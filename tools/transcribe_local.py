#!/usr/bin/env python3
"""
transcribe_local.py — word-level timestamps WITHOUT an API, via faster-whisper.

Same output contract as tools/transcribe.py (the ElevenLabs Scribe route), so anything
reading a transcript.json — vo_from_recording.py, the repurpose-recording track — takes
either file interchangeably. Use this when the ElevenLabs quota is spent, when the audio
shouldn't leave the machine, or for the short one-take VO reads where Scribe's edge in
accuracy doesn't pay for itself.

Scribe is still the better recogniser on long, noisy, multi-speaker source; this is the
free local fallback, not a replacement.

Usage:
  python tools/transcribe_local.py --in voice/take.m4a --out voice/take.words.json
  python tools/transcribe_local.py --in ... --out ... --model large-v3 --allow-download

Needs `pip install faster-whisper` (NOT stdlib — this is an optional extra, like
cutout.py's pillow/rembg). Models are cached under ~/.cache/huggingface/hub; by default
only already-downloaded ones are used, so a run never silently pulls gigabytes.
"""
import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MODEL = "medium"


def run(cmd):
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if r.returncode != 0:
        sys.exit(f"command failed: {' '.join(cmd)}\n{r.stdout}")
    return r.stdout


def probe_duration(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", path])
    return float(out.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True, help="source video/audio file")
    ap.add_argument("--out", required=True, help="output transcript.json path")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"faster-whisper model (default {DEFAULT_MODEL})")
    ap.add_argument("--language", default="ru")
    ap.add_argument("--compute-type", default="int8", help="int8 (default, CPU-friendly) | float32")
    ap.add_argument("--beam-size", type=int, default=5)
    ap.add_argument("--no-vad", action="store_true", help="skip voice-activity filtering")
    ap.add_argument("--allow-download", action="store_true", help="permit fetching a model that isn't cached yet")
    args = ap.parse_args()

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("faster-whisper is not installed.\n  pip install faster-whisper\n"
                 "  (or use tools/transcribe.py, the ElevenLabs route)")

    src = os.path.abspath(args.inp)
    if not os.path.exists(src):
        sys.exit(f"no such file: {args.inp}")
    total = probe_duration(src)

    print(f"loading model {args.model} ({args.compute_type})"
          f"{'' if args.allow_download else ', cache only'} ...")
    try:
        model = WhisperModel(args.model, device="cpu", compute_type=args.compute_type,
                             local_files_only=not args.allow_download)
    except Exception as e:
        sys.exit(f"could not load model {args.model!r}: {e}\n"
                 "  pass --allow-download to fetch it (models run 0.5-3 GB), or pick a cached one")

    print(f"transcribing {os.path.relpath(src, ROOT)} ({total:.1f}s) ...")
    segments, info = model.transcribe(
        src, language=args.language, beam_size=args.beam_size, word_timestamps=True,
        vad_filter=not args.no_vad,
        # long silences are where whisper loops a phrase back on itself; not carrying the
        # previous text into the next window is the cheapest guard against it
        condition_on_previous_text=False)

    words, texts = [], []
    for seg in segments:
        texts.append(seg.text)
        for w in (seg.words or []):
            t = w.word.strip()
            if t:
                words.append({"w": t, "start": round(w.start, 3), "end": round(w.end, 3)})
        print(f"  {seg.start:7.2f}s {seg.text.strip()[:88]}")

    out = {
        "source": os.path.relpath(src, ROOT),
        "duration_sec": round(total, 2),
        "language_code": args.language,
        "engine": f"faster-whisper:{args.model}",
        "words": words,
        "text": " ".join(t.strip() for t in texts).strip(),
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n{len(words)} words -> {os.path.relpath(os.path.abspath(args.out), ROOT)}")


if __name__ == "__main__":
    main()
