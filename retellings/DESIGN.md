# retellings/ — long-form story retellings (6th production track)

A **4-6 minute** narrated video: one voice (Inworld/Nikolai) reading a story written against
the 7-beat structure in [`STORY-STRUCTURE.md`](STORY-STRUCTURE.md), over ~20 AI-generated 9:16
stills (Ken Burns + crossfade), with word-synced burned-in captions and the corner logo.
Plain Python + ffmpeg, no Remotion.

Its raw material is usually a short this repo already made: a 40-65s `vox-shorts/` or
`ai-shorts/` episode has one fact and one turn compressed into a minute, and that is exactly
the seed a five-minute retelling needs — the research is done, and the length is spent on the
*story* rather than on more facts. First one: `petlya-i-spiral/`, retold from
`vox-shorts/vox-17-petlya-i-spiral/` (64.3s → ~5:00).

## Why its own track and not a long narrated-short

Same stack as `narrated-shorts/`, three differences, all of them consequences of length:

| | narrated-shorts | retellings |
|---|---|---|
| script unit | one blob (`hook` + `vo` + `ending`) | a list of **beats**, each with a `role` from the 7-beat structure |
| TTS cache | one file per episode | **one file per beat** — rewriting beat 6 costs one beat of TTS, not five minutes of it |
| silence | none | explicit `pause_after` per beat; the pause after `quiet` is the pacing |
| stills | 1-5 | ~20, declared per beat (one per ~15s) |
| captions | one ffmpeg input per chunk (~25) | ~134 chunks, burned in **batches** (see below) |

At 60 seconds none of that pays for itself. At five minutes all five do.

## Format

@30fps, 4-6 minutes, in **one of two frame shapes**, declared per story in `script.json`:

| `"format"` | frame | for | crossfade | corner logo |
|---|---|---|---|---|
| `"9:16"` (default) | 1080×1920 | Reels/Shorts, phone | 0.6s | 170px |
| `"16:9"` | 1920×1080 | **YouTube** — the shape this track is actually aimed at | 1.2s | 240px |

The shape is resolved once, by `spec_format()` in `tools/build_retelling.py`, and handed to
every stage — stills, captions, the Ken Burns crop, the logo. Nothing downstream re-derives
it, so a caption and a still cannot disagree about what frame they are in.

**16:9 is not 9:16 rotated.** Three things change with the shape and all three are in code,
not in the writer's head:

- *Captions.* `CAPTION_LAYOUT` in `build_narrated_short.py` holds one entry per shape, picked
  by `w > h`. Horizontal type is larger in pixels (52/64 against 46/58) but smaller as a
  share of frame height, the measure is nearly twice as wide so a caption stays on one or two
  lines, and the band sits 150px off the bottom instead of 460 — vertical hides captions above
  a phone UI that does not exist on a desktop, and lifting them a third of the way up a wide
  frame would cover the picture.
- *Prompts.* A 9:16 prompt asks the model to stack a subject; a 16:9 prompt has to say what
  fills the sides, or you get one centred object and two thirds of empty frame. `load_spec()`
  refuses to build when a prompt still says "vertical" in a 16:9 spec (or the reverse) —
  that mistake is only visible 22 paid stills later.
- *Pacing.* A YouTube retelling is put on in a background tab and listened to more than
  watched, so the dissolve is doubled to 1.2s: at ~13s per still it is still under 10% of the
  shot, and the video never appears to cut. The build's arithmetic is xfade-neutral — every
  offset cancels the fade back out — so this changes the feel and not the length.

### Паузы и подложка: единственное, что измеримо убивает досматриваемость

Это не вкусовщина, а цифры с самого канала (`~/.claude/skills/yt-analytics`, выборка за
90 дней):

| ролик | длина | досмотрели до конца | самая длинная пауза |
|---|---|---|---|
| Сила идеала | 28 с | **73%** | 0.8 с |
| Ветер не выбирает | 29 с | 15% | 3.0 с |
| Река не спорит с берегом | 31 с | **5%** | 3.6 с |

Обвал начинается ровно на паузе. Отсюда два правила трека:

1. **`pause_after` = 0.4 с между рабочими тактами, 0.7 после `quiet`, 0.6 после `return`.**
   Реальный зазор выходит примерно на 0.45 с длиннее заданного - столько тишины Inworld
   оставляет в хвосте такта, - так что 0.4 на бумаге даёт слышимые ~0.85 с. Значения
   0.7-0.9, записанные в `STORY-STRUCTURE.md` §3, дают на слух 1.2-1.35 с и для ЭТОГО
   канала уже великоваты; схема писалась до того, как появились замеры.
2. **`MUSIC_DB = -15`, а не -24.** На -24 подложка садится на ~28 дБ ниже речи и на
   телефоне не слышна вообще - пауза звучит как обрыв дорожки. На -15 она примерно на
   19 дБ ниже речи: слышна, не мешает, и держит паузу как дыхание.

