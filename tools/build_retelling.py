#!/usr/bin/env python3
"""
build_retelling.py — assemble one long-form "retelling" (retellings/ track, ~4-6 minutes).

Same pixels-and-voice stack as the narrated-shorts track (Inworld narrator + AI stills +
Ken Burns + word-synced burned-in captions + corner logo) but built for a *story* that runs
5 minutes instead of 60 seconds. Three things change, and all three exist because of the
length:

1. **The script is a list of beats, not one blob.** A 5-minute narration is written against
   the 7-beat structure in retellings/STORY-STRUCTURE.md (hook / scene / break / three /
   quiet / turn / return). Each beat is TTS'd and cached separately, so rewriting beat 6
   costs one beat of TTS, not five minutes of it. Beats also carry an explicit
   `pause_after` — the silence between beats is the pacing, and a 5-minute read without it
   is a wall.

2. **Captions are burned in batches.** narrated-shorts puts every caption chunk on its own
   ffmpeg input; at 60s that is ~25 inputs, at 5 minutes it is ~130 (≈1 GB of decoded RGBA
   held at once). This walks the same proven overlay chain in batches of --batch chunks,
   re-encoding the intermediate at CRF 18 so the extra generations do not show.

3. **Images are per beat.** One still per ~15s of narration; each beat declares its own
   stills with fractions summing to 1.0 *within that beat*, so re-timing one beat cannot
   silently re-time somebody else's picture.

Usage (each stage stops where you can still change your mind cheaply):
  python tools/build_retelling.py --spec ... --dry-run      # plan + cost, spends nothing
  python tools/build_retelling.py --spec ... --voice-only   # TTS only, then LISTEN
  python tools/build_retelling.py --spec ... --images-only  # stills + contact sheet, then LOOK
  python tools/build_retelling.py --spec ...                # full build

4. **The frame shape is per story.** "format": "16:9" builds 1920x1080 for YouTube, where a
   five-minute story is put on in a background tab; "9:16" (the default) builds the phone
   frame the narrated-shorts track uses. Captions, stills, the Ken Burns crop and the corner
   logo all read the same resolved shape, so they cannot disagree about what frame they are
   in — see FORMATS / LOGO_W / XFADE_BY_FORMAT below and CAPTION_LAYOUT in
   build_narrated_short.py.

Spec schema (retellings/<slug>/script.json):
  {
    "slug": "petlya-i-spiral",
    "title": "Петля и спираль",
    "format": "16:9",                          # optional, "9:16" (default) | "16:9"
    "xfade": 1.2,                              # optional, defaults per format
    "voice":  {"voice_id": "Nikolai", "model": "inworld-tts-1.5-max", "temperature": 1.1,
               "speaking_rate": 1.0},          # optional, these are the defaults
    "music":  "media/library/music/clips/ambient-pad.mp3",   # optional
    "image_provider": "alibaba",               # optional: openrouter (default) | alibaba | cloudflare | modelscope
    "image_style": ", authentic 1890s archival photograph, ...",  # optional, appended to every prompt
    "image_negative": "color photograph, modern digital render",  # optional, alibaba only
    "beats": [
      {"role": "hook", "text": "...", "pause_after": 0.8,
       "caption": "gold",                       # optional; defaults per role (see CAPTION_BY_ROLE)
       "images": [["<English prompt>, wide cinematic composition", 0.5], ["...", 0.5]]},
      ...
    ]
  }

Outputs (relative to the spec's directory — gitignored, see retellings/DESIGN.md):
  voice/<slug>-bNN-<role>.mp3 + .words.json    per-beat TTS cache
  voice/<slug>_build/                          ffmpeg scratch
  output/<slug>.mp4                            the finished video
Stills are COMMITTED under media/projects/<slug>/images/bNN_i.png (paid, non-reproducible).

Needs OPENROUTER_API_KEY (stills) and INWORLD_API_KEY (voice) in .env.
"""
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_narrated_short import (  # noqa: E402
    W, H, FPS, XFADE, ZOOM_MARGIN, ROOT as NS_ROOT, KEN_BURNS_MOTIONS, _zoompan_expr,
    chunk_words, gen_image_for, make_caption_png, make_logo_chip, mix_audio, strip_stress,
)
from gen_voice_inworld import tts_with_timestamps  # noqa: E402

