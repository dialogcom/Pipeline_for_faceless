#!/usr/bin/env python3
"""
build_narrated_short.py — assemble one "narrated short" end to end (narrated-shorts track).

The format: a single narrator (tools/gen_voice_inworld.py) over 1-2 AI-generated still
images (tools/gen_image.py-equivalent via OpenRouter's unified /images API — used here
directly since this track needs 9:16 stills with no reference-image support beyond what
OpenRouter's google/gemini-3.1-flash-image already gives), Ken-Burns-animated and
crossfaded, with word-synced burned-in captions and a persistent corner logo. Proven on
narrated-shorts/guru-i-uchenik (17 shorts, 2026-08-09) — see that project's scripts.json
for a worked example of the spec format this CLI consumes.

Why ffmpeg filters instead of Remotion: this track has no per-shot custom animation code,
so a plain filter_complex pipeline (scale/crop/zoompan/xfade/overlay) is simpler and faster
to batch across many short episodes than spinning up a Remotion composition per video.

Usage (single short, spec = one JSON object per the schema below):
  python tools/build_narrated_short.py --spec-file narrated-shorts/guru-i-uchenik/scripts.json --id 18

Usage (as a library):
  from build_narrated_short import build_narrated_short, gen_image
  ...

Spec schema (one entry in the scripts.json array):
  {
    "id": 18, "slug": "kebab-case-name",
    "hook": "...", "vo": "...", "ending": "...",     # concatenated = the full narration
    "images": [["<English gen_image prompt>", 0.55], ["<prompt>", 0.45]],  # duration fractions sum to 1.0
    "voice": {"voice_id": "Nikolai", "model": "inworld-tts-1.5-max", "temperature": 1.1, "speaking_rate": 1.0},  # optional, has defaults
    "image_provider": "alibaba",      # optional: openrouter (default) | alibaba | cloudflare | modelscope
    "image_model": "wan2.7-image",    # optional, provider-specific; omit for that provider's default
    "image_style": ", authentic 1890s archival photograph, ...",  # optional, appended to every prompt
    "image_negative": "color photograph, modern digital render, ..."  # optional, alibaba only
  }

Outputs (relative to the scripts.json's directory, gitignored — see narrated-shorts/DESIGN.md):
  voice/short-<id>-<slug>.mp3 + .words.json
  output/short-<id>-<slug>.mp4

Generated images are COMMITTED (paid, non-reproducible) under
media/projects/<series-name>/images/s<id>_<i>.png — series-name is the scripts.json's
parent directory name.

Needs OPENROUTER_API_KEY (images) and INWORLD_API_KEY (voice) in .env.
"""
import json
import os
import subprocess
import sys
import re
import textwrap
import base64
import urllib.request
from functools import lru_cache
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_voice_inworld import tts_with_timestamps, load_env  # noqa: E402

W, H, FPS = 1080, 1920, 30
ZOOM_MARGIN = 1.15  # oversize-crop safety margin so AI-generator watermarks fall outside frame
LOGO_PATH = ROOT / "media/projects/uka-bird/logo-bird.png"
LOGO_CHIP_W = 170  # top-left, must clear the bottom-anchored caption band (feedback_vox_petya_corner_logo)
LOGO_CHIP_PAD = 22

# Cyrillic-safe bold font for burned-in captions. Referenced directly from a system install
# (not copied into the repo — Arial's license does not permit redistribution). The macOS path
# is first because that is where this track was proven; the Linux fallbacks let the same
# module import (and the retellings pipeline that reuses it) run on a stock Debian/Ubuntu box
# instead of dying at import time on a missing Arial.
FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def resolve_font_path(candidates=FONT_CANDIDATES):
    for c in candidates:
        if os.path.exists(c):
            return c
    sys.exit("no Cyrillic-safe bold font found; tried:\n  " + "\n  ".join(candidates))


FONT_PATH = resolve_font_path()
FONT = ImageFont.truetype(FONT_PATH, 46)
FONT_HOOK = ImageFont.truetype(FONT_PATH, 58)


