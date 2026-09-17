#!/usr/bin/env python3
"""
gen_image_alibaba.py — AI still images via Alibaba Model Studio. Sibling of
gen_image_cloudflare.py / gen_image_fal.py / gen_image_modelscope.py — same role, different
provider. Currently the best-quality route we have that is NOT metered per frame: native
1080x1920 output, understands Russian prompts, ~50-85s per frame.

TWO ROUTES, and they are not interchangeable (proven 24-25.08.2026):

  plan   — the subscription key from Model Studio -> Token Plan (starts `sk-sp-`), used
           against the PLAN-EXCLUSIVE host token-plan.<region>.maas.aliyuncs.com. Image
           models wan2.7-image / wan2.7-image-pro are inside the plan. Synchronous only:
           the async task API answers "current user api does not support asynchronous
           calls", so wan* here goes through the multimodal (sync) endpoint, not the
           text2image one. This is the route that works today.
  paygo  — an ordinary Model Studio API key (starts `sk-`, from console -> API-KEY) against
           dashscope-intl / dashscope. qwen-image* is synchronous, wan* is async
           (POST -> task_id -> poll /tasks/<id>).

The `o1__…` key (qwen-code CLI plan) is not a Model Studio key at all and is rejected on
every host — do not put it in ALIBABA_API_KEY.

Region matters on the paygo route: a key issued in ap-southeast-1 (Singapore) is NOT valid
against the Beijing host and vice versa — the wrong pairing returns `InvalidApiKey`, which
reads like a bad key rather than a bad host. ALIBABA_REGION in .env selects it.

Usage:
  python tools/gen_image_alibaba.py --prompt "..." --out frame.png
  python tools/gen_image_alibaba.py --model wan2.7-image-pro --prompt "..." --out frame.png
  python tools/gen_image_alibaba.py --models        # what this key may call
  python tools/gen_image_alibaba.py --probe         # is the key accepted at all? (free)

  --model     model id (default: wan2.7-image on the plan route, qwen-image-2.0 on paygo)
  --prompt    text prompt (Russian works — no need to translate)
  --width     default 1080          --height    default 1920
  --negative  negative prompt (a sensible default one is applied server-side)
  --seed      integer, for a reproducible re-roll
  --extend    let the model rewrite/expand the prompt (off by default: we write our own)
  --route     plan | paygo (default: plan when ALIBABA_TOKEN_PLAN_KEY is set)
  --timeout   seconds to wait (default 300 — a frame takes 50-85s)
  --dry-run   print the payload, no API call

Needs ALIBABA_TOKEN_PLAN_KEY (plan) or ALIBABA_API_KEY (paygo) in .env, optionally
ALIBABA_REGION (default ap-southeast-1). Plan usage burns the 7-day quota shown in the
console; there is no API for the remaining balance, so check the Token Plan page.
"""
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_REGION = "ap-southeast-1"
PLAN_DEFAULT_MODEL = "wan2.7-image"
PAYGO_DEFAULT_MODEL = "qwen-image-2.0"

PAYGO_HOSTS = {
    "ap-southeast-1": "https://dashscope-intl.aliyuncs.com",
    "cn-beijing": "https://dashscope.aliyuncs.com",
}