# Frame shapes this track can build. "9:16" is the phone/Reels default the narrated-shorts
# track shares; "16:9" is YouTube, where a 5-minute story is put on in a background tab and
# listened to more than watched. The shape is chosen per story in the spec ("format"), not
# per tool, because the same script can legitimately ship in both.
FORMATS = {"9:16": (1080, 1920), "16:9": (1920, 1080)}
DEFAULT_FORMAT = "9:16"

# Corner-logo width per shape. The 9:16 value is the vox/shorts one, sized to survive being
# watched on a phone. 16:9 goes the other way and is deliberately SMALLER as a share of the
# frame (150/1920 = 7.8%, against 170/1080 = 15.7%): on a wide frame the top-left corner is
# empty picture rather than a crowded strip, so a chip scaled to match pulls the eye and
# starts reading as a title card. Here it is only a watermark.
LOGO_W = {"9:16": 170, "16:9": 150}

# Crossfade between stills. Longer on 16:9 on purpose: a background-listening video should
# never appear to cut, and at ~20s per still a 1.2s dissolve is still under 6% of the shot.
# The build's arithmetic is xfade-neutral — every offset cancels the fade back out — so this
# changes the feel and not the length.
XFADE_BY_FORMAT = {"9:16": 0.6, "16:9": 1.2}

# Music-bed gain for this track, louder than the 60-second episodes' -24 dB. A retelling has
# real silences in it by design (pause_after between beats), and on this channel dead air is
# the documented retention killer: three long "Природа" videos with 3.0-3.6s gaps ended at
# 5-15% watched, against 73% for the one whose longest gap was 0.8s. The bed has to be
# audible enough that a pause reads as a held breath.
MUSIC_DB = -18.0   # -15 до dynaudnorm; выравнивание подняло средний на ~3 дБ

# Measured on the guru-i-uchenik series (17 episodes, Nikolai @ speaking_rate 1.0):
# 2102 words over 971.0s = 129.9 wpm. Used only by --dry-run to predict length before
# spending anything on TTS — the real timing always comes from Inworld's word timestamps.
WPM = 130.0
# Per-still price by provider, for --dry-run's estimate. Cloudflare bills in "neurons" and
# the free tier caps at 10,000/day across all models, so a 22-still run can hit the cap
# before it hits a bill — see retellings/DESIGN.md.
IMG_COST_USD = {"openrouter": 0.067, "cloudflare": 0.06, "modelscope": 0.0}
DEFAULT_IMG_COST = 0.067

# Which API key each stage needs, so a build fails in the first second with the name of the
# missing key instead of halfway through, after paying for the half that worked.
VOICE_KEY = "INWORLD_API_KEY"
IMAGE_KEYS = {"openrouter": ["OPENROUTER_API_KEY"],
              "cloudflare": ["CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"],
              "modelscope": ["MODELSCOPE_API_KEY"]}

# Which caption style each structural beat gets. Gold is the loud style: it belongs to the
# beat that has to stop a scroll (hook) and the beat that pays the story off (turn). Every
# other beat is plain white — if half the video is gold, none of it is.
CAPTION_BY_ROLE = {"hook": "gold", "turn": "gold"}
DEFAULT_PAUSE = 0.7


def spec_format(spec):
    """(name, (W, H), xfade, logo_width) for one spec. One place decides the shape, so a
    caption, a still and a Ken Burns crop can never disagree about what frame they are in."""
    name = spec.get("format", DEFAULT_FORMAT)
    if name not in FORMATS:
        sys.exit(f"unknown format {name!r} — one of {', '.join(FORMATS)}")
    return name, FORMATS[name], spec.get("xfade", XFADE_BY_FORMAT[name]), LOGO_W[name]


