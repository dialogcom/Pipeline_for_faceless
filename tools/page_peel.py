#!/usr/bin/env python3
"""
page_peel.py — концовка «отворот страницы»: кадр отгибается, под ним афоризм.

Кадр видео отгибается от нижнего левого угла, как страница книги. Под ним
открывается тёмная подложка с афоризмом. Отогнутый клин рисуется изнанкой
листа - светлой, с тенью по линии сгиба.

Usage:
  python tools/page_peel.py --video in.mp4 --text "Строка\nвторая" --out out.mp4
  python tools/page_peel.py --video in.mp4 --text "..." --preview кадр.png
  --author "Шри Чинмой"   подпись под афоризмом
  --peel 1.6              сколько секунд длится отгиб
  --hold 3.2              сколько секунд держится раскрытым
  --fps 30

Нужны Pillow и ffmpeg.
"""
import argparse
import math
import os
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAPER = (232, 230, 226)
PAPER_EDGE = (198, 195, 190)
UNDER = (14, 22, 48)
INK = (245, 246, 250)
AUTHOR_INK = (150, 170, 215)
FONTS = (
    os.path.join(ROOT, "media", "library", "fonts", "Inter-Bold.ttf"),
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def font(size):
    for path in FONTS:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def ease(t):
    """Плавный старт и мягкая остановка - лист не дёргается."""
    return t * t * (3 - 2 * t)


def reflect(point, a, b):
    """Отражение точки относительно прямой AB: изнанка листа - зеркало лицевой."""
    (px, py), (ax, ay), (bx, by) = point, a, b
    dx, dy = bx - ax, by - ay
    denom = dx * dx + dy * dy
    if denom == 0:
        return point
    t = ((px - ax) * dx + (py - ay) * dy) / denom
    cx, cy = ax + t * dx, ay + t * dy
    return (2 * cx - px, 2 * cy - py)


def underlay(size, text, author):
    """Подложка с афоризмом - её видно в раскрытом углу."""
    w, h = size
    layer = Image.new("RGBA", size, (*UNDER, 255))
    draw = ImageDraw.Draw(layer)
    lines = text.split("\n")
    fs = max(30, int(w * 0.047))
    f = font(fs)
    line_h = int(fs * 1.34)
    total = line_h * len(lines)
    # Текст живёт в нижней левой четверти - там, где угол раскрывается шире всего.
    x = int(w * 0.075)
    y = int(h * 0.855) - total
    for i, line in enumerate(lines):
        draw.text((x, y + i * line_h), line, font=f, fill=INK)
    if author:
        fa = font(int(fs * 0.62))
        draw.text((x, y + total + int(fs * 0.5)), author, font=fa, fill=AUTHOR_INK)
    return layer


def peel_frame(size, progress, under):
    """Один кадр наложения: прозрачно там, где лист ещё лежит."""
    w, h = size
    p = ease(max(0.0, min(1.0, progress)))
    if p <= 0.001:
        return Image.new("RGBA", size, (0, 0, 0, 0))

    # Сгиб: одна точка ползёт вверх по левому краю, вторая вправо по нижнему.
    # Множители разные, иначе в правом нижнем углу остаётся осколок исходного кадра.
    a = (0.0, h * (1.0 - min(1.0, p * 1.15)))
    b = (w * min(1.0, p * 1.39), float(h))
    corner = (0.0, float(h))

    out = Image.new("RGBA", size, (0, 0, 0, 0))
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).polygon([a, b, corner], fill=255)
    out.paste(under, (0, 0), mask)

    # Изнанка листа: тот же треугольник, отражённый через линию сгиба.
    flap = [reflect(corner, a, b), a, b]
    # Изнанка не заливка, а бумага: у сгиба светлее, к дальнему краю уходит в тень.
    grad = Image.new("RGBA", size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    far = flap[0]
    steps = 40
    for i in range(steps):
        t0, t1 = i / steps, (i + 1) / steps
        shade = 1.0 - 0.19 * t1
        tone = tuple(int(c * shade) for c in PAPER)
        quad = [
            (a[0] + (far[0] - a[0]) * t0, a[1] + (far[1] - a[1]) * t0),
            (b[0] + (far[0] - b[0]) * t0, b[1] + (far[1] - b[1]) * t0),
            (b[0] + (far[0] - b[0]) * t1, b[1] + (far[1] - b[1]) * t1),
            (a[0] + (far[0] - a[0]) * t1, a[1] + (far[1] - a[1]) * t1),
        ]
        gd.polygon(quad, fill=(*tone, 255))
    sheet = Image.new("RGBA", size, (0, 0, 0, 0))
    mask_flap = Image.new("L", size, 0)
    ImageDraw.Draw(mask_flap).polygon(flap, fill=255)
    sheet.paste(grad, (0, 0), mask_flap)
    ImageDraw.Draw(sheet).line([a, b], fill=(*PAPER_EDGE, 255), width=max(2, int(w * 0.004)))

    shadow = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).polygon(flap, fill=(0, 0, 0, 120))
    shadow = shadow.filter(ImageFilter.GaussianBlur(int(w * 0.018)))
    out = Image.alpha_composite(out, shadow)
    return Image.alpha_composite(out, sheet)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--text", required=True)
    ap.add_argument("--author", default="Шри Чинмой")
    ap.add_argument("--out")
    ap.add_argument("--preview")
    ap.add_argument("--peel", type=float, default=1.6)
    ap.add_argument("--max-peel", type=float, default=0.72,
                    help="насколько далеко отгибается лист: 1.0 съедает кадр целиком")
    ap.add_argument("--hold", type=float, default=3.2)
    ap.add_argument("--fps", type=int, default=30)
    args = ap.parse_args()

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:format=duration", "-of", "csv=p=0", args.video],
        capture_output=True, text=True, check=True).stdout.split()
    w, h = (int(x) for x in probe[0].split(",")[:2])
    duration = float(probe[-1])
    size = (w, h)
    text = args.text.replace("\\n", "\n")
    under = underlay(size, text, args.author)

    if args.preview:
        frame = tempfile.mktemp(suffix=".png")
        subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{duration - 1:.2f}", "-i", args.video,
                        "-frames:v", "1", frame, "-y"], check=True)
        base = Image.open(frame).convert("RGBA")
        Image.alpha_composite(base, peel_frame(size, args.max_peel, under)).convert("RGB").save(args.preview)
        os.unlink(frame)
        print(f"превью -> {args.preview}")
        return

    if not args.out:
        sys.exit("нужен --out или --preview")

    total = args.peel + args.hold
    start = max(0.0, duration - total)
    tmp = tempfile.mkdtemp(prefix="peel-")
    try:
        frames = int(total * args.fps)
        for i in range(frames):
            t = i / args.fps
            raw = t / args.peel if args.peel > 0 else 1.0
            layer = peel_frame(size, min(raw, 1.0) * args.max_peel, under)
            layer.save(os.path.join(tmp, f"f{i:05d}.png"))
        subprocess.run([
            "ffmpeg", "-v", "error", "-i", args.video,
            "-framerate", str(args.fps), "-i", os.path.join(tmp, "f%05d.png"),
            "-filter_complex",
            f"[1:v]setpts=PTS-STARTPTS+{start}/TB[ov];[0:v][ov]overlay=0:0:eof_action=pass[v]",
            "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "medium",
            "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "copy", args.out, "-y",
        ], check=True)
        print(f"готово -> {args.out}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