Проверять готовый ролик так:

```bash
ffmpeg -i output/<slug>.mp4 -af "silencedetect=noise=-40dB:d=0.5" -f null /dev/null
```

Ни один зазор не должен превышать секунду с небольшим, и ни в одном не должно быть
цифровой тишины: замерьте уровень внутри паузы, он обязан держаться около -40 дБ, а не
уходить в -60.

Ещё одно, из тех же данных: **длину хронометража нельзя добирать паузами.** Именно так
пилот и получил свои 1.62 с после хука и 2.33 с перед поворотом. Рычаг длины - темп
чтения (`speaking_rate`) и текст, но не тишина.

Narrator: Inworld `Nikolai`, `inworld-tts-1.5-max`, temperature 1.1 — the same voice as
`narrated-shorts/`, so the two tracks sound like one channel.

**Speaking rate 0.90 on 16:9, 1.0 on 9:16.** A 60-second episode is read at the pace of a
scroll; a five-minute story on YouTube is read at the pace of an audiobook (~117 wpm). The
slower rate is also the length lever: `petlya-i-spiral` came out at 4:34 at rate 1.0 and 5:04
at 0.90, off exactly the same 619 words. Reach for the rate and the between-beat pauses before
adding text, and never reach for filler audio — a pause stuffed with a sound effect is audible
as padding. Confirmed on the pilot (21.08.2026): zero mis-stressed words at 0.90.

**Length arithmetic.** Measured over the 17 `guru-i-uchenik` episodes: 2102 words / 971.0s =
**129.9 words per minute** (`WPM` in `tools/build_retelling.py`). Five minutes of read text is
therefore **~630-650 words** including the pauses. Per-episode variance across those 17 was
121-140 wpm, so treat ±10% as normal and let `--dry-run` do the arithmetic:

```bash
python tools/build_retelling.py --spec retellings/<slug>/script.json --dry-run
```

It prints per-beat word counts, predicted seconds, still count and dollar cost, and spends
nothing. Run it before every build.

## Per-project artifact contract

```
retellings/<slug>/
  script.json     — the spec: slug, title, voice, music, beats[]  (source of truth, committed)
  script.md       — the beat sheet, the sources behind every checkable claim, episode notes
  voice/          — per-beat TTS cache <slug>-bNN-<role>.mp3 + .words.json   [gitignored]
  voice/<slug>_build/ — ffmpeg scratch                                       [gitignored]
  output/<slug>.mp4                                                          [gitignored]

media/projects/<slug>/images/
  bNN_i.png       — AI stills, one per images[] entry (COMMITTED — paid, non-reproducible)
```

## Pipeline, and where you can intervene

The build is deliberately stoppable at every point where changing your mind is still cheap.
Nothing after a stage costs anything until you run the next one.

```bash
python tools/build_retelling.py --spec retellings/<slug>/script.json --dry-run     # plan + cost
python tools/audit_voice.py --profile voice-profiles/chekhov-ru --spec .../script.json
python tools/build_retelling.py --spec retellings/<slug>/script.json --voice-only  # TTS, then LISTEN
python tools/build_retelling.py --spec retellings/<slug>/script.json --images-only # stills, then LOOK
python tools/build_retelling.py --spec retellings/<slug>/script.json               # full build
```

| после чего | что смотреть | как вмешаться |
|---|---|---|
| `--dry-run` | слова и секунды по тактам, число кадров, цена | правьте `script.json`; потрачено ноль |
| `audit_voice` | 100 баллов и конкретные предложения | правьте текст, гоняйте снова |
| `--voice-only` | `voice/<slug>_build/voice.wav` — послушать целиком | ударение не то → правьте текст такта, удалите его `.mp3`/`.words.json`, перегенерите **один такт**, не пять минут |
| `--images-only` | `voice/<slug>_build/stills-contact-sheet.jpg` — все кадры одним листом, пронумерованы | кадр не тот → правьте промпт **и удалите этот PNG** (кэш по имени файла), запустите снова |
| полная сборка | `bg.mp4` (фон без текста), `cap_pass*.mp4` (по пачкам капшенов), `audio_mixed.wav` | пересобрать можно любой из этапов, удалив соответствующий файл |

Every stage is cached by filename, so a re-run only redoes what changed. **The image cache is
keyed by filename, not by prompt** — edit a prompt and you must delete that PNG:

```bash
rm media/projects/<slug>/images/b05_2.png
```

The contact sheet is written before assembly on every full build too, not just under
`--images-only`: twenty-one stills are the expensive, hardest-to-re-roll part, and flipping
through a folder is how a wrong one gets missed.

## Hard rules