def load_spec(path):
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    beats = spec.get("beats") or []
    if not beats:
        sys.exit(f"{path}: no beats")
    for i, b in enumerate(beats):
        if not b.get("text", "").strip():
            sys.exit(f"beat {i} ({b.get('role')}): empty text")
        imgs = b.get("images") or []
        if not imgs:
            sys.exit(f"beat {i} ({b.get('role')}): no images")
        total = sum(f for _, f in imgs)
        if abs(total - 1.0) > 0.01:
            sys.exit(f"beat {i} ({b.get('role')}): image fractions sum to {total:.3f}, must be 1.0")
        for ch in "—–":
            if ch in b["text"]:
                sys.exit(f"beat {i} ({b.get('role')}): long dash {ch!r} in text — "
                         f"this track uses a plain hyphen only (retellings/DESIGN.md)")

    # A prompt that still says "vertical composition" in a 16:9 build is the single most
    # expensive mistake available here: the model obeys the words, the frame cover-crops the
    # sides off the subject, and you find out 22 paid stills later. Caught before spending.
    name = spec.get("format", DEFAULT_FORMAT)
    if name not in FORMATS:
        sys.exit(f"unknown format {name!r} — one of {', '.join(FORMATS)}")
    fw, fh = FORMATS[name]
    wrong = "vertical" if fw > fh else "horizontal"
    for i, b in enumerate(beats):
        for k, (prompt, _) in enumerate(b.get("images") or []):
            if wrong in prompt.lower():
                sys.exit(f"beat {i} ({b.get('role')}) image {k}: prompt says {wrong!r} but "
                         f"format is {name} — rewrite the composition wording first")
    return spec


def dry_run(spec):
    """Print the plan and what building it would cost. Spends nothing."""
    beats, grand_words, grand_dur, n_img = spec["beats"], 0, 0.0, 0
    fmt, (fw, fh), xfade, _ = spec_format(spec)
    print(f"{spec.get('title', spec['slug'])}  [{spec['slug']}]  {fmt} {fw}x{fh}  "
          f"xfade {xfade}s")
    print(f"{'#':>2} {'role':<8} {'words':>6} {'est':>7} {'pause':>6} {'imgs':>5}  caption")
    for i, b in enumerate(beats):
        nw = len(strip_stress(b["text"]).split())
        est = nw / WPM * 60.0
        pause = b.get("pause_after", DEFAULT_PAUSE)
        style = b.get("caption", CAPTION_BY_ROLE.get(b.get("role"), "plain"))
        print(f"{i:>2} {b.get('role', '?'):<8} {nw:>6} {est:>6.1f}s {pause:>5.1f}s "
              f"{len(b['images']):>5}  {style}")
        grand_words += nw
        grand_dur += est + pause
        n_img += len(b["images"])
    provider = spec.get("image_provider", "openrouter")
    unit = IMG_COST_USD.get(provider, DEFAULT_IMG_COST)
    model = spec.get("image_model", "(provider default)")
    print(f"\ntotal: {grand_words} words, ~{grand_dur:.0f}s ({grand_dur/60:.2f} min) "
          f"at {WPM:.0f} wpm, {n_img} stills")
    print(f"stills via {provider} / {model}: {n_img} x ~${unit} = ~${n_img * unit:.2f}")
    print(f"voice via Inworld: {len(''.join(b['text'] for b in beats))} chars")
    print("(estimate only — real timing comes from Inworld's word timestamps)")