def load_env():
    env = {}
    p = os.path.join(ROOT, ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return {**env, **os.environ}


def get_arg(args, name, default=None):
    return args[args.index(name) + 1] if name in args else default


def route_for(env, forced=None):
    """Which key, which host. Returns (route, key, host, region)."""
    region = env.get("ALIBABA_REGION", DEFAULT_REGION)
    plan_key, paygo_key = env.get("ALIBABA_TOKEN_PLAN_KEY"), env.get("ALIBABA_API_KEY")
    route = forced or ("plan" if plan_key else "paygo")
    if route == "plan":
        if not plan_key:
            sys.exit("ALIBABA_TOKEN_PLAN_KEY not set (.env) — нужен ключ из Token Plan")
        return route, plan_key, f"https://token-plan.{region}.maas.aliyuncs.com", region
    if not paygo_key:
        sys.exit("ALIBABA_API_KEY not set (.env)")
    if region not in PAYGO_HOSTS:
        sys.exit(f"unknown ALIBABA_REGION {region!r} (expected one of {', '.join(PAYGO_HOSTS)})")
    return route, paygo_key, PAYGO_HOSTS[region], region


def _post(url, key, body, extra_headers=None, timeout=300):
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    headers.update(extra_headers or {})
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _get(url, key, timeout=60):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _explain(e):
    """Model Studio puts the useful part in the body, not the status line."""
    detail = e.read().decode() if hasattr(e, "read") else str(e)
    try:
        j = json.loads(detail)
        err = j.get("error") if isinstance(j.get("error"), dict) else {}
        code = j.get("code") or err.get("code", "")
        msg = j.get("message") or err.get("message", "")
        if code in ("InvalidApiKey", "invalid_api_key"):
            msg += ("  [ключ и хост не из одной пары: ключ Token Plan (sk-sp-) ходит только "
                    "на token-plan.<region>.maas.aliyuncs.com, обычный ключ Model Studio "
                    "(sk-) — только на dashscope; ключ qwen-code (o1__) не подходит никуда. "
                    "Проверьте --route и ALIBABA_REGION]")
        if code == "AccessDenied" and "asynchronous" in msg:
            msg += ("  [на тарифном плане асинхронного API нет — wan* здесь идёт через "
                    "синхронный multimodal-эндпойнт]")
        return f"{code}: {msg}" if code else detail[:800]
    except Exception:
        return detail[:800]


RETRYABLE = ("ResponseTimeout", "InternalError", "ServiceUnavailable", "Throttling")


def _retryable(e):
    """A stalled generation and a stalled download both look like success-in-progress right
    up to the moment they don't. Both are worth one more try; a rejected prompt is not."""
    if isinstance(e, (socket.timeout, TimeoutError, urllib.error.URLError)) \
            and not isinstance(e, urllib.error.HTTPError):
        return True
    if isinstance(e, urllib.error.HTTPError):
        if e.code >= 500:
            return True
        try:
            body = e.read()
            e.read = lambda _b=body: _b      # _explain still needs to read it later
            return json.loads(body).get("code") in RETRYABLE
        except Exception:
            return False
    return False


def _with_retries(fn, attempts=3, what="запрос"):
    for n in range(1, attempts + 1):
        try:
            return fn()
        except Exception as e:
            if n == attempts or not _retryable(e):
                raise
            print(f"  {what}: попытка {n} сорвалась ({type(e).__name__}), повтор через 5 c",
                  file=sys.stderr)
            time.sleep(5)


def _params(width, height, negative=None, seed=None, extend=False):
    p = {"size": f"{width}*{height}", "watermark": False, "prompt_extend": bool(extend)}
    if negative:
        p["negative_prompt"] = negative
    if seed is not None:
        p["seed"] = int(seed)
    return p


def gen_image_alibaba(prompt, out_path, model=None, width=1080, height=1920, timeout=300,
                      negative=None, seed=None, extend=False, forced_route=None):
    env = load_env()
    route, key, host, _ = route_for(env, forced_route)
    model = model or (PLAN_DEFAULT_MODEL if route == "plan" else PAYGO_DEFAULT_MODEL)
    params = _params(width, height, negative, seed, extend)

    try:
        if route == "paygo" and model.startswith("wan"):
            task = _post(f"{host}/api/v1/services/aigc/text2image/image-synthesis", key,
                         {"model": model, "input": {"prompt": prompt},
                          "parameters": {**params, "n": 1}},
                         {"X-DashScope-Async": "enable"})
            tid = task["output"]["task_id"]
            deadline = time.time() + timeout
            while time.time() < deadline:
                st = _get(f"{host}/api/v1/tasks/{tid}", key)
                status = st["output"]["task_status"]
                if status == "SUCCEEDED":
                    url = st["output"]["results"][0]["url"]
                    break
                if status in ("FAILED", "CANCELED", "UNKNOWN"):
                    sys.exit(f"alibaba task {status}: {json.dumps(st, ensure_ascii=False)[:500]}")
                time.sleep(3)
            else:
                sys.exit(f"alibaba task timed out after {timeout}s")
        else:
            resp = _with_retries(
                lambda: _post(f"{host}/api/v1/services/aigc/multimodal-generation/generation",
                              key,
                              {"model": model,
                               "input": {"messages": [{"role": "user",
                                                       "content": [{"text": prompt}]}]},
                               "parameters": params},
                              timeout=timeout),
                what="генерация")
            content = resp["output"]["choices"][0]["message"]["content"]
            url = next(c["image"] for c in content if "image" in c)
    except urllib.error.HTTPError as e:
        sys.exit(f"Alibaba API error: {_explain(e)}")

    # The picture is already paid for by the time it has a URL, so a dropped download is the
    # one failure worth fighting for. Written via a temp file: a half-received PNG must never
    # land under the real name, or the build's filename cache would treat it as done.
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    tmp = f"{out_path}.part"

    def fetch():
        with urllib.request.urlopen(url, timeout=180) as r:
            data = r.read()
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, out_path)

    try:
        _with_retries(fetch, what="скачивание")
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return out_path