- **`--voice-only` before stills, always.** Five minutes of narration is ~$1.40 of stills; a
  mis-stressed word found after generating them costs the whole set. Listen first.
- **Stress fixes** work exactly as in `narrated-shorts/DESIGN.md`: swap the word, or put a
  combining acute `́` (U+0301) after the stressed vowel in `script.json`. The builder strips
  the mark before it reaches a caption. `petlya-i-spiral` carries five, inherited from vox-17:
  Чинмо́й, петли́ (×2), ме́рите, вираже́.
- **Dashes:** plain hyphen `-` only, never `—`/`–`. `load_spec()` rejects the spec outright if
  it finds one, because a long dash reads as visibly AI-written and would have to be caught
  again in every caption.
- **Numbers get spelled out in words** in the VO text ("в тысяча девятьсот семьдесят шестом"),
  not left as digits. Inworld's Russian reading of bare numerals is unreliable, and the
  captions inherit whatever the text says.
- **Gold captions belong to `hook` and `turn` only** (`CAPTION_BY_ROLE`). If half the video is
  gold, none of it is.
- **Image fractions sum to 1.0 within a beat**, not across the video — re-timing one beat must
  not silently re-time another beat's picture. `load_spec()` enforces this.
- **Corner logo is non-negotiable**, same chip and placement as narrated-shorts.
- **No CTA outro.** `return` ends on an image. The `narrated-shorts` teaser exception does not
  extend here: a five-minute video that ends by asking for something has spent the viewer's
  time and then asked for more.
- **Every checkable claim goes in `script.md` with its source.** A five-minute factual retelling
  that gets a date wrong is worse than a sixty-second one, because it sounds more authoritative.

## What five minutes breaks, and how the assembly answers it

Three things in the narrated-shorts assembly are fine at 60 seconds with two stills and wrong
at five minutes with twenty-one. All three were found by running the pipeline end to end on
placeholder stills and a synthetic voice track — see "Smoke-testing without keys" below.

**Captions are burned in batches.** narrated-shorts gives every caption chunk its own ffmpeg
input: ~25 at 60s, ~122 here, i.e. that many decoded 1080×1920 RGBA frames (≈1 GB) held at
once. The builder walks the *same proven overlay chain* in batches of `--batch` (default 40),
re-encoding intermediates at CRF 18. The corner logo rides in the final batch instead of
taking a pass of its own — at this length every extra full-video encode costs minutes and one
more generation.

**The background is built in one pass.** narrated-shorts crossfades pairwise, re-encoding the
accumulated video once per image. At two images that is one extra encode; at twenty-one it is
twenty, and the opening still ends up twenty generations deep. `build_bg_chain()` puts all N
stills and all N-1 xfades in a single `filter_complex`. Measured on the smoke run: 19s instead
of 158s, and one encode instead of twenty.

**Crossfade offsets advance by the full image duration.** Each xfade's offset is measured in
the *accumulated* stream, so it advances by the previous image's whole duration, not duration
minus the crossfade. Subtracting the crossfade each time (which `build_bg` did until
2026-08-21) leaves the background `0.6 × (stills − 1)` short: 2.4s on a 5-still narrated
short, **12s on a 21-still retelling**.

The symptom is not a shorter video and not clipped narration — the logo input
(`-loop 1 -t total_dur`) keeps the overlay's framesync alive past the end of the background,
and framesync holds its last frame. So the closing still **freezes** for those seconds while
every earlier cut lands ahead of the words it was timed to. Verified on a real 5-still
episode: background 46.63s under a 49.0s narration, finished video still 49.00s, last three
seconds frame-identical. Fixed in both tracks.

**Two ffmpeg gotchas the graph depends on.** A Ken Burns fragment feeds `zoompan` exactly ONE
frame (`-i image.png`, no `-loop`, no input-side `-t`) — `zoompan`'s `d=` expands *every*
input frame, so a looped input produced a 313-second background for a 49-second script. And
`trim`/`setpts` leaves the stream marked variable-rate, which `xfade` rejects outright
("current rate of 1/0 is invalid"), so each fragment ends `,fps=30,format=yuv420p`.

## Smoke-testing without keys

The voice and the stills cost money and need `INWORLD_API_KEY` / `OPENROUTER_API_KEY`. Every
other stage does not, and it is the part most likely to be wrong. Generate 21 placeholder PNGs
at full 1080×1920, synthesise per-beat tone tracks with word timings at the measured 130 wpm
(keeping punctuation attached to the words, the way Inworld returns it — `chunk_words` breaks
captions on it), compress the timeline ~6× to keep the run under a minute, and drive
`concat_voice` → `build_bg_chain` → `mix_audio` → `overlay_captions` → mux directly.

Then check the output duration against the sum of beat durations. It should match to within a
frame; the 12-second drift above showed up as nothing but that number being wrong. Pull frames
across the runtime and read them: gold captions on `hook` and `turn`, white elsewhere, logo
clear of the caption band, Ken Burns actually moving between stills.