def preflight(spec, spec_dir, need_images=True):
    """Name every missing key up front. Both stages are cached, so a key is only required for
    work that is actually still outstanding — re-running a finished build must not demand
    credentials it will never use."""
    from gen_voice_inworld import load_env
    env = load_env()
    slug = spec["slug"]
    missing = []

    pending_voice = [b for i, b in enumerate(spec["beats"])
                     if not (spec_dir / "voice" / f"{slug}-b{i:02d}-{b.get('role', f'b{i}')}.words.json").exists()]
    if pending_voice and not env.get(VOICE_KEY, "").strip():
        missing.append(f"{VOICE_KEY} (нужен для {len(pending_voice)} тактов озвучки)")

    if need_images:
        provider = spec.get("image_provider", "openrouter")
        img_dir = NS_ROOT / "media/projects" / slug / "images"
        pending = sum(1 for i, b in enumerate(spec["beats"]) for k in range(len(b["images"]))
                      if not (img_dir / f"b{i:02d}_{k}.png").exists())
        if pending:
            for key in IMAGE_KEYS.get(provider, []):
                if not env.get(key, "").strip():
                    missing.append(f"{key} (нужен для {pending} кадров через {provider})")
    if missing:
        sys.exit("не хватает ключей в .env:\n  - " + "\n  - ".join(missing)
                 + "\nскопируйте .env.example в .env и заполните эти строки.")


def tts_beats(spec, voice_dir):
    """TTS every beat, cached per beat file. Returns (beat_infos, words, total_dur).

    words carry absolute times across the whole video; each beat's own timestamps are
    shifted by everything (narration + pauses) that ran before it."""
    voice_dir.mkdir(parents=True, exist_ok=True)
    vcfg = spec.get("voice", {})
    infos, words, offset = [], [], 0.0
    for i, b in enumerate(spec["beats"]):
        role = b.get("role", f"b{i}")
        stem = voice_dir / f"{spec['slug']}-b{i:02d}-{role}"
        mp3, wj = stem.with_suffix(".mp3"), Path(str(stem) + ".words.json")
        if wj.exists():
            data = json.loads(wj.read_text(encoding="utf-8"))
            bw, bdur = data["words"], data["duration"]
            print(f"  beat {i} {role}: cached {bdur:.1f}s", file=sys.stderr)
        else:
            audio, bw, bdur = tts_with_timestamps(
                b["text"], vcfg.get("voice_id", "Nikolai"), vcfg.get("model", "inworld-tts-1.5-max"),
                vcfg.get("temperature", 1.1), vcfg.get("speaking_rate", 1.0))
            mp3.write_bytes(audio)
            wj.write_text(json.dumps({"duration": bdur, "words": bw}, ensure_ascii=False, indent=2),
                          encoding="utf-8")
            print(f"  beat {i} {role}: tts {bdur:.1f}s {len(bw)}w -> {mp3.name}", file=sys.stderr)
        pause = b.get("pause_after", DEFAULT_PAUSE)
        style = b.get("caption", CAPTION_BY_ROLE.get(role, "plain"))
        shifted = [{"w": w["w"], "start": w["start"] + offset, "end": w["end"] + offset} for w in bw]
        words += shifted
        infos.append({"i": i, "role": role, "mp3": mp3, "style": style, "words": shifted,
                      "start": offset, "speech": bdur, "dur": bdur + pause})
        offset += bdur + pause
    return infos, words, offset


def concat_voice(infos, out_wav, work_dir):
    """Beat mp3s in order, each followed by its own pause_after of real silence."""
    parts = []
    for info in infos:
        part = work_dir / f"v{info['i']:02d}.wav"
        subprocess.run(["ffmpeg", "-y", "-i", str(info["mp3"]), "-ar", "44100", "-ac", "2", str(part)],
                       capture_output=True)
        parts.append(part)
        gap = info["dur"] - info["speech"]
        if gap > 0.01:
            sil = work_dir / f"s{info['i']:02d}.wav"
            subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                            "-t", f"{gap:.3f}", str(sil)], capture_output=True)
            parts.append(sil)
    listing = work_dir / "voice_parts.txt"
    listing.write_text("".join(f"file '{p.resolve()}'\n" for p in parts), encoding="utf-8")
    r = subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
                        "-ar", "44100", "-ac", "2", str(out_wav)], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"voice concat FAIL: {r.stderr[-1500:]}")


