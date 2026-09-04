#!/usr/bin/env python3
"""
One-off: rebuild narrated-shorts/trudnosti-puti episode 1 using the Cloudflare-generated
stills in media/projects/trudnosti-puti/images-cf/, reusing the already-cached voice/words
(no TTS regeneration). Writes output/short-01-malysh-i-vershina-cf.mp4, does not touch the
OpenRouter-based original.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_narrated_short import build_narrated_short, mix_audio, hook_word_count  # noqa: E402

spec_dir = ROOT / "narrated-shorts/trudnosti-puti"
entry = json.loads((spec_dir / "scripts.json").read_text(encoding="utf-8"))[0]
assert entry["id"] == 1

words_json = spec_dir / "voice" / "short-01-malysh-i-vershina.words.json"
data = json.loads(words_json.read_text(encoding="utf-8"))
words, total_dur = data["words"], data["duration"]

img_dir = ROOT / "media/projects/trudnosti-puti/images-cf"
images = [(img_dir / f"s1_{i}.png", total_dur * frac) for i, (_, frac) in enumerate(entry["images"])]

work_dir = spec_dir / "voice" / "01-malysh-i-vershina_cf_build"
work_dir.mkdir(parents=True, exist_ok=True)
mixed_wav = work_dir / "audio_mixed.wav"
voice_mp3 = spec_dir / "voice" / "short-01-malysh-i-vershina.mp3"
mix_audio(voice_mp3, total_dur, mixed_wav, work_dir=work_dir)

hw = hook_word_count(words, entry["hook"])
out_final = spec_dir / "output" / "short-01-malysh-i-vershina-cf.mp4"
build_narrated_short(words, total_dur, hw, images, mixed_wav, out_final, work_dir / "assemble")
print(f"done -> {out_final}")