@lru_cache(maxsize=None)
def _font(px):
    return ImageFont.truetype(FONT_PATH, px)


# Caption geometry per aspect, picked by frame shape rather than by a flag — a caller that
# hands in a 1920x1080 canvas always wants the horizontal treatment and never has to say so.
#
# "vertical" is the proven narrated-shorts layout, reproduced value-for-value so the 9:16
# track renders byte-identically after this change.
#
# "horizontal" is NOT that layout scaled. A 16:9 frame is watched at arm's length or across
# a room, so the type is larger in absolute pixels but smaller as a share of frame height
# (58px on 1080 high = 5.4%, against 46px on 1920 = 2.4% — the vertical band would look
# gigantic at this shape). The measure is nearly twice as wide because the frame is, which
# keeps a caption to one or two lines instead of four. And the band sits 150px off the
# bottom rather than 460: vertical hides its captions above a phone UI that is not there on
# a desktop or a TV, and pushing them to a third of the way up a 16:9 frame would cover the
# picture the story is being told with.
CAPTION_LAYOUT = {
    "vertical": dict(font=46, font_hook=58, wrap=28, wrap_hook=24, line_h=58, line_h_hook=68,
                     lift=460, pad_x=40, pad_y=24, radius=16, stroke=2, stroke_hook=3),
    "horizontal": dict(font=52, font_hook=64, wrap=48, wrap_hook=40, line_h=66, line_h_hook=80,
                       lift=150, pad_x=48, pad_y=28, radius=18, stroke=3, stroke_hook=4),
}

STRESS_MARK = "́"  # combining acute — see gen_voice_inworld.py's stress-control note

IMG_MODEL = "google/gemini-3.1-flash-image"


def strip_stress(text):
    return text.replace(STRESS_MARK, "")


def caption_text(chunk):
    """Chunk -> the line as it should be READ, not as the synthesizer chopped it.

    Inworld returns a standalone dash glued to the word before it ("путь-"), which in a
    burned-in caption reads as a hyphenated word or a stutter. The audio is right and the
    timings are right, so this is fixed here, on the way to the picture, and never in the
    voice folder — those files must keep matching the mp3."""
    text = " ".join(w["w"] for w in chunk)
    return re.sub(r"(\w)-(\s|$)", r"\1 -\2", text)