def caption_chunks(infos):
    """Word chunks for the whole video, each tagged with its beat's caption style. Chunked
    per beat so no caption ever spans a between-beat pause."""
    out = []
    for info in infos:
        for chunk in chunk_words(info["words"], max_words=6):
            out.append({"text": " ".join(w["w"] for w in chunk),
                        "start": chunk[0]["start"], "end": chunk[-1]["end"],
                        "gold": info["style"] == "gold"})
    return out


def contact_sheet(images, out_path, size, cols=6, thumb_w=300):
    """One JPEG with every still in order, numbered. The stills are the expensive, hardest to
    re-roll part of the build, and flipping through 21 PNGs in a file browser is how a wrong
    one gets missed — a sheet is one glance. Written before assembly starts, so a bad still
    costs one re-roll rather than a whole render."""
    w, h = size
    thumb_h = round(thumb_w * h / w)
    if w > h:            # wide thumbs need fewer per row or the sheet stops being one glance
        cols = min(cols, 4)
    rows = (len(images) + cols - 1) // cols
    pad, label_h = 8, 22
    sheet = Image.new("RGB", (cols * (thumb_w + pad) + pad,
                              rows * (thumb_h + label_h + pad) + pad), (18, 16, 24))
    d = ImageDraw.Draw(sheet)
    for i, (path, dur) in enumerate(images):
        x = pad + (i % cols) * (thumb_w + pad)
        y = pad + (i // cols) * (thumb_h + label_h + pad)
        try:
            im = Image.open(path).convert("RGB").resize((thumb_w, thumb_h), Image.LANCZOS)
        except Exception:
            im = Image.new("RGB", (thumb_w, thumb_h), (60, 20, 20))
        sheet.paste(im, (x, y))
        d.text((x + 4, y + thumb_h + 4), f"{i:02d}  {Path(path).stem}  {dur:.1f}s",
               fill=(230, 226, 240))
    sheet.save(out_path, quality=88)
    return out_path


def build_bg_chain(images, out_path, work_dir, size, xfade=XFADE):
    """Ken Burns over every still and crossfade the lot, in ONE ffmpeg pass.

    narrated-shorts builds the chain pairwise, re-encoding the accumulated video once per
    image. At 2 images that is one extra encode; at 21 it is twenty, and the first still ends
    up twenty generations deep — visible mush by the time the video reaches its own opening
    shot. One filter_complex with N looped image inputs and N-1 chained xfades encodes once.

    Offsets are measured in the accumulated stream, so each advances by the previous image's
    FULL duration (see build_bg's note on the drift that got fixed alongside this).
    """
    n = len(images)
    W, H = size
    inputs, filt = [], []
    for i, (img, dur) in enumerate(images):
        seg = dur + xfade
        nframes = max(1, int(round(seg * FPS)))
        z, x, y = _zoompan_expr(KEN_BURNS_MOTIONS[i % len(KEN_BURNS_MOTIONS)], nframes)
        # A bare "-i image.png" feeds zoompan exactly ONE frame, and zoompan's d= turns that
        # one frame into nframes. Looping the input instead (or bounding it with an input-side
        # "-t") makes zoompan expand EVERY looped frame: the first run of this produced a
        # 313-second background for a 49-second script. The trailing trim is the belt to that
        # brace, and keeps the fragment exactly as long as the offsets below assume.
        inputs += ["-i", str(img)]
        filt.append(
            f"[{i}:v]scale={int(W*ZOOM_MARGIN)}:{int(H*ZOOM_MARGIN)}:force_original_aspect_ratio=increase,"
            f"crop={int(W*ZOOM_MARGIN)}:{int(H*ZOOM_MARGIN)},"
            f"zoompan=z='{z}':x='{x}':y='{y}':d={nframes}:s={W}x{H}:fps={FPS},setsar=1,"
            # trim/setpts leaves the stream marked variable-rate, and xfade refuses anything
            # that is not constant ("current rate of 1/0 is invalid"), so re-stamp the rate
            # and pin the pixel format the encoder wants.
            f"trim=duration={seg:.3f},setpts=PTS-STARTPTS,fps={FPS},format=yuv420p[k{i}]")
    last, offset = "k0", images[0][1] - xfade
    for i in range(1, n):
        out = f"x{i}"
        filt.append(f"[{last}][k{i}]xfade=transition=fade:duration={xfade}:"
                    f"offset={offset:.3f}[{out}]")
        last = out
        offset += images[i][1]
    r = subprocess.run(["ffmpeg", "-y"] + inputs + ["-filter_complex", ";".join(filt),
                       "-map", f"[{last}]" if n > 1 else "[k0]", "-an",
                       "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                       "-pix_fmt", "yuv420p", str(out_path)], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"background build FAIL: {r.stderr[-2500:]}")


def overlay_captions(bg, chunks, out_path, work_dir, total_dur, size, logo_w, batch=40):
    """Burn caption PNGs onto bg, `batch` overlays per ffmpeg pass, logo in the last pass.

    One pass per caption (like narrated-shorts does at 60s) would mean ~130 simultaneous
    1080x1920 RGBA inputs on a 5-minute read. Same filter chain, just walked in batches;
    intermediates are CRF 18 so the extra encode generations stay invisible.

    The corner logo rides along in the final batch rather than taking a pass of its own: at
    this length every extra full-video encode costs minutes and one more generation of
    quality, and the logo is just one more overlay."""
    caps_dir = work_dir / "caps"
    caps_dir.mkdir(parents=True, exist_ok=True)
    n_passes = max(1, (len(chunks) + batch - 1) // batch)
    cur = bg
    for pi, bi in enumerate(range(0, max(1, len(chunks)), batch)):
        group = chunks[bi:bi + batch]
        inputs, filt, last, idx = ["-i", str(cur)], [], "0:v", 0
        for k, c in enumerate(group):
            png = caps_dir / f"{bi + k:04d}.png"
            make_caption_png(c["text"], png, hook=c["gold"], size=size)
            inputs += ["-i", str(png)]
            idx += 1
            filt.append(f"[{last}][{idx}:v]overlay=0:0:"
                        f"enable='between(t,{c['start']:.3f},{c['end']:.3f})'[v{idx}]")
            last = f"v{idx}"
        if pi == n_passes - 1:
            # '-loop 1' with an explicit '-t' is load-bearing on the logo input: `fade` needs
            # a real per-frame timeline to animate over, and an unbounded looped input never
            # reaches EOF — see build_narrated_short.py's note, learned in hours of runtime.
            chip = work_dir / "logo_chip.png"
            make_logo_chip(chip, width=logo_w)
            inputs += ["-loop", "1", "-t", f"{total_dur:.3f}", "-i", str(chip)]
            idx += 1
            filt.append(f"[{idx}:v]fade=t=in:st=0:d=0.8:alpha=1[logofade]")
            filt.append(f"[{last}][logofade]overlay=48:56[vlogo]")
            last = "vlogo"
        step = work_dir / f"cap_pass{pi:02d}.mp4"
        r = subprocess.run(["ffmpeg", "-y"] + inputs + ["-filter_complex", ";".join(filt),
                           "-map", f"[{last}]", "-c:v", "libx264", "-preset", "veryfast",
                           "-crf", "18", "-pix_fmt", "yuv420p", str(step)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"caption pass {pi} FAIL: {r.stderr[-2500:]}")
        print(f"  captions {min(bi + batch, len(chunks))}/{len(chunks)}"
              f"{' + logo' if pi == n_passes - 1 else ''}", file=sys.stderr)
        cur = step
    Path(cur).rename(out_path)


def build(spec_path, batch=40, voice_only=False, images_only=False):
    spec = load_spec(spec_path)
    spec_dir = Path(spec_path).parent
    slug = spec["slug"]
    fmt, size, xfade, logo_w = spec_format(spec)
    print(f"=== retelling: {spec.get('title', slug)} === {fmt} {size[0]}x{size[1]}",
          file=sys.stderr)

    preflight(spec, spec_dir, need_images=not voice_only)
    voice_dir = spec_dir / "voice"
    work_dir = voice_dir / f"{slug}_build"
    work_dir.mkdir(parents=True, exist_ok=True)

    infos, words, total_dur = tts_beats(spec, voice_dir)
    print(f"  narration: {total_dur:.1f}s ({total_dur/60:.2f} min), {len(words)} words",
          file=sys.stderr)
    voice_wav = work_dir / "voice.wav"
    concat_voice(infos, voice_wav, work_dir)
    if voice_only:
        print(f"voice-only -> {voice_wav}  (listen for mis-stress before spending on stills)",
              file=sys.stderr)
        return voice_wav

    img_dir = NS_ROOT / "media/projects" / slug / "images"
    # Written once per story, appended to every prompt: twenty stills that must look like one
    # film cannot rely on twenty prompts each remembering the same clause. Beats may override
    # the provider, and the style follows them across it.
    style, negative = spec.get("image_style"), spec.get("image_negative")
    images = []
    for info in infos:
        beat = spec["beats"][info["i"]]
        for k, (prompt, frac) in enumerate(beat["images"]):
            p = gen_image_for(f"b{info['i']:02d}_{k}", prompt, img_dir,
                              provider=beat.get("image_provider", spec.get("image_provider", "openrouter")),
                              model=beat.get("image_model", spec.get("image_model")),
                              size=size, style=style, negative=negative)
            images.append((p, info["dur"] * frac))

    sheet = contact_sheet(images, work_dir / "stills-contact-sheet.jpg", size)
    print(f"  stills -> {img_dir}\n  contact sheet -> {sheet}", file=sys.stderr)
    if images_only:
        print("images-only: look at the sheet, delete any still you want re-rolled "
              "(the cache is keyed by filename), then run again.", file=sys.stderr)
        return sheet

    mixed = work_dir / "audio_mixed.wav"
    mix_audio(voice_wav, total_dur, mixed, music_track=spec.get("music") and (NS_ROOT / spec["music"]),
              work_dir=work_dir, music_db=spec.get("music_db", MUSIC_DB))

    bg = work_dir / "bg.mp4"
    build_bg_chain(images, bg, work_dir, size, xfade=xfade)
    capped = work_dir / "capped.mp4"
    overlay_captions(bg, caption_chunks(infos), capped, work_dir, total_dur, size, logo_w,
                     batch=batch)

    out_dir = spec_dir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_final = out_dir / f"{slug}.mp4"
    r = subprocess.run(["ffmpeg", "-y", "-i", str(capped), "-i", str(mixed),
                        "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
                        "-b:a", "192k", "-shortest", str(out_final)], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"mux FAIL: {r.stderr[-2000:]}")
    print(f"done -> {out_final}  ({total_dur:.1f}s)", file=sys.stderr)
    return out_final


def main():
    args = sys.argv[1:]
    if "--spec" not in args:
        sys.exit("usage: build_retelling.py --spec <script.json> "
                 "[--dry-run|--voice-only|--images-only] [--batch N]")
    spec_path = args[args.index("--spec") + 1]
    if "--dry-run" in args:
        dry_run(load_spec(spec_path))
        return
    batch = int(args[args.index("--batch") + 1]) if "--batch" in args else 40
    build(spec_path, batch=batch, voice_only="--voice-only" in args,
          images_only="--images-only" in args)


if __name__ == "__main__":
    main()
