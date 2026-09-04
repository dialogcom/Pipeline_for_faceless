# CLAUDE.md — claude-faceless-shorts-creator

A **faceless-shorts factory** driven by Claude Code. Six production tracks, one repo — the
right skill is picked automatically from the request:

| The user asks for… | Skill | Pixels come from | Projects live in |
|---|---|---|---|
| "make a short about X" (default) | `/make-short` | 100% TSX (Remotion animation) | `shorts/short-N-<niche>/` |
| "make an AI video short", "blue-man video" | `/make-ai-short` | a fal video model (locked recurring character) | `ai-shorts/<series>/` |
| "vox style / documentary / explainer short" | `/make-vox` | layered paper-collage (AI images + cutouts) | `vox-shorts/vox-N-<topic>/` |
| a batch/carousel of narrated shorts from a script set | `/make-narrated-short` | Inworld TTS narrator over AI stills (Ken Burns), plain ffmpeg | `narrated-shorts/<series-slug>/` |
| cut an existing recording (Zoom call, webinar) into a cliffhanger series | `/repurpose-recording` | the user's own footage, cropped/captioned, plain ffmpeg | `media/projects/<slug>/` (source in `raw-footage/<slug>/`) |
| a 3-6 min narrated story, or "retell that short at five minutes" | `/make-retelling` | Inworld narrator over ~20 AI stills, plain ffmpeg — **9:16 or 16:9, per story** | `retellings/<slug>/` |

The first three share a `beats.json` contract, ElevenLabs voice with word-exact captions
(`gen_voice.py`), and TSX composition (crash rules in `/vidtsx-2d-generator`). The last three
are plain ffmpeg; `narrated-shorts` and `retellings` share the Inworld narrator, the caption
renderer and the corner logo, and differ by length (45-65s vs 4-6 min) and by script unit (one
blob vs 7 structural beats). All six share: frame-by-frame QA at phone scale, library-first SFX
(`/suggest-sfx`) where applicable, optional music bed, no CTA outros (narrated-shorts is the one
deliberate, discussed exception — see its DESIGN.md).

## Layout

```
tools/            Python tools: eleven_keys (11labs key pool), gen_voice, vo_from_recording, gen_voice_inworld, gen_sfx,
                  gen_music, mix_sfx, mix_music, gen_chords, gen_image, gen_clip, bakeoff_clip,
                  cutout, capture_web, build_narrated_short, build_retelling, transcribe,
                  transcribe_local, fix_transcript, segment_episodes, frame_shots,
                  build_repurposed_episode, analyze_voice, audit_voice, post_telegram, publish_queue, doctor
remotion/         the Remotion project — src/lib/ (shared + niche kits incl. collage.tsx),
                  src/shots/{short-N, ai-N, vox-N}/  (narrated-shorts has no TSX — plain ffmpeg)
media/            Remotion's public root: library/ (reusable: sfx, music, logos)
                  + projects/<proj>/ (media for ONE video — incl. committed AI clips & layers)
shorts/           TSX shorts: script.md, beats.json, sfx-plan.json each
ai-shorts/        generative shorts: + character.json (LOCKED reference), shot sidecars, IDEAS.md
vox-shorts/       collage shorts: + DESIGN.md (the visual language — read before any vox work)
narrated-shorts/  narrator+AI-stills shorts: + DESIGN.md, scripts.json per series (source of truth)
retellings/       4-6 min narrated stories: + DESIGN.md, STORY-STRUCTURE.md (the 7-beat writing
                  contract, read before writing), script.json + script.md per story.
                  The only track that also builds HORIZONTAL: "format": "16:9" in the spec
                  -> 1920x1080 for YouTube (captions, stills, logo and xfade all follow)
voice-profiles/   cross-track writing layer: measured voice profiles (PROFILE.md +
                  metrics.json) — chekhov-ru for narrative tracks, uka-ru for 60s episodes —
                  plus the audience profile and the anti-AI-tell reference set.
                  Read voice-profiles/README.md before writing narration
raw-footage/      source recordings for repurpose-recording projects [gitignored]
brand.md          the style contract every skill reads (palette, motion, safe areas, SFX taste)
IDEAS.md          the TSX-shorts idea bank + niche ranking
.claude/skills/   make-short, make-ai-short, make-vox, make-narrated-short, make-retelling,
                  repurpose-recording, vidtsx-2d-generator, suggest-sfx,
                  write-in-voice + audit-voice (the write -> score -> fix loop)
```

## Conventions (hard rules)

- **Run everything from the repo root.** Tools resolve engine paths (media/library, catalogs)
  against their own location, but project paths (`shorts/...`) against the CWD.
- **Python:** any Python 3.10+ — the core pipeline is stdlib-only. Only vox layer production
  needs extras: `pip install pillow rembg` (cutout.py) and `pip install playwright &&
  playwright install chromium` (capture_web.py). `ffmpeg`/`ffprobe` and `node`/`npx` on PATH.
- **API keys** live in `.env` at the repo root (copy `.env.example`). Never commit `.env`.
  ELEVENLABS_API_KEY (+ optional spares ELEVENLABS_API_KEY_2..9, auto-failover on
  quota via tools/eleven_keys.py) = voice/SFX/music/STT · FAL_KEY = AI clips + images · GEMINI_API_KEY = images ·
  OPENROUTER_API_KEY = fallback image route (unified `/images` API, used when the direct Gemini
  key is quota-limited) · INWORLD_API_KEY = narrated-shorts TTS (native Russian voices, e.g.
  Nikolai; word-exact timestamps built in, no forced-alignment step).
- **Registry is generated:** after adding/renaming a shot, `cd remotion && npm run gen`
  (frames.mjs/render-all.mjs do NOT run it themselves).
- **Media rules:** `media/library/` is for CROSS-VIDEO reusable assets only (each with a
  catalog). Anything generated FOR ONE video (story frames, AI clips, collage layers) goes in
  `media/projects/<proj>/`, referenced as `staticFile('projects/<proj>/x')`. Reuse before you
  generate — check the catalogs first.
- **Committed vs gitignored media:** AI-generated clips, collage layers, and narrated-shorts
  stills in `media/projects/` ARE committed (paid, non-reproducible pixels). `*/voice/` and
  `*/output/` are gitignored everywhere (regenerable) — including `narrated-shorts/*/` and
  `retellings/*/`;
  `ai-shorts/*/shots/*.mp4` working copies too — the canonical clip lives in
  `media/projects/<name>/`.
- **Costs (ai-shorts only):** state the derived generation cost BEFORE spending it, and never
  regenerate a locked character from text (see /make-ai-short's iron rules).
- **Voice is checked, not vibed:** narration for any track is written with `/write-in-voice`
  against a profile (`chekhov-ru` for `retellings/`, `uka-ru` for `narrated-shorts/`) and
  scored by `tools/audit_voice.py` (100 points, gate 80, deterministic — same text always
  gives the same number). Never add AI-drafted text
  back into a profile's corpus: a profile built on its own output stops being a reference.
- **QA is not optional:** render frames at phone scale and READ them before any full render.