def gen_image(tag, prompt, out_dir, aspect="9:16"):
    """OpenRouter unified /images API. Cached by tag — safe to re-run. `aspect` is the frame
    shape the caller is composing for ("9:16" phone, "16:9" YouTube)."""
    out = Path(out_dir) / f"{tag}.png"
    if out.exists():
        return out
    env = load_env()
    body = json.dumps({"model": IMG_MODEL, "prompt": prompt, "aspect_ratio": aspect}).encode()
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/images", data=body,
        headers={"Authorization": f"Bearer {env['OPENROUTER_API_KEY']}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            resp = json.load(r)
    except Exception as e:
        detail = e.read().decode() if hasattr(e, "read") else str(e)
        sys.exit(f"image gen FAIL {tag}: {detail[:800]}\n"
                  f"(common cause: realistic banknotes/currency trip Gemini's safety filter — "
                  f"rephrase to gold coins or a more symbolic/abstract prompt)")
    cost = resp.get("usage", {}).get("cost")
    raw = base64.b64decode(resp["data"][0]["b64_json"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(raw)
    print(f"  img ok {tag} cost=${cost}", file=sys.stderr)
    return out


JPEG_QUALITY = 92


def to_jpeg(png_path, quality=JPEG_QUALITY):
    """PNG in, JPEG out, original removed. 4:4:4 chroma (subsampling=0) because captions and
    fine archival grain are exactly what 4:2:0 smears."""
    png_path = Path(png_path)
    if png_path.suffix.lower() != ".png":
        return png_path
    jpg = png_path.with_suffix(".jpg")
    Image.open(png_path).convert("RGB").save(jpg, quality=quality, subsampling=0, optimize=True)
    png_path.unlink()
    return jpg


def gen_image_for(tag, prompt, out_dir, provider="openrouter", model=None, size=None,
                  style=None, negative=None):
    """Route one still to the configured provider. Cached by filename either way, so the
    cache is provider-agnostic: switching providers does NOT regenerate existing stills —
    delete the still first if you want a specific one re-rolled on a new provider.

    `size` is the frame the still is composed for, (1080, 1920) by default. It is a REQUEST,
    not a guarantee: a square-only model still returns a square, which cover-crops downstream
    and loses the sides — so a 16:9 build wants a model that honours width/height.

    `style` is appended to every prompt in the series and `negative` is passed to providers
    that take one (alibaba). That is what holds a MIXED-provider series together: a look one
    model gives by default (Flux's archival sepia) another gives only when asked, so the ask
    lives once per series instead of being rewritten into twenty prompts."""
    w, h = size or (W, H)
    out_dir = Path(out_dir)
    # Stills are STORED as JPEG and PNG is only the wire format. A 1080x1920 png off these
    # models runs 4 MB; the same frame at q92 is 0.6 MB and survives a Ken-Burns push and an
    # h264 encode with nothing visible lost. Twenty stills a story, committed forever — the
    # difference is the disk. Legacy .png stills still count as cached, so nothing rebuilds.
    # An EMPTY file is not a cached still: a download that died mid-write used to leave a
    # 0-byte file behind, and "the file exists" then quietly fed nothing into the render.
    out = out_dir / f"{tag}.jpg"
    for cached in (out, out_dir / f"{tag}.png"):
        if cached.exists() and cached.stat().st_size > 0:
            return cached
    raw = out_dir / f"{tag}.png"
    if style:
        prompt = f"{prompt}{style}"
    if provider == "openrouter":
        return to_jpeg(gen_image(tag, prompt, out_dir, aspect="16:9" if w > h else "9:16"))
    if provider == "cloudflare":
        from gen_image_cloudflare import gen_image_cloudflare, DEFAULT_MODEL as CF_DEFAULT
        raw.parent.mkdir(parents=True, exist_ok=True)
        print(f"  img {tag} ...", file=sys.stderr)
        # Size is passed as a REQUEST, not a demand: gen_image_cloudflare drops it for
        # square-only models (Flux) and retries without it if a model complains. Forcing it
        # here is what used to break the Flux route.
        gen_image_cloudflare(prompt, str(raw), model=model or CF_DEFAULT, width=w, height=h)
        return to_jpeg(raw)
    if provider == "modelscope":
        from gen_image_modelscope import gen_image_modelscope, DEFAULT_MODEL as MS_DEFAULT, DEFAULT_SIZE
        raw.parent.mkdir(parents=True, exist_ok=True)
        print(f"  img {tag} ...", file=sys.stderr)
        gen_image_modelscope(prompt, str(raw), model=model or MS_DEFAULT, size=DEFAULT_SIZE)
        return to_jpeg(raw)
    if provider == "alibaba":
        # Model Studio honours exact width/height, so no cover-crop and no square fallback —
        # what is asked for is what comes back. ~60s per still; see gen_image_alibaba.py for
        # the plan-vs-paygo key split.
        from gen_image_alibaba import gen_image_alibaba, PLAN_DEFAULT_MODEL
        raw.parent.mkdir(parents=True, exist_ok=True)
        print(f"  img {tag} ...", file=sys.stderr)
        gen_image_alibaba(prompt, str(raw), model=model or PLAN_DEFAULT_MODEL, width=w, height=h,
                          negative=negative)
        return to_jpeg(raw)
    sys.exit(f"unknown image_provider {provider!r} "
             f"(alibaba | openrouter | cloudflare | modelscope)")


def make_logo_chip(out_path, width=LOGO_CHIP_W, pad=LOGO_CHIP_PAD):
    """Bird logo on a translucent dark rounded backing, so it reads against light AI-still
    backgrounds too (a bare white mark can vanish into pale skies/curtains/fog)."""
    logo = Image.open(LOGO_PATH).convert("RGBA")
    inner_w = width - 2 * pad
    inner_h = max(1, round(logo.height * inner_w / logo.width))
    logo_r = logo.resize((inner_w, inner_h), Image.LANCZOS)
    h = inner_h + 2 * pad
    im = Image.new("RGBA", (width, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, width, h], radius=22, fill=(12, 10, 20, 140))
    im.alpha_composite(logo_r, (pad, pad))
    im.save(out_path)
    return width, h


def wrap_words(text, width=28):
    return textwrap.wrap(text, width=width, break_long_words=False) or [text]


def make_caption_png(text, out_path, hook=False, size=None):
    """One caption as a full-frame RGBA overlay. `size` defaults to the 9:16 frame; pass
    (1920, 1080) for the horizontal retellings track and the geometry follows the shape."""
    w, h = size or (W, H)
    lay = CAPTION_LAYOUT["horizontal" if w > h else "vertical"]
    font = _font(lay["font_hook"] if hook else lay["font"])
    lines = wrap_words(strip_stress(text.strip()), lay["wrap_hook"] if hook else lay["wrap"])
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    line_h = lay["line_h_hook"] if hook else lay["line_h"]
    total_h = line_h * len(lines)
    y0 = h - lay["lift"] - total_h // 2
    max_w = max(d.textlength(l, font=font) for l in lines)
    pad_x, pad_y = lay["pad_x"], lay["pad_y"]
    box = [(w - max_w) / 2 - pad_x, y0 - pad_y, (w + max_w) / 2 + pad_x, y0 + total_h + pad_y]
    fill = (20, 10, 40, 170) if hook else (0, 0, 0, 150)
    d.rounded_rectangle(box, radius=lay["radius"], fill=fill)
    stroke = lay["stroke_hook"] if hook else lay["stroke"]
    for i, line in enumerate(lines):
        lw = d.textlength(line, font=font)
        x = (w - lw) / 2
        y = y0 + i * line_h
        color = (255, 220, 120, 255) if hook else (255, 255, 255, 255)
        d.text((x, y), line, font=font, fill=color, stroke_width=stroke, stroke_fill=(0, 0, 0, 220))
    im.save(out_path)


def chunk_words(words, max_words=6):
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        if any(w["w"].endswith(p) for p in (".", "?", "!", "»")) or len(cur) >= max_words:
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


def hook_word_count(words, hook_text):
    norm = lambda s: re.sub(r"\s+", "", strip_stress(s))
    target = norm(hook_text)
    acc = ""
    for i, w in enumerate(words):
        acc += norm(w["w"])
        if len(acc) >= len(target):
            return i + 1
    return len(words)


# Ken-Burns motion presets, cycled per image — pure ffmpeg (zero added generation cost),
# just varies the crop/zoom path so a 4-5 image episode doesn't feel like the same push-in
# repeated. Each returns (zoom_expr, x_expr, y_expr) given the clip's frame count.
def _zoompan_expr(motion, nframes):
    center_x, center_y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    if motion == "zoom_in_center":
        return "min(zoom+0.0006,1.14)", center_x, center_y
    if motion == "zoom_out_center":
        return "if(eq(on,0),1.14,max(zoom-0.0006,1.0))", center_x, center_y
    if motion == "pan_right":
        return "1.12", f"(iw-iw/zoom)*(on/{nframes})", center_y
    if motion == "pan_down":
        return "1.1", center_x, f"(ih-ih/zoom)*(on/{nframes})"
    raise ValueError(motion)


KEN_BURNS_MOTIONS = ["zoom_in_center", "pan_right", "zoom_out_center", "pan_down"]


XFADE = 0.6


def build_bg(images, out_path, work_dir, tag="bg"):
    """images: [(path, duration), ...]. Ken-Burns each (motion cycled per index); crossfade
    between them if >1.

    Offset arithmetic, the expensive way to learn it: each xfade's offset is measured in the
    ACCUMULATED stream, so it advances by the previous image's full duration — not by
    duration minus the crossfade. Subtracting the crossfade every time (as this did until
    2026-08-21) leaves the background XFADE*(n-1) short — 2.4s on the 5-image episode
    DESIGN.md recommends, 12s on a 21-image retelling — with every image after the second
    entering early by a growing margin.

    Measured symptom, on a real 5-still episode: the mux does NOT clip the narration, because
    the logo input (`-loop 1 -t total_dur`) keeps the overlay's framesync alive past the end
    of the background, and framesync's default eof_action=repeat holds the background's last
    frame. So the video keeps its full length and the closing still simply FREEZES for the
    last 2.4s, while every cut before it has drifted ahead of what the narrator is saying.
    Every fragment now carries the extra XFADE tail, including the last, so the total comes
    out exactly sum(durations)."""
    n = len(images)
    frags = []
    for i, (img, dur) in enumerate(images):
        extra = XFADE
        nframes = max(1, int(round((dur + extra) * FPS)))
        motion = KEN_BURNS_MOTIONS[i % len(KEN_BURNS_MOTIONS)]
        z, x, y = _zoompan_expr(motion, nframes)
        vf = (f"scale={int(W*ZOOM_MARGIN)}:{int(H*ZOOM_MARGIN)}:force_original_aspect_ratio=increase,"
              f"crop={int(W*ZOOM_MARGIN)}:{int(H*ZOOM_MARGIN)},"
              f"zoompan=z='{z}':x='{x}':y='{y}':d={nframes}:s={W}x{H}:fps={FPS},setsar=1")
        frag = work_dir / f"{tag}_{i}.mp4"
        subprocess.run(["ffmpeg", "-y", "-loop", "1", "-i", str(img), "-t", f"{dur + extra:.3f}",
                        "-vf", vf, "-an", "-c:v", "libx264", "-preset", "veryfast",
                        "-pix_fmt", "yuv420p", str(frag)], capture_output=True)
        frags.append(frag)
    if n == 1:
        frags[0].rename(out_path)
        return
    cur = frags[0]
    offset = images[0][1] - XFADE
    for i in range(1, n):
        out = work_dir / f"{tag}_xf{i}.mp4"
        cmd = ["ffmpeg", "-y", "-i", str(cur), "-i", str(frags[i]),
               "-filter_complex", f"xfade=transition=fade:duration={XFADE}:offset={offset:.3f}",
               "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(out)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"xfade FAIL: {r.stderr[-1500:]}")
        cur = out
        offset += images[i][1]
    cur.rename(out_path)


def build_narrated_short(words, total_dur, hook_words, images, audio_path, out_final, work_dir):
    """images: [(image_path, duration_seconds), ...]. audio_path: final mixed voice+music wav.
    Writes out_final (1080x1920 mp4, captions + logo baked in, audio muxed)."""
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    caps_dir = work_dir / "caps"
    caps_dir.mkdir(exist_ok=True)

    bg = work_dir / "bg.mp4"
    build_bg(images, bg, work_dir)

    chunks = chunk_words(words, max_words=6)
    inputs = ["-i", str(bg)]
    next_idx = 1  # ffmpeg 0-based input-stream index; bg took slot 0. Tracked explicitly
    # rather than derived from len(inputs) — one input (the logo) needs extra argv flags
    # ("-loop 1") ahead of "-i", which would throw off a slot-count-based index.
    filt_parts = []
    last = "0:v"
    word_i = 0
    for ci, chunk in enumerate(chunks):
        text = caption_text(chunk)
        start, end = chunk[0]["start"], chunk[-1]["end"]
        is_hook = word_i < hook_words
        word_i += len(chunk)
        png = caps_dir / f"{ci:04d}.png"
        make_caption_png(text, png, hook=is_hook)
        inputs += ["-i", str(png)]
        in_idx = next_idx
        next_idx += 1
        out_label = f"v{in_idx}"
        filt_parts.append(f"[{last}][{in_idx}:v]overlay=0:0:enable='between(t,{start:.3f},{end:.3f})'[{out_label}]")
        last = out_label

    # persistent corner logo — always on, clear of the bottom-anchored captions. Baked onto a
    # translucent dark backing chip so it stays legible over light backgrounds too (a plain
    # white logo mark disappears against pale AI-still backdrops), plus a short fade-in so it
    # doesn't feel like a static sticker. "-loop 1" is required here (unlike the caption pngs)
    # because `fade` needs a real per-frame timeline to animate over — a plain single-frame
    # input only ever gives it one (near-transparent, t=0) frame, which overlay then holds
    # for the rest of the video, making the logo invisible throughout. The explicit "-t" is
    # required too: with no other output-level bound (no -shortest), an unbounded looped input
    # makes ffmpeg run until every input reaches EOF — since this one never does, it ran for
    # hours instead of ~60s before this fix.
    logo_chip = work_dir / "logo_chip.png"
    make_logo_chip(logo_chip)
    inputs += ["-loop", "1", "-t", f"{total_dur:.3f}", "-i", str(logo_chip)]
    logo_idx = next_idx
    next_idx += 1
    filt_parts.append(f"[{logo_idx}:v]fade=t=in:st=0:d=0.8:alpha=1[logofade]")
    filt_parts.append(f"[{last}][logofade]overlay=48:56[vlogo]")
    last = "vlogo"

    capped = work_dir / "capped.mp4"
    cmd = ["ffmpeg", "-y"] + inputs + ["-filter_complex", ";".join(filt_parts), "-map", f"[{last}]",
           "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(capped)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"caption/logo overlay FAIL: {r.stderr[-2500:]}")

    cmd = ["ffmpeg", "-y", "-i", str(capped), "-i", str(audio_path),
           "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
           "-shortest", str(out_final)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"mux FAIL: {r.stderr[-2000:]}")
    print(f"done -> {out_final}", file=sys.stderr)


def mix_audio(voice_mp3, total_dur, out_mixed, music_track=None, work_dir=None, music_db=-24.0):
    """Quiet music bed under the voice (defaults to media/library/music ambient-pad).

    `music_db` is the gain applied to the bed BEFORE mixing. -24 is the 60-second-episode
    value: at that level the bed lands ~28 dB under the narration, which is inaudible on a
    phone speaker. That is fine for an episode that never stops talking, and wrong for a
    five-minute story that pauses between beats — there the bed is the only thing standing
    between "a breath" and "the audio died". See retellings/DESIGN.md."""
    work_dir = Path(work_dir)
    music_track = music_track or (ROOT / "media/library/music/clips/ambient-pad.mp3")
    voice_wav = work_dir / "voice.wav"
    subprocess.run(["ffmpeg", "-y", "-i", str(voice_mp3), "-ar", "44100", "-ac", "2", str(voice_wav)],
                   capture_output=True)
    # The library clips fade in and out at their own edges. Looping one raw therefore drops
    # the bed into silence once per clip length — ambient-pad falls from -42 dB to -90 dB over
    # its last four seconds, so a 5-minute retelling got a five-second hole every 63 seconds,
    # and two of the pilot's between-beat pauses landed squarely in one. Trim the faded edges
    # first and loop only the sounding body: the seam is a timbre step at a matched level
    # instead of a hole, and under narration at -18 dB it is inaudible.
    loop_unit = work_dir / "music_unit.wav"
    subprocess.run(["ffmpeg", "-y", "-i", str(music_track), "-af",
                    "silenceremove=start_periods=1:start_threshold=-46dB:detection=peak,"
                    "areverse,"
                    "silenceremove=start_periods=1:start_threshold=-46dB:detection=peak,"
                    "areverse",
                    "-ar", "44100", "-ac", "2", str(loop_unit)], capture_output=True)

    music_wav = work_dir / "music.wav"
    fade_out_start = max(0.1, total_dur - 4)
    subprocess.run(["ffmpeg", "-y", "-stream_loop", "-1", "-i", str(loop_unit), "-t", f"{total_dur:.3f}",
                    # dynaudnorm BEFORE the gain: a sparse pad has near-silent moments of its
                    # own, and looping it means one of those can land exactly on a between-beat
                    # pause — which is how the pilot ended up with -56 dB of "music" at the one
                    # silence that mattered. Evening out the bed's own dynamics lifts its
                    # deepest hole from -52 dB to -33 while moving the average only 3 dB, so
                    # the track keeps its character and every pause stays held.
                    "-af", f"dynaudnorm=f=200:g=15:p=0.55,volume={music_db}dB,"
                           f"afade=t=in:st=0:d=2,afade=t=out:st={fade_out_start:.3f}:d=4",
                    "-ar", "44100", "-ac", "2", str(music_wav)], capture_output=True)
    subprocess.run(["ffmpeg", "-y", "-i", str(voice_wav), "-i", str(music_wav),
                    "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=0,volume=1.8",
                    "-ar", "44100", "-ac", "2", str(out_mixed)], capture_output=True)


def build_from_spec(entry, spec_dir):
    sid, slug = entry["id"], entry["slug"]
    series = spec_dir.name
    print(f"=== short {sid}: {slug} ===", file=sys.stderr)

    work_dir = spec_dir / "voice" / f"{sid:02d}-{slug}_build"
    work_dir.mkdir(parents=True, exist_ok=True)
    voice_mp3 = spec_dir / "voice" / f"short-{sid:02d}-{slug}.mp3"
    words_json = spec_dir / "voice" / f"short-{sid:02d}-{slug}.words.json"
    voice_mp3.parent.mkdir(parents=True, exist_ok=True)

    full_text = f"{entry['hook']} {entry['vo']} {entry['ending']}"
    if words_json.exists():
        data = json.loads(words_json.read_text(encoding="utf-8"))
        words, total_dur = data["words"], data["duration"]
    else:
        vcfg = entry.get("voice", {})
        audio, words, total_dur = tts_with_timestamps(
            full_text, vcfg.get("voice_id", "Nikolai"), vcfg.get("model", "inworld-tts-1.5-max"),
            vcfg.get("temperature", 1.1), vcfg.get("speaking_rate", 1.0))
        voice_mp3.write_bytes(audio)
        words_json.write_text(json.dumps({"duration": total_dur, "words": words}, ensure_ascii=False, indent=2),
                               encoding="utf-8")
    print(f"  duration={total_dur:.1f}s words={len(words)}", file=sys.stderr)

    img_dir = ROOT / "media/projects" / series / "images"
    provider = entry.get("image_provider", "openrouter")
    model = entry.get("image_model")
    style, negative = entry.get("image_style"), entry.get("image_negative")
    image_paths = []
    for i, (prompt, frac) in enumerate(entry["images"]):
        p = gen_image_for(f"s{sid}_{i}", prompt, img_dir, provider=provider, model=model,
                          style=style, negative=negative)
        image_paths.append((p, total_dur * frac))

    mixed_wav = work_dir / "audio_mixed.wav"
    mix_audio(voice_mp3, total_dur, mixed_wav, work_dir=work_dir)

    out_dir = spec_dir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_final = out_dir / f"short-{sid:02d}-{slug}.mp4"
    hw = hook_word_count(words, entry["hook"])
    build_narrated_short(words, total_dur, hw, image_paths, mixed_wav, out_final, work_dir / "assemble")
    return out_final


def main():
    args = sys.argv[1:]
    spec_file = None
    for i, a in enumerate(args):
        if a == "--spec-file":
            spec_file = args[i + 1]
    if not spec_file:
        sys.exit("usage: build_narrated_short.py --spec-file <scripts.json> [--id N | --all]")
    spec_path = Path(spec_file)
    entries = json.loads(spec_path.read_text(encoding="utf-8"))

    ids = None
    if "--id" in args:
        ids = {int(args[args.index("--id") + 1])}
    todo = entries if ids is None else [e for e in entries if e["id"] in ids]
    for e in todo:
        build_from_spec(e, spec_path.parent)
    print("ALL DONE", file=sys.stderr)


if __name__ == "__main__":
    main()
