#!/usr/bin/env python3
"""
gen_image_cloudflare.py — AI still images via Cloudflare Workers AI. Sibling of gen_image.py
(direct Gemini) and gen_image_fal.py (fal.ai queue) — same role, different provider.

Model-agnostic BY DESIGN: the model id is just a string, so swapping models is a --model
flag. Default is Stable Diffusion XL, which accepts explicit width/height — needed for our
1080x1920 vertical composition instead of a square-only output that would need a lossy crop.

**Size handling (fixed 2026-08-21).** Not every Workers AI model takes width/height:
FLUX.1-schnell rejects the request outright, and this script used to send them
unconditionally, so the proven Flux route crashed here and had to be re-written as a
throwaway script every session (see vox-shorts/HANDOFF.md, which recorded the workaround).
Now: models known to be square-only are called without the size fields, and any other model
that *answers* with a size complaint is retried once without them. So a square-only model
returns its square, a sizing model returns 1080x1920, and neither needs a special script.
A square still cover-crops to 9:16 downstream (build_bg scales with
force_original_aspect_ratio=increase), losing the sides — prefer a sizing model when the
composition matters.

Usage:
  python tools/gen_image_cloudflare.py --prompt "..." --out shorts/ch-1/assets/frame.png
  python tools/gen_image_cloudflare.py --model @cf/black-forest-labs/flux-1-schnell \\
      --prompt "..." --out frame.png          # square-only model, no width/height

  --model     Workers AI model id (default: @cf/stabilityai/stable-diffusion-xl-base-1.0)
  --prompt    text prompt
  --width     default 1080 (SDXL: 256-2048)
  --height    default 1920 (SDXL: 256-2048)
  --set k=v   any extra payload field, repeatable (numbers/bools auto-parsed; JSON accepted)
  --dry-run   print the payload, no API call

Needs CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID in .env (dash.cloudflare.com).
Pricing is per-model on Cloudflare's Workers AI pricing page — check before generating.
"""
import json
import os
import sys
import base64
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MODEL = "@cf/stabilityai/stable-diffusion-xl-base-1.0"

# Models that reject width/height. Substring match, so version suffixes are covered.
SQUARE_ONLY = ("flux-1-schnell", "flux-schnell")
# An error naming any of these means "you sent a size I do not take" — worth one retry
# without the size rather than failing a paid batch on its first still.
SIZE_COMPLAINTS = ("width", "height", "unexpected", "not allowed", "unrecognized",
                   "additionalproperties", "invalid")


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


def _post(url, token, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.headers.get("Content-Type", ""), resp.read()


def gen_image_cloudflare(prompt, out_path, model=DEFAULT_MODEL, width=1080, height=1920, extra=None):
    env = load_env()
    token = env.get("CLOUDFLARE_API_TOKEN", "").strip()
    account_id = env.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    if not token or not account_id:
        sys.exit("CLOUDFLARE_API_TOKEN and/or CLOUDFLARE_ACCOUNT_ID not set in .env "
                  "(dash.cloudflare.com -> My Profile -> API Tokens, and Account ID from the dashboard sidebar)")

    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
    base = {"prompt": prompt, **(extra or {})}
    sized = not any(tag in model for tag in SQUARE_ONLY) and width and height

    try:
        content_type, raw = _post(url, token, {**base, "width": width, "height": height} if sized else base)
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        if sized and any(w in body.lower() for w in SIZE_COMPLAINTS):
            print(f"  {model} rejected width/height — retrying square "
                  f"(it will be cover-cropped to 9:16 later)", file=sys.stderr)
            try:
                content_type, raw = _post(url, token, base)
            except urllib.error.HTTPError as e2:
                sys.exit(f"Cloudflare API error {e2.code} at {url}:\n{e2.read().decode()[:1000]}")
        else:
            sys.exit(f"Cloudflare API error {e.code} at {url}:\n{body[:1000]}")

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    if content_type.startswith("image/"):
        with open(out_path, "wb") as f:
            f.write(raw)
    else:
        # JSON-wrapped response (e.g. flux-1-schnell): {"result": {"image": "<base64>"}, "success": true, ...}
        data = json.loads(raw)
        if not data.get("success", True):
            sys.exit(f"Cloudflare generation failed: {json.dumps(data.get('errors'))[:800]}")
        b64 = data.get("result", {}).get("image")
        if not b64:
            sys.exit(f"no image data found in response: {json.dumps(data)[:800]}")
        with open(out_path, "wb") as f:
            f.write(base64.b64decode(b64))

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
    width = int(get_arg(args, "--width", "1080"))
    height = int(get_arg(args, "--height", "1920"))
    extra = {}
    for i, a in enumerate(args):
        if a == "--set":
            k, _, v = args[i + 1].partition("=")
            extra[k] = parse_val(v)

    sized = not any(tag in model for tag in SQUARE_ONLY) and width and height
    print(f"model = {model}  size = {f'{width}x{height}' if sized else 'square (model takes no width/height)'}")
    if dry:
        payload = {"prompt": prompt, **({"width": width, "height": height} if sized else {}), **extra}
        print("payload =", json.dumps(payload, indent=2)[:600])
        print("[dry-run] no API call.")
        return

    gen_image_cloudflare(prompt, out, model=model, width=width, height=height, extra=extra)


if __name__ == "__main__":
    main()
