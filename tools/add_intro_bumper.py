#!/usr/bin/env python3
"""
add_intro_bumper.py — prepend a short spoken "Итак, сегодня про..." bumper to already-built
narrated-shorts episodes, so a re-upload after a break isn't a byte-identical duplicate of the
first publish. Reuses build_narrated_short.py's caption/logo/audio-mix helpers so the bumper
looks and sounds like the rest of the pipeline (same caption style, same corner logo, same
voice/model defaults).

Does NOT touch the original output/short-NN-slug.mp4 — writes output/short-NN-slug-intro.mp4
alongside it, so the un-bumpered master stays intact.

Usage:
  python tools/add_intro_bumper.py --spec-file narrated-shorts/trudnosti-puti/scripts.json --id 1
  python tools/add_intro_bumper.py --spec-file narrated-shorts/trudnosti-puti/scripts.json   # all
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_narrated_short import (  # noqa: E402
    W, H, make_caption_png, make_logo_chip, mix_audio,
)
from gen_voice_inworld import tts_with_timestamps  # noqa: E402

BUMPER_CLIP = ROOT / "media/projects/trudnosti-puti/bumper-buddha.mp4"
TAIL_PAD = 0.5  # seconds of bumper held after speech ends, so the cut doesn't feel abrupt


def build_intro_clip(intro_text, voice_cfg, out_final, work_dir):
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    audio, words, total_dur = tts_with_timestamps(
        intro_text, voice_cfg.get("voice_id", "Nikolai"), voice_cfg.get("model", "inworld-tts-1.5-max"),
        voice_cfg.get("temperature", 1.1), voice_cfg.get("speaking_rate", 1.0))
    voice_mp3 = work_dir / "intro_voice.mp3"
    voice_mp3.write_bytes(audio)

    clip_dur = total_dur + TAIL_PAD
    mixed_wav = work_dir / "intro_audio_mixed.wav"
    mix_audio(voice_mp3, clip_dur, mixed_wav, work_dir=work_dir)

    bg = work_dir / "intro_bg.mp4"
    subprocess.run(["ffmpeg", "-y", "-i", str(BUMPER_CLIP), "-t", f"{clip_dur:.3f}",
                    "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1",
                    "-an", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(bg)],
                   capture_output=True)

    caps_dir = work_dir / "caps"
    caps_dir.mkdir(exist_ok=True)
    png = caps_dir / "0000.png"
    make_caption_png(intro_text, png, hook=True)

    logo_chip = work_dir / "logo_chip.png"
    make_logo_chip(logo_chip)

    capped = work_dir / "intro_capped.mp4"
    cmd = ["ffmpeg", "-y", "-i", str(bg), "-i", str(png), "-loop", "1", "-t", f"{clip_dur:.3f}", "-i", str(logo_chip),
           "-filter_complex",
           f"[0:v][1:v]overlay=0:0:enable='between(t,0,{total_dur:.3f})'[v1];"
           f"[2:v]fade=t=in:st=0:d=0.8:alpha=1[logofade];[v1][logofade]overlay=48:56[vout]",
           "-map", "[vout]", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(capped)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"intro caption/logo overlay FAIL: {r.stderr[-2000:]}")

    cmd = ["ffmpeg", "-y", "-i", str(capped), "-i", str(mixed_wav),
           "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
           "-shortest", str(out_final)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"intro mux FAIL: {r.stderr[-2000:]}")
    return clip_dur


def prepend_intro(entry, spec_dir):
    sid, slug = entry["id"], entry["slug"]
    main_mp4 = spec_dir / "output" / f"short-{sid:02d}-{slug}.mp4"
    if not main_mp4.exists():
        sys.exit(f"missing {main_mp4} — build the base episode first")

    work_dir = spec_dir / "voice" / f"{sid:02d}-{slug}_intro_build"
    intro_mp4 = work_dir / "intro.mp4"
    print(f"=== intro {sid}: {slug} ===", file=sys.stderr)
    dur = build_intro_clip(entry["intro"], entry.get("voice", {}), intro_mp4, work_dir)
    print(f"  intro duration={dur:.1f}s", file=sys.stderr)

    out_final = spec_dir / "output" / f"short-{sid:02d}-{slug}-intro.mp4"
    cmd = ["ffmpeg", "-y", "-i", str(intro_mp4), "-i", str(main_mp4),
           "-filter_complex", "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[outv][outa]",
           "-map", "[outv]", "-map", "[outa]", "-c:v", "libx264", "-preset", "veryfast",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(out_final)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"concat FAIL: {r.stderr[-2000:]}")
    print(f"done -> {out_final}", file=sys.stderr)
    return out_final


def main():
    args = sys.argv[1:]
    spec_file = None
    for i, a in enumerate(args):
        if a == "--spec-file":
            spec_file = args[i + 1]
    if not spec_file:
        sys.exit("usage: add_intro_bumper.py --spec-file <scripts.json> [--id N]")
    spec_path = Path(spec_file)
    entries = json.loads(spec_path.read_text(encoding="utf-8"))

    ids = None
    if "--id" in args:
        ids = {int(args[args.index("--id") + 1])}
    todo = entries if ids is None else [e for e in entries if e["id"] in ids]
    for e in todo:
        prepend_intro(e, spec_path.parent)
    print("ALL DONE", file=sys.stderr)


if __name__ == "__main__":
    main()