## Где живут ключи

`.env` в git не хранится — и не должен. Из этого следует то, что регулярно сбивает с толку:
**сессия Claude Code, поднятая из GitHub, ключей не видит**, даже если предыдущая сессия на
локальной машине ими пользовалась. Это разные машины, а не одна с потерянной памятью.

Три рабочих места для ключей, каждое даёт своё:

| где | кто сможет собирать | как положить |
|---|---|---|
| `.env` на вашей машине | локальный Claude Code и вы сами в терминале | `bash tools/setup_keys.sh` |
| Secrets репозитория на GitHub | workflow «Собрать пересказ» — кнопкой во вкладке Actions, без терминала | Settings → Secrets and variables → Actions → New repository secret |
| переменные окружения remote-окружения Claude Code | сессия, поднятая из GitHub, то есть Claude в вебе | настройки окружения на claude.ai/code |

Ключи от прошлых проектов ищутся `bash tools/find_keys.sh` — он обходит `.env` на диске и
показывает, где какой ключ заполнен, печатая только пути и имена, но не значения.

`tools/setup_keys.sh` спрашивает ключи по одному, **не отображая ввод**, обновляет строку в
`.env` на месте вместо дублирования, ставит права `600` и отказывается работать, если `.env`
вдруг не значится в `.gitignore`. Значение не попадает ни на экран, ни в историю команд —
в отличие от `echo KEY=... >> .env`, которая оставляет ключ и там, и там.

`.github/workflows/build-retelling.yml` запускается только вручную (этапы `images` и `full`
тратят деньги, автозапуск по push означал бы оплату каждого коммита), всегда печатает смету
до трат, кэширует озвучку между запусками и коммитит сгенерированные кадры обратно в
репозиторий — по правилу «платные пиксели хранятся в гите», иначе следующий запуск заплатит
за них снова.

Секреты Actions доступны любому, кто может пушить в репозиторий: он вправе добавить workflow,
который их напечатает. Для приватного личного репозитория это нормально, для общего — нет.

## Providers

Voice is always Inworld (`INWORLD_API_KEY`) — the track needs native Russian and word-level
timestamps. Stills are pluggable, declared per project in `script.json`:

```json
"image_provider": "cloudflare",
"image_model": "@cf/leonardo/lucid-origin"
```

| provider | keys | notes |
|---|---|---|
| `openrouter` (default) | `OPENROUTER_API_KEY` | `google/gemini-3.1-flash-image`, ~$0.067/still. Its safety filter blocks realistic banknotes |
| `cloudflare` | `CLOUDFLARE_API_TOKEN` **and** `CLOUDFLARE_ACCOUNT_ID` | Workers AI, the route this project actually runs on. `@cf/leonardo/lucid-origin` takes `width`/`height` up to 2500, so 1080×1920 is native. ~$0.06/still |
| `modelscope` | `MODELSCOPE_API_KEY` | Qwen-Image and friends |

**Not every Workers AI model accepts a size.** FLUX.1-schnell rejects `width`/`height`
outright — `gen_image_cloudflare.py` used to send them unconditionally, which is why the
proven Flux route had to be re-written as a throwaway script every session (recorded in
`vox-shorts/HANDOFF.md`). Since 2026-08-21 the size is a request, not a demand: it is dropped
for known square-only models and retried without on a size complaint. A square still
cover-crops to 9:16 downstream and loses its sides, so prefer a sizing model
(`lucid-origin`, SDXL) where composition matters; switch to the proven
`@cf/black-forest-labs/flux-1-schnell` by changing one line of `script.json` if
`lucid-origin` is not available on the account.

**Cloudflare's free tier caps at 10,000 neurons/day across all models.** A 22-still retelling
can hit that ceiling before it hits a bill; a paid Workers plan removes the cap. If stills
start failing partway, that is the likely reason — the cache means a re-run the next day only
generates the ones that are still missing.

`build_retelling.py` runs a **preflight** before anything else and names every missing key,
counting only work that is actually outstanding: a finished build never asks for credentials
it will not use, and `--voice-only` never asks for an image key.

## Cost and wall-clock

Per five-minute episode: ~22 stills — **~$1.32** on Cloudflare `lucid-origin`, ~$1.47 on
OpenRouter — plus Inworld TTS for ~4,000 characters. State it before building; `--dry-run`
prints the number for the provider the spec actually declares.

Assembly time, extrapolated from the smoke run on a plain x86 container (libx264 `veryfast`,
no hardware encode): roughly **2 minutes for the background and 5-6 for the caption passes**,
so ~8 minutes of ffmpeg for a five-minute video. Budget more on a slower box, less where the
encoder is hardware-accelerated.
