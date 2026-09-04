#!/usr/bin/env python3
"""
gen_image_modelscope.py — AI still images via ModelScope's async image-generation API
(Qwen-Image and other models hosted there). Sibling of gen_image_fal.py / gen_image_cloudflare.py
— same role, different provider. Async submit-then-poll pattern (unlike fal's queue, ModelScope's
task_status/output_images shape is its own).

Model-agnostic BY DESIGN: the model id is just a string, so swapping models is a --model flag.

Usage:
  python tools/gen_image_modelscope.py --prompt "..." --out shorts/ch-1/assets/frame.png
  python tools/gen_image_modelscope.py --model Qwen/Qwen-Image --prompt "..." \\
      --size 936x1664 --out frame.png

  --model     ModelScope model id (default: Qwen/Qwen-Image-2512)
  --prompt    text prompt (Chinese or English, <2000 chars)
  --size      "WIDTHxHEIGHT" (default 936x1664 — closest 9:16 vertical within Qwen-Image's
              documented [64,1664] per-side cap; NOTE this is short of our usual 1080x1920,
              so build_narrated_short.py's oversize-crop still applies at render time)
  --negative  negative_prompt (optional)
  --seed      int, 0 to 2^31-1 (optional)
  --steps     sampling steps, 1-100 (optional, provider default if omitted)
  --guidance  guidance coefficient, 1.5-20 (optional, provider default if omitted)
  --timeout   seconds to wait (default 300)
  --dry-run   print the payload, no API call

Needs MODELSCOPE_API_KEY in .env (modelscope.cn -> account -> Access Tokens).
Pricing is per-model on ModelScope's own pages — check before generating a batch.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_URL = "https://api-inference.modelscope.cn/"
DEFAULT_MODEL = "Qwen/Qwen-Image-2512"
DEFAULT_SIZE = "936x1664"


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


def req_json(url, key, body=None, method=None, extra_headers=None):
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", **(extra_headers or {})}
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        sys.exit(f"ModelScope API error {e.code} at {url}:\n{e.read().decode()[:1000]}")


def gen_image_modelscope(prompt, out_path, model=DEFAULT_MODEL, size=DEFAULT_SIZE,
                          negative_prompt=None, seed=None, steps=None, guidance=None, timeout=300):
    key = load_env().get("MODELSCOPE_API_KEY", "").strip()
    if not key:
        sys.exit("MODELSCOPE_API_KEY not set in .env (modelscope.cn -> account -> Access Tokens)")

    payload = {"model": model, "prompt": prompt}
    if size:
        payload["size"] = size
    if negative_prompt:
        payload["negative_prompt"] = negative_prompt
    if seed is not None:
        payload["seed"] = seed
    if steps is not None:
        payload["steps"] = steps
    if guidance is not None:
        payload["guidance"] = guidance

    sub = req_json(f"{BASE_URL}v1/images/generations", key, body=payload,
                    extra_headers={"X-ModelScope-Async-Mode": "true"})
    task_id = sub.get("task_id")
    if not task_id:
        sys.exit(f"no task_id in submit response: {json.dumps(sub)[:800]}")
    print(f"  queued: {task_id}", file=sys.stderr)

    t0 = time.time()
    last = ""
    while True:
        data = req_json(f"{BASE_URL}v1/tasks/{task_id}", key,
                         extra_headers={"X-ModelScope-Task-Type": "image_generation"})
        status = data.get("task_status", "?")
        if status != last:
            print(f"    {status}  (+{int(time.time()-t0)}s)", file=sys.stderr)
            last = status
        if status == "SUCCEED":
            break
        if status == "FAILED":
            sys.exit(f"generation FAILED: {json.dumps(data)[:800]}")
        if time.time() - t0 > timeout:
            sys.exit(f"timeout after {int(timeout)}s (task {task_id} may still finish; re-poll it)")
        time.sleep(3)

    img_url = (data.get("output_images") or [None])[0]
    if not img_url:
        sys.exit(f"no output_images in response: {json.dumps(data)[:800]}")

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    urllib.request.urlretrieve(img_url, out_path)
    sidecar = os.path.splitext(out_path)[0] + ".json"
    with open(sidecar, "w", encoding="utf-8") as f:
        json.dump({"model": model, "payload": payload, "task_id": task_id, "source_url": img_url},
                   f, ensure_ascii=False, indent=2)
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
    size = get_arg(args, "--size", DEFAULT_SIZE)
    negative = get_arg(args, "--negative")
    seed = get_arg(args, "--seed")
    seed = int(seed) if seed is not None else None
    steps = get_arg(args, "--steps")
    steps = int(steps) if steps is not None else None
    guidance = get_arg(args, "--guidance")
    guidance = float(guidance) if guidance is not None else None
    timeout = float(get_arg(args, "--timeout", "300"))

    print(f"model = {model}  size = {size}")
    if dry:
        payload = {"model": model, "prompt": prompt, "size": size, "negative_prompt": negative,
                   "seed": seed, "steps": steps, "guidance": guidance}
        print("payload =", json.dumps(payload, ensure_ascii=False, indent=2)[:600])
        print("[dry-run] no API call.")
        return

    gen_image_modelscope(prompt, out, model=model, size=size, negative_prompt=negative,
                          seed=seed, steps=steps, guidance=guidance, timeout=timeout)


if __name__ == "__main__":
    main()
