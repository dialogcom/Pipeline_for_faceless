# narrated-shorts - setup guide for a new machine/account

This is the **narrated-shorts** track only: one narrator voice reading a hook/body/ending-hook
script over 1-2 AI-generated 9:16 stills (Ken Burns pan/zoom + crossfade), with word-synced
burned-in captions and a corner logo. Output is a vertical MP4, 45-65s, ready for YouTube
Shorts / Reels / TikTok.

No Remotion, no Node.js, no browser automation - this track is **plain Python + ffmpeg**.
That's the whole stack.

See [`DESIGN.md`](DESIGN.md) in this same folder for the format spec and the hard-won rules
(dash conventions, stress-fixing, image-prompt safety filter gotchas). This document is the
"get a stranger from zero to a rendered video" setup guide; DESIGN.md is the reference once
you're up and running.

## 1. Prerequisites

- **Python 3.10+**
- **ffmpeg** and **ffprobe** on your `PATH` (`brew install ffmpeg` on Mac, `apt install ffmpeg`
  on Linux, or download a build for Windows and add it to PATH)
- **Pillow**: `pip install pillow` - the only non-stdlib Python dependency this track needs
  (used for burning captions/logo onto frames)
- **git** (to clone the repo)
- VS Code: no special extensions required. The Python extension is nice-to-have for syntax
  help; `scripts.json` is plain JSON so VS Code's built-in JSON support (formatting,
  validation) is enough.

Verify ffmpeg is reachable before doing anything else:
```bash
ffmpeg -version && ffprobe -version
```

## 2. Get the code

```bash
git clone <repo-url>
cd claude-faceless-shorts-creator
```

Everything below assumes your terminal's working directory is the repo root - the tools
resolve their own engine paths relative to `tools/`, but resolve *project* paths (like
`narrated-shorts/...`) against the current working directory.

## 3. API keys (2 required for this track)

Copy the template and fill it in:
```bash
cp .env.example .env
```

Or, to type the keys without them landing on screen or in your shell history:
```bash
bash tools/setup_keys.sh
```

`.env` is git-ignored - never commit it. Fill in only these two lines for narrated-shorts:

