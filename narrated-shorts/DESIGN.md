# narrated-shorts/ — single-narrator + AI-image shorts (4th production track)

A vertical-shorts format for a recurring **narrator + AI-generated stills** structure: one
voice reads a hook/body/ending-hook script over 1-2 AI-generated 9:16 images (Ken Burns +
crossfade), with word-synced burned-in captions. No footage montage (that's what the earlier
`samaya-glupaya-sdelka-video` two-speaker podcast videos did with the micro-clips library +
`assemble_multi.py`-style scripts) and no TSX composition (that's `make-short`/`make-ai-short`/
`make-vox`) — this track is pure ffmpeg, built for producing many short (45-65s) episodes of
the same series quickly. Proven on `guru-i-uchenik` (17 episodes, 2026-08-09).

## Why its own track, not a make-short variant

- No custom per-shot animation code — every episode is the same filter pipeline (Ken Burns +
  crossfade + captions + logo), so a Remotion composition per episode would be pure overhead.
- The images are photoreal/painterly AI stills (OpenRouter's `google/gemini-3.1-flash-image`),
  not code-drawn — same register as `make-ai-short`'s clips, but *stills* not *video*, and
  *narrator-driven* not dialogue-driven.
- Voice is **Inworld** (`tools/gen_voice_inworld.py`), not ElevenLabs — Inworld has native
  Russian voices (Nikolai: deep, resonant, dramatic — picked specifically as a less-generic
  alternative to ElevenLabs' Adam) and returns word-level timestamps natively, no forced
  alignment step needed.

## Format

1080×1920 @30fps, 45-65s (YouTube Shorts-eligible with room to spare). Beat shape:
**Hook** (bold gold-tinted caption style, first ~2-3 sentences) → **Voiceover** (body, regular
caption style) → **Ending hook** (a next-episode teaser is fine *only* when the series is
genuinely episodic and says so up front — see `feedback_finish_the_thought` memory for the
default no-dangling-CTA rule this is an intentional, discussed exception to).

## Per-series artifact contract

```
narrated-shorts/<series-slug>/
  scripts.json      — array of episode specs (source of truth, committed):
                       {id, slug, hook, vo, ending, images: [[prompt, duration_fraction], ...], voice?}
  voice/            — cached TTS per episode: short-NN-slug.mp3 + .words.json  [gitignored]
  output/           — final rendered short-NN-slug.mp4                        [gitignored]

media/projects/<series-slug>/images/
  sN_i.png          — AI-generated stills, one per images[] entry (committed — paid, non-reproducible)
```

## Pipeline (one command per episode or per batch)

```bash
python tools/build_narrated_short.py --spec-file narrated-shorts/<series-slug>/scripts.json --id 5
python tools/build_narrated_short.py --spec-file narrated-shorts/<series-slug>/scripts.json   # all entries
```

Re-running is cheap and safe: TTS/images/final are all cached by filename, so a re-run after
editing one `scripts.json` entry only regenerates what changed (delete the specific cached
file to force a redo of just that piece).

## Hard rules, learned the expensive way (2026-08-09 pilot round)

- **Dashes:** never feed `—`/`–` into TTS or captions — `gen_voice_inworld.py` auto-converts
  to a plain hyphen (`-`). This user's standing style preference (see
  `feedback_short_dashes_not_em` memory): a long dash reads as visibly AI-written.
- **Stress:** Inworld's Russian TTS occasionally mis-stresses a word. Two fixes, in order of
  preference: (1) swap to a same-meaning word/conjugation it renders correctly (e.g.
  "узнаете" → "узнайте"), (2) insert a combining acute accent `́` right after the
  stressed vowel in the *source* text (e.g. genitive "души" → `душ́и`) — Inworld honors
  it, and `build_narrated_short.py`'s `strip_stress()` removes the mark before it ever reaches
  an on-screen caption. Always do one listen-through of a new script's TTS before batch-
  generating a whole series off it.
- **Provider reality check:** this file's default is OpenRouter, but the project's own
  status notes have OpenRouter nearly out of balance and the direct Gemini key out of quota;
  Cloudflare Workers AI is the route that actually runs. Set `"image_provider": "cloudflare"`
  on the entry (plus `"image_model"`) rather than assuming the default works.
- **Image prompts:** avoid photorealistic banknotes/currency in `gen_image` prompts — Gemini's
  safety filter reliably blocks them (`finish_reason: STOP`, no image data). Use gold
  coins/bars or a more symbolic treatment instead.
- **Watermark safety:** the shared `ZOOM_MARGIN = 1.15` oversize-crop in
  `build_narrated_short.py` pushes most AI-generator corner watermarks out of frame by
  default; if one still shows up in QA, tighten the margin further for that specific image
  rather than the whole pipeline.
- **Crossfade drift (fixed 2026-08-21):** `build_bg()` advanced each xfade offset by the
  image's duration *minus* the 0.6s crossfade, but the offset is measured in the accumulated
  stream and must advance by the full duration. The background therefore came out
  `0.6 × (stills − 1)` short — **2.4s on the 5-still episode this file recommends** — with
  every still after the second entering early by a growing margin.

  What that looks like, measured on `put-i-istoriya/#1` (5 stills, 49.0s narration): the
  background was 46.63s, the finished video was still 49.00s, and the narration was **not**
  clipped. The logo input (`-loop 1 -t total_dur`) keeps the overlay's framesync running past
  the end of the background, and framesync holds the last frame — so the closing still
  **freezes for the final 2.4 seconds**, and each cut before it lands ahead of the words it
  was timed to. Frame-to-frame difference over the last three seconds: 4-5 (frozen) before the
  fix, 179-255 (Ken Burns still moving) after.

  Harmless at 1-2 stills, which is why it survived the pilot round. **Any episode built with
  three or more stills before that date is worth re-rendering** — 13 in this repo (all 12 of
  `trudnosti-puti` plus `put-i-istoriya/#1`). TTS and images are cached, so a re-run only
  redoes the assembly and costs nothing *where the stills are on disk*: in this repo only
  `put-i-istoriya` has its full set (`media/projects/guru-i-uchenik/images/` and
  `media/projects/trudnosti-puti/images/` are empty — that series' stills went to
  `images-cf/` and only for episode 1), so the other 12 have to be re-rendered wherever their
  stills actually live.
- **Logo:** the bird-logo corner watermark (`media/projects/uka-bird/logo-bird.png`) is
  baked into every episode by `build_narrated_short.py`, top-left, ~150px, always clear of the
  bottom-anchored captions. Non-negotiable per user request — do not build an episode without it.
