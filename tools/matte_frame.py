#!/usr/bin/env python3
"""
matte_frame.py — border-connected-component matte for busy/photographic backgrounds
(character reference photos, video frames), as opposed to tools/cutout.py's "isolated
on white" gen_image.py case.

Samples border pixel colors directly (handles multi-tone backgrounds like sky+ground,
not just a single flat color), then uses connected-components to keep only regions
touching the image edge as background — so internal dark linework (hair, brows, shirt
folds) that happens to be close to a background color doesn't get punched out along with
it. rembg (ML matting) isn't usable on this machine (onnxruntime's prebuilt binaries
need macOS 15+), hence this classical fallback.

Best on dark or saturated-color backgrounds with good contrast against skin/clothing —
proven reliable there (see media/projects/petya-character/cutouts/). Struggles when the
subject's clothing is close in tone to the background (a white shirt against a cream
wall will bleed into "background" and get erased) — check the result before trusting it,
and reshoot/re-pick a frame with a more contrasty backdrop if it comes out holey.

Usage:
  python tools/matte_frame.py in.png out.png [tolerance]
  tolerance  distance-to-nearest-border-color below which a pixel counts as
             background-like, pre connected-components   [default 38]
"""
import sys

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage


def matte(path_in, path_out, tol=38, border_n=60, feather=1, pad=24):
    img = Image.open(path_in).convert("RGB")
    arr = np.asarray(img).astype(np.float32)
    h, w, _ = arr.shape

    # sample border pixel colors (subset, evenly spaced) as the background reference set
    idx = []
    for i in range(border_n):
        t = i / border_n
        idx.append((0, int(t * (w - 1))))
        idx.append((h - 1, int(t * (w - 1))))
        idx.append((int(t * (h - 1)), 0))
        idx.append((int(t * (h - 1)), w - 1))
    ref = np.array([arr[y, x] for y, x in idx])  # (N,3)

    flat = arr.reshape(-1, 3)
    mind = np.full(flat.shape[0], 1e9, dtype=np.float32)
    for r in ref:
        d = np.sum((flat - r) ** 2, axis=1)
        mind = np.minimum(mind, d)
    mind = mind.reshape(h, w) ** 0.5

    bg_like = mind < tol  # "background-colored" mask, pre connected-components

    labeled, _ = ndimage.label(bg_like)
    border_labels = set(labeled[0, :]) | set(labeled[-1, :]) | set(labeled[:, 0]) | set(labeled[:, -1])
    border_labels.discard(0)
    true_bg = np.isin(labeled, list(border_labels))

    alpha = np.where(true_bg, 0, 255).astype(np.uint8)
    alpha_img = Image.fromarray(alpha, mode="L")
    if feather > 0:
        alpha_img = alpha_img.filter(ImageFilter.GaussianBlur(feather))

    rgba = img.convert("RGBA")
    rgba.putalpha(alpha_img)

    bbox = alpha_img.getbbox()
    if bbox:
        l, t, r, b = bbox
        l = max(0, l - pad)
        t = max(0, t - pad)
        r = min(w, r + pad)
        b = min(h, b + pad)
        rgba = rgba.crop((l, t, r, b))

    rgba.save(path_out)
    print(f"{path_out}  ({rgba.width}x{rgba.height})")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: python tools/matte_frame.py in.png out.png [tolerance]")
        sys.exit(1)
    matte(sys.argv[1], sys.argv[2], tol=float(sys.argv[3]) if len(sys.argv) > 3 else 38)
