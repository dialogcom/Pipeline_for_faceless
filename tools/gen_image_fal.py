#!/usr/bin/env python3
"""
gen_image_fal.py — AI still images via the DIRECT fal.ai queue API. Sibling of gen_clip.py
(same queue-based request/poll pattern), for the image case.

Model-agnostic BY DESIGN: the fal model id is just a string, so swapping models is a --model
flag, never a code change. Extra model-specific inputs pass through with --set key=value.
Saves the image + a sidecar .json (model, payload, request id) for reproducibility.

Usage:
  python tools/gen_image_fal.py --prompt "..." --out shorts/ch-1/assets/frame.png
  python tools/gen_image_fal.py --model fal-ai/flux-pro/v1.1-ultra --prompt "..." \\
      --aspect 9:16 --out frame.png

  --model     fal model id (default: fal-ai/flux-pro/v1.1-ultra)
  --prompt    text prompt (sent as "prompt")
  --aspect    aspect_ratio (default 9:16)
  --set k=v   any extra payload field, repeatable (numbers/bools auto-parsed; JSON accepted)
  --timeout   seconds to wait (default 300)
  --dry-run   print the payload, no API call

Needs FAL_KEY in .env (https://fal.ai/dashboard/keys). Costs are per-model on fal's pricing
page — check before generating; state the cost when proposing a batch of images.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MODEL = "fal-ai/flux-pro/v1.1-ultra"
QUEUE = "https://queue.fal.run"


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


def parse_val(v):
    try:
        return json.loads(v)
    except (ValueError, json.JSONDecodeError):
        return v


def req_json(url, key, body=None, method=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method,
                               headers={"Authorization": f"Key {key}",
                                        "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        sys.exit(f"fal API error {e.code} at {url}:\n{e.read().decode()[:800]}")


def find_image_url(obj):
    """Walk any response schema for the first image-looking url."""
    if isinstance(obj, dict):
        u = obj.get("url")
        if isinstance(u, str) and (obj.get("content_type", "").startswith("image/") or
                                    any(u.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp"))):
            return u
        for v in obj.values():
            found = find_image_url(v)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = find_image_url(v)
            if found:
                return found
    return None


def gen_image_fal(prompt, out_path, model=DEFAULT_MODEL, aspect="9:16", extra=None, timeout=300):
    payload = {"prompt": prompt, "aspect_ratio": aspect, **(extra or {})}
    key = load_env().get("FAL_KEY", "").strip()
    if not key:
        sys.exit("FAL_KEY not set in .env (get one at https://fal.ai/dashboard/keys)")

    sub = req_json(f"{QUEUE}/{model}", key, body=payload)
    status_url = sub.get("status_url") or f"{QUEUE}/{model}/requests/{sub['request_id']}/status"
    response_url = sub.get("response_url") or f"{QUEUE}/{model}/requests/{sub['request_id']}"
    print(f"  queued: {sub.get('request_id')}", file=sys.stderr)

    t0 = time.time()
    last = ""
    while True:
        st = req_json(f"{status_url}?logs=1", key)
        s = st.get("status", "?")
        if s != last:
            print(f"    {s}  (+{int(time.time()-t0)}s)", file=sys.stderr)
            last = s
        if s == "COMPLETED":
            break
        if s in ("FAILED", "ERROR", "CANCELLED"):
            sys.exit(f"generation {s}: {json.dumps(st)[:800]}")
        if time.time() - t0 > timeout:
            sys.exit(f"timeout after {int(timeout)}s (request {sub.get('request_id')} may still finish; "
                     f"re-poll {response_url})")
        time.sleep(2)

    result = req_json(response_url, key)
    img_url = find_image_url(result)
    if not img_url:
        sys.exit(f"no image url found in response: {json.dumps(result)[:800]}")

    urllib.request.urlretrieve(img_url, out_path)
    sidecar = os.path.splitext(out_path)[0] + ".json"
    with open(sidecar, "w", encoding="utf-8") as f:
        json.dump({"model": model, "payload": payload, "request_id": sub.get("request_id"),
                   "source_url": img_url}, f, ensure_ascii=False, indent=2)
    print(f"  img ok -> {out_path}", file=sys.stderr)
    return out_path


def main():
    args = sys.argv[1:]
    dry = "--dry-run" in args

    prompt = get_arg(args, "--prompt")
    out = get_arg(args, "--out")
    if not prompt or not out:
        sys.exit("need --prompt and --out (see file header)")

    model = get_arg(args, "--model", DEFAULT_MODEL)
    aspect = get_arg(args, "--aspect", "9:16")
    timeout = float(get_arg(args, "--timeout", "300"))
    extra = {}
    for i, a in enumerate(args):
        if a == "--set":
            k, _, v = args[i + 1].partition("=")
            extra[k] = parse_val(v)

    print(f"model = {model}  aspect = {aspect}")
    if dry:
        print("payload =", json.dumps({"prompt": prompt, "aspect_ratio": aspect, **extra}, indent=2)[:600])
        print("[dry-run] no API call.")
        return

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    gen_image_fal(prompt, out, model=model, aspect=aspect, extra=extra, timeout=timeout)


if __name__ == "__main__":
    main()