def list_models(forced_route=None):
    """What this key may actually call — free, and the fastest sanity check there is."""
    env = load_env()
    route, key, host, region = route_for(env, forced_route)
    print(f"маршрут {route}  регион {region} -> {host}")
    print(f"ключ: длина {len(key)}, префикс {key[:6]}…")
    try:
        data = _get(f"{host}/compatible-mode/v1/models", key)
    except urllib.error.HTTPError as e:
        print(f"ОТКАЗ: {_explain(e)}")
        return 1
    ids = sorted(m.get("id", "") for m in data.get("data", []))
    images = [m for m in ids if "image" in m or m.startswith("wan")]
    print(f"КЛЮЧ ПРИНЯТ — моделей доступно {len(ids)}")
    print("  картиночные:", ", ".join(images) or "нет — этим ключом кадры не сделать")
    print("  остальные:  ", ", ".join(m for m in ids if m not in images))
    return 0 if images else 1


def probe(forced_route=None):
    return list_models(forced_route)


def main():
    args = sys.argv[1:]
    forced = get_arg(args, "--route")
    if forced and forced not in ("plan", "paygo"):
        sys.exit("--route must be plan or paygo")
    if "--models" in args or "--probe" in args:
        sys.exit(list_models(forced))
    prompt, out = get_arg(args, "--prompt"), get_arg(args, "--out")
    if not prompt or not out:
        sys.exit("usage: gen_image_alibaba.py --prompt '...' --out F [--model M] "
                 "[--width W] [--height H] [--negative N] [--seed S] [--extend] "
                 "[--route plan|paygo] | --models")
    env = load_env()
    route, _, host, _ = route_for(env, forced)
    model = get_arg(args, "--model") or (PLAN_DEFAULT_MODEL if route == "plan"
                                         else PAYGO_DEFAULT_MODEL)
    w, h = int(get_arg(args, "--width", 1080)), int(get_arg(args, "--height", 1920))
    seed = get_arg(args, "--seed")
    if "--dry-run" in args:
        print(json.dumps({"route": route, "host": host, "model": model, "prompt": prompt,
                          "parameters": _params(w, h, get_arg(args, "--negative"), seed,
                                                "--extend" in args)},
                         ensure_ascii=False, indent=2))
        return
    print(f"маршрут {route}  model = {model}  size = {w}*{h}", file=sys.stderr)
    t = time.time()
    p = gen_image_alibaba(prompt, out, model=model, width=w, height=h,
                          timeout=int(get_arg(args, "--timeout", 300)),
                          negative=get_arg(args, "--negative"), seed=seed,
                          extend="--extend" in args, forced_route=forced)
    print(f"{time.time() - t:.0f}s", file=sys.stderr)
    print(p)


if __name__ == "__main__":
    main()