| Variable | Where to get it | What it's for | Rough cost |
|---|---|---|---|
| `OPENROUTER_API_KEY` | [openrouter.ai](https://openrouter.ai) → Keys | AI stills, via OpenRouter's unified `/images` API, model `google/gemini-3.1-flash-image` | ~$0.067/image |
| `INWORLD_API_KEY` | [inworld.ai](https://inworld.ai) dashboard → get a Basic-auth key (already `base64(client_id:client_secret)` - paste it as-is, no re-encoding needed) | Narrator voice with native word-level timestamps (no forced-alignment step) | Inworld's own per-character pricing - check their dashboard |

You do **not** need `GEMINI_API_KEY` or `ELEVENLABS_API_KEY` for this track specifically (those
back the other 4 production tracks in this repo, which you're not using).

## 4. Layout you'll be working with

```
narrated-shorts/<series-slug>/
  scripts.json      - array of episode specs, the source of truth (you write/edit this)
  voice/            - cached TTS: short-NN-slug.mp3 + .words.json  [gitignored, regenerable]
  output/           - final rendered short-NN-slug.mp4             [gitignored, regenerable]

media/projects/<series-slug>/images/
  sN_i.png          - AI stills, one per images[] entry in scripts.json
                      (COMMIT these - they're paid and non-reproducible; everything else
                      above is gitignored and rebuilds from scripts.json + your API keys)

tools/build_narrated_short.py   - the pipeline itself
```

## 5. Write a `scripts.json` entry

Each episode is one object in a JSON array:

```json
{
  "id": 1,
  "slug": "kebab-case-slug",
  "hook": "First ~2-3 sentences - bold gold caption style, grabs attention.",
  "vo": "The body of the narration - regular white caption style.",
  "ending": "Closing line. A next-episode teaser is fine ONLY if the series is genuinely episodic.",
  "images": [
    ["An English gen_image prompt describing the scene, vertical composition", 0.4],
    ["A second prompt if the script describes a contrasting second scene/moment", 0.6]
  ],
  "voice": {"voice_id": "Nikolai", "model": "inworld-tts-1.5-max", "temperature": 1.1, "speaking_rate": 1.0}
}
```

Notes:
- `hook` + `vo` + `ending` are concatenated and sent to TTS as one continuous narration -
  write them to read naturally back-to-back.
- **1 image vs. several**: pick however many distinct visual beats the script actually has -
  each `images[]` entry gets its own Ken-Burns pan/zoom, and duration fractions must sum to
  `1.0`. More images (4-5 for a ~60s video) reads better for retention than 1-2 held too long.
- Image prompts are **English**, specific (subject, composition, lighting), and end with
  `"vertical composition"` as a trailing tag.
- **Never write realistic banknotes/currency into a prompt** - Gemini's safety filter reliably
  blocks it. Use gold coins/bars or a symbolic treatment instead.
- **Dashes**: use a plain hyphen `-`, never an em-dash or en-dash, anywhere in `hook`/`vo`/`ending`. The
  pipeline auto-converts em/en-dashes to a hyphen before sending to TTS regardless, but
  writing it correctly up front avoids surprises in the burned-in captions.
- `voice` is optional per-entry (defaults shown above if omitted).

## 6. Build

Pilot one episode first - voice tuning, caption style, and image-prompt accuracy are much
cheaper to fix once than across a whole series:

```bash
python tools/build_narrated_short.py --spec-file narrated-shorts/<series-slug>/scripts.json --id 1
```

Then the rest:
```bash
python tools/build_narrated_short.py --spec-file narrated-shorts/<series-slug>/scripts.json
```

This runs every entry **not yet cached**. Caching is by filename:
- TTS: `voice/short-NN-slug.mp3` + `.words.json` - if these exist, TTS is skipped (no repeat
  charge) even on a full re-run.
- Images: `media/projects/<series>/images/sN_i.png` - same deal, cached by that exact path.

**Gotcha**: the image cache is keyed by *filename*, not by prompt content. If you edit an
existing entry's `images[i]` prompt but keep the same index `i`, the old image will NOT be
regenerated - delete that specific `.png` file first to force a redo:
```bash
rm media/projects/<series-slug>/images/s3_1.png
python tools/build_narrated_short.py --spec-file narrated-shorts/<series-slug>/scripts.json --id 3
```

If one episode's image prompt gets rejected by the safety filter, fix just that entry and
re-run with `--id N` - already-built episodes are untouched.

## 7. QA before you call it done

Pull a handful of frames spread across the render and actually look at them:
```bash
ffmpeg -y -ss 15 -i narrated-shorts/<series>/output/short-01-slug.mp4 -frames:v 1 frame.png
```
Check: captions synced and legible, hook segment reads visually distinct (gold vs. white
caption style), images match their prompts, the corner logo is present and clear of caption
text. For Cyrillic scripts, do one full listen-through before batch-generating a whole series
off a new script style - Inworld occasionally mis-stresses a word (see DESIGN.md's
stress-fix technique: swap the word, or insert a combining acute accent `́` after the
stressed vowel in the source text).

## 8. Cost awareness

Per ~60s episode with 5 images: **5 × $0.067 ≈ $0.34** in image cost, plus Inworld's TTS cost
for ~150-200 words of narration (check their dashboard for current per-character pricing).
State the total before batch-building a series with many episodes.

## Optional: alternate image providers

The core pipeline uses OpenRouter as described above. Two more image tools exist in `tools/`
if you want to compare quality/cost against a different provider - neither is required:

- `tools/gen_image_fal.py` - fal.ai, model-agnostic (`--model` flag), default
  `fal-ai/flux-pro/v1.1-ultra`, ~$0.06/image. Needs `FAL_KEY` in `.env`.
- `tools/gen_image_cloudflare.py` - Cloudflare Workers AI, model-agnostic. Needs
  **both** `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` in `.env` (Cloudflare requires
  an account ID alongside the token, unlike single-key APIs). Tested models:
  - `@cf/stabilityai/stable-diffusion-xl-base-1.0` (default) - cheapest, rougher quality
    (occasional anatomy/composition artifacts), fine for drafts only.
  - `@cf/leonardo/lucid-origin` - noticeably better quality, close to OpenRouter/Gemini,
    ~$0.06/image.
  - `@cf/leonardo/phoenix-1.0` - also strong, more atmospheric/less literal to the prompt,
    ~$0.05/image.
  - Cloudflare's **free tier caps at 10,000 "neurons"/day** across all models combined -
    resets daily. A paid Workers plan removes the cap.

Neither tool touches `build_narrated_short.py`'s own image generation - to actually use one
for a real episode, generate the images to a separate path and re-run the final assembly
step manually (see how `tools/rebuild_with_cf_images.py` in this repo's history did it as a
one-off example, reusing `build_narrated_short()`'s exported function with cached
voice/words and swapped-in image paths).

## Optional: anti-duplicate re-upload intro

`tools/add_intro_bumper.py` prepends a short (~3s) spoken "by the way, today's about X" line
over a fixed B-roll clip before the episode's existing hook - useful if you're planning to
re-upload a video after a gap and want the opening seconds to not be byte-identical to what
was already published. Add an `"intro"` field to the `scripts.json` entry, point
`BUMPER_CLIP` in the script at a vertical B-roll clip you own the rights to, then:
```bash
python tools/add_intro_bumper.py --spec-file narrated-shorts/<series>/scripts.json --id 1
```
Writes `output/short-NN-slug-intro.mp4` alongside (not over) the original. Worth knowing:
this only changes the fingerprint of the first few seconds - the rest of the video is still
byte-identical to the original upload, so it reduces (does not eliminate) duplicate-detection
risk.
