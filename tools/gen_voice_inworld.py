#!/usr/bin/env python3
"""
gen_voice_inworld.py — Inworld TTS with word-exact timestamps (narrated-shorts track).

Sibling of gen_voice.py (ElevenLabs, beats.json-driven TSX shorts): this one is for the
single-narrator "Ken Burns over AI images" format in narrated-shorts/. Inworld returns
word-level start/end times natively (no forced-alignment step needed), and its Voice
Library has native-Russian voices — default here is Nikolai (deep, resonant, dramatic;
confirmed non-generic pick for RU spiritual/philosophical narration, 2026-08-09).

Usage:
  python tools/gen_voice_inworld.py --text "..." --out shorts/x/voice/voice.mp3
  python tools/gen_voice_inworld.py --text-file script.txt --out out.mp3 --voice Nikolai
  python tools/gen_voice_inworld.py --text "..." --out out.mp3 --dry-run

Writes <out>.mp3 (or whatever extension --out has) + a sidecar <out-stem>.words.json:
  {"duration": 51.07, "words": [{"w": "Гуру", "start": 0.0, "end": 0.41}, ...]}

Needs INWORLD_API_KEY in .env — a Basic-auth key, already base64(client_id:client_secret),
used as-is in the Authorization header (get it from the Inworld dashboard).

Model presets confirmed against the live API (2026-08-09):
  inworld-tts-1        — base model
  inworld-tts-1.5-max  — richer, more expressive (default; user's own playground settings)

**Stress control**: Russian words that come out mis-stressed can be fixed two ways —
(1) swap to a same-meaning word/conjugation the model renders correctly (e.g. "узнаете" ->
"узнайте"), or (2) insert a combining acute accent U+0301 right after the stressed vowel
(e.g. "душ" + U+0301 + "и" for genitive "души́", correctly end-stressed). Inworld accepts
U+0301 inline and echoes it back in the returned word text — callers must strip it before
using the word text for on-screen captions (see tools/build_narrated_short.py's
strip_stress()). Always listen to a script's TTS pass once before batch-generating a series
off it.

**Style note (this user, standing preference):** never feed an em-dash (—) or en-dash (–)
into text — this tool auto-converts both to a plain hyphen before sending (see clean_dashes).
"""
import json
import os
import sys
import base64
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PRESETS = {
    "base": "inworld-tts-1",
    "max": "inworld-tts-1.5-max",
}
DEFAULT_MODEL = "inworld-tts-1.5-max"
DEFAULT_VOICE = "Nikolai"
DEFAULT_TEMPERATURE = 1.1
DEFAULT_SPEAKING_RATE = 1.0


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


def clean_dashes(text):
    return text.replace("—", "-").replace("–", "-")


def tts_with_timestamps(text, voice_id=DEFAULT_VOICE, model=DEFAULT_MODEL,
                         temperature=DEFAULT_TEMPERATURE, speaking_rate=DEFAULT_SPEAKING_RATE,
                         language="ru"):
    """Returns (audio_bytes, words, duration). words: [{"w","start","end"}, ...],
    punctuation-only tokens glued onto the preceding word, combining stress marks intact."""
    env = load_env()
    api_key = env.get("INWORLD_API_KEY", "").strip()
    if not api_key:
        sys.exit("INWORLD_API_KEY not set in .env")

    text = clean_dashes(text)
    body = json.dumps({
        "text": text,
        "voiceId": voice_id,
        "modelId": model,
        "language": language,
        "audioConfig": {"audioEncoding": "MP3", "sampleRateHertz": 44100, "speakingRate": speaking_rate},
        "timestampType": "WORD",
        "temperature": temperature,
    }).encode()
    req = urllib.request.Request("https://api.inworld.ai/tts/v1/voice", data=body, headers={
        "Authorization": f"Basic {api_key}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.load(r)
    except Exception as e:
        detail = e.read().decode() if hasattr(e, "read") else str(e)
        sys.exit(f"Inworld API error: {detail[:1000]}")

    audio = base64.b64decode(data["audioContent"])
    align = data["timestampInfo"]["wordAlignment"]
    raw_words, starts, ends = align["words"], align["wordStartTimeSeconds"], align["wordEndTimeSeconds"]

    words = []
    for w, s, e in zip(raw_words, starts, ends):
        wt = w.strip()
        if not wt:
            continue
        if not any(ch.isalnum() for ch in wt):
            # pure punctuation/dash token — glue onto the previous word
            if words:
                words[-1]["w"] += wt
                words[-1]["end"] = e
            continue
        words.append({"w": wt, "start": s, "end": e})
    duration = ends[-1] if ends else 0.0
    return audio, words, duration


def main():
    args = sys.argv[1:]
    text = get_arg(args, "--text")
    text_file = get_arg(args, "--text-file")
    if text_file:
        text = open(text_file, encoding="utf-8").read()
    out = get_arg(args, "--out")
    if not text or not out:
        sys.exit("need --text/--text-file and --out (see file header)")

    voice = get_arg(args, "--voice", DEFAULT_VOICE)
    model = PRESETS.get(get_arg(args, "--model", DEFAULT_MODEL), get_arg(args, "--model", DEFAULT_MODEL))
    temperature = float(get_arg(args, "--temperature", DEFAULT_TEMPERATURE))
    speaking_rate = float(get_arg(args, "--speaking-rate", DEFAULT_SPEAKING_RATE))

    if "--dry-run" in args:
        print(f"voice={voice} model={model} temperature={temperature} speaking_rate={speaking_rate}")
        print(f"text ({len(text)} chars): {text[:200]}...")
        print(f"out -> {out}")
        return

    audio, words, duration = tts_with_timestamps(text, voice, model, temperature, speaking_rate)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "wb") as f:
        f.write(audio)
    words_path = os.path.splitext(out)[0] + ".words.json"
    with open(words_path, "w", encoding="utf-8") as f:
        json.dump({"duration": duration, "words": words}, f, ensure_ascii=False, indent=2)
    print(f"voice -> {out}  ({duration:.1f}s, {len(words)} words)")
    print(f"words -> {words_path}")


if __name__ == "__main__":
    main()
