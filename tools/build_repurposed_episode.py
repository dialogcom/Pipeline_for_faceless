#!/usr/bin/env python3
"""
build_repurposed_episode.py — render ONE episode of a repurposed-long-recording series
(see .claude/skills/repurpose-recording, media/projects/<slug>/{transcript,episodes,
interrupts}.json).

Per episode: crop/zoom the source into a tight vertical frame, burn word-synced captions
from the transcript over the speaker's own audio, then append a voiced "bridge" bumper
(Inworld TTS, default Nikolai — a deliberately DIFFERENT voice from the speaker's own, so
it reads as an added editorial layer, never a fake reproduction of her voice) with a
centered text card, that asks/teases the interrupt line and holds until it's spoken.

Usage:
  python tools/build_repurposed_episode.py --project rossienko-talk --episode 1
  python tools/build_repurposed_episode.py --project rossienko-talk --episode 1 --no-bumper

Needs INWORLD_API_KEY in .env (bumper voice). ffmpeg/ffprobe on PATH.
"""
import argparse
import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_voice_inworld import tts_with_timestamps  # noqa: E402
from build_narrated_short import make_logo_chip  # noqa: E402
import frame_shots  # noqa: E402

W, H, FPS = 1080, 1920, 30
# Default crop rect, measured against rossienko-talk's 720x1280 source — tight talking-head
# framing, confirmed against frames at 1200s/2400s. A project overrides it (or switches to
# per-shot auto framing) with its own media/projects/<slug>/framing.json:
#   {"mode": "fixed", "crop": {"w":.., "h":.., "x":.., "y":..}}
#   {"mode": "auto_pillarbox", "band_offset_y": -150}   # mixed-aspect assembled footage
CROP = dict(w=349, h=620, x=215, y=474)
LOGO_PATH = ROOT / "media/projects/uka-bird/logo-bird.png"
MUSIC_BED = ROOT / "media/library/music/clips/ambient-pad.mp3"  # meditation-bells wanted but
# ElevenLabs key lacks music_generation scope (2026-08-11) — ambient-pad is the closest existing
# library bed (calm/minimal/no-drums); swap once a real bell bed can be generated.
MUSIC_GAIN_DB = -26  # "негромко" — sits well under both her voice and the bumper narrator

FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
FONT = ImageFont.truetype(FONT_PATH, 46)
FONT_BUMPER = ImageFont.truetype(FONT_PATH, 56)


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"FAIL: {' '.join(str(c) for c in cmd)}\n{r.stderr[-2500:]}")
    return r.stdout


def wrap_words(text, width=26):
    return textwrap.wrap(text, width=width, break_long_words=False) or [text]


def make_caption_png(text, out_path):
    """Bottom-anchored caption, sized to sit in the blurred pad below the tight face crop."""
    lines = wrap_words(text.strip())
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    line_h = 58
    total_h = line_h * len(lines)
    y0 = H - 340 - total_h
    max_w = max(d.textlength(l, font=FONT) for l in lines)
    pad_x, pad_y = 40, 22
    box = [(W - max_w) / 2 - pad_x, y0 - pad_y, (W + max_w) / 2 + pad_x, y0 + total_h + pad_y]
    d.rounded_rectangle(box, radius=16, fill=(0, 0, 0, 150))
    for i, line in enumerate(lines):
        lw = d.textlength(line, font=FONT)
        d.text(((W - lw) / 2, y0 + i * line_h), line, font=FONT, fill=(255, 255, 255, 255),
               stroke_width=2, stroke_fill=(0, 0, 0, 220))
    im.save(out_path)


def make_bumper_card(text, out_path):
    """Full-bleed dark card with the bridge question, centered."""
    lines = wrap_words(text.strip(), width=20)
    im = Image.new("RGBA", (W, H), (10, 8, 16, 235))
    d = ImageDraw.Draw(im)
    line_h = 72
    total_h = line_h * len(lines)
    y0 = (H - total_h) // 2
    for i, line in enumerate(lines):
        lw = d.textlength(line, font=FONT_BUMPER)
        d.text(((W - lw) / 2, y0 + i * line_h), line, font=FONT_BUMPER, fill=(255, 235, 200, 255),
               stroke_width=3, stroke_fill=(0, 0, 0, 200))
    im.save(out_path)


def chunk_words(words, max_words=6):
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        if any(w["w"].rstrip('"»').endswith(p) for p in (".", "?", "!", "...")) or len(cur) >= max_words:
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


def crop_filter(crop=CROP):
    return (f"crop={crop['w']}:{crop['h']}:{crop['x']}:{crop['y']},"
            f"scale={W}:{H}:flags=lanczos,unsharp=5:5:0.6:5:5:0.0,setsar=1")


def probe_size(path):
    out = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
               "stream=width,height", "-of", "csv=p=0:s=x", str(path)])
    w, h = out.strip().split("x")[:2]
    return int(w), int(h)


def render_source_clip(src, start, dur, framing, out_path):
    """Step 1 for one episode: the source window, reframed into the vertical canvas, with
    the speaker's own audio kept as-is."""
    mode = framing.get("mode", "fixed")
    if mode == "auto_pillarbox":
        # Assembled footage changes aspect shot to shot; measure it and cut the frame per
        # run rather than forcing one rect on the whole series (see tools/frame_shots.py).
        sw, sh = probe_size(src)
        segs = frame_shots.plan_segments(src, start, dur, sw, sh,
                                         min_seg=framing.get("min_segment_sec", 1.2))
        filt = frame_shots.build_filter(
            segs, W, H, band_offset_y=framing.get("band_offset_y", -150),
            blur=framing.get("blur", 42), brightness=framing.get("brightness", -0.18),
            saturation=framing.get("saturation", 0.65), fps=FPS)
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
             "-i", str(src), "-filter_complex", filt, "-map", "[vout]", "-map", "0:a",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
             "-c:a", "aac", "-b:a", "160k", str(out_path)])
        return segs
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(src),
         "-vf", crop_filter(framing.get("crop", CROP)), "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "18", "-c:a", "aac", "-b:a", "160k", str(out_path)])
    return None


def probe_duration(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", str(path)])
    return float(out.strip())


def apply_overlays(in_path, overlays, proj_dir, out_path):
    """Blend short, semi-transparent B-roll clips over the talking-head video during
    specific windows — thematically matched stock footage (see overlays.json), time-
    stretched to exactly fill its window so there's no visible loop seam."""
    inputs = ["-i", str(in_path)]
    filt = []
    last = "0:v"
    for i, o in enumerate(overlays):
        clip = proj_dir / o["clip"]
        window = o["end"] - o["start"]
        clip_dur = probe_duration(clip)
        factor = window / clip_dur
        inputs += ["-i", str(clip)]
        idx = i + 1
        fade_out_st = max(0.0, window - 0.5) + o["start"]
        vf = (f"[{idx}:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
              f"setpts={factor:.5f}*PTS+{o['start']:.3f}/TB,format=rgba,"
              f"colorchannelmixer=aa={o['opacity']},"
              f"fade=t=in:st={o['start']:.3f}:d=0.5:alpha=1,"
              f"fade=t=out:st={fade_out_st:.3f}:d=0.5:alpha=1[ov{i}]")
        filt.append(vf)
        out_l = f"v{idx}"
        filt.append(f"[{last}][ov{i}]overlay=0:0:enable='between(t,{o['start']:.3f},{o['end']:.3f})'[{out_l}]")
        last = out_l
    run(["ffmpeg", "-y", "-v", "error"] + inputs + ["-filter_complex", ";".join(filt),
         "-map", f"[{last}]", "-map", "0:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-c:a", "aac", "-b:a", "160k", str(out_path)])


def add_logo(in_path, out_path, total_dur):
    """Persistent translucent-chip corner logo, same treatment as narrated-shorts
    (feedback_vox_petya_corner_logo: must clear the bottom-anchored caption band)."""
    work = out_path.parent
    logo_chip = work / "logo_chip.png"
    make_logo_chip(logo_chip)
    run(["ffmpeg", "-y", "-v", "error", "-i", str(in_path), "-loop", "1", "-t", f"{total_dur:.3f}",
         "-i", str(logo_chip), "-filter_complex",
         "[1:v]fade=t=in:st=0:d=0.8:alpha=1[logofade];[0:v][logofade]overlay=48:56[v]",
         "-map", "[v]", "-map", "0:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-c:a", "aac", "-b:a", "160k", str(out_path)])


def add_music_bed(in_path, out_path, total_dur):
    """Quiet looped music bed mixed under the existing audio (speaker + bumper narrator).
    See MUSIC_BED note: wanted meditation bells, fell back to ambient-pad (API scope)."""
    work = out_path.parent
    voice_wav = work / "orig_audio.wav"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(in_path), "-vn", "-ar", "44100", "-ac", "2", str(voice_wav)])
    music_wav = work / "music.wav"
    fade_out_st = max(0.1, total_dur - 3)
    run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", str(MUSIC_BED), "-t", f"{total_dur:.3f}",
         "-af", f"volume={MUSIC_GAIN_DB}dB,afade=t=in:st=0:d=2,afade=t=out:st={fade_out_st:.3f}:d=3",
         "-ar", "44100", "-ac", "2", str(music_wav)])
    mixed_wav = work / "mixed_audio.wav"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(voice_wav), "-i", str(music_wav), "-filter_complex",
         "[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=0,volume=1.4",
         "-ar", "44100", "-ac", "2", str(mixed_wav)])
    run(["ffmpeg", "-y", "-v", "error", "-i", str(in_path), "-i", str(mixed_wav), "-map", "0:v", "-map", "1:a",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", str(out_path)])


def build_episode(proj_dir: Path, ep_index: int, use_bumper: bool, use_logo: bool, use_music: bool):
    transcript = json.loads((proj_dir / "transcript.json").read_text(encoding="utf-8"))
    episodes = json.loads((proj_dir / "episodes.json").read_text(encoding="utf-8"))["episodes"]
    interrupts = {i["after_episode"]: i["text"] for i in
                  json.loads((proj_dir / "interrupts.json").read_text(encoding="utf-8"))}
    # Stretches where the source shows its own full-screen text (quote cards, titles) and
    # our word-synced captions would just say the same thing twice, in two typefaces.
    mute_path = proj_dir / "caption_mute.json"
    mutes = json.loads(mute_path.read_text(encoding="utf-8")) if mute_path.exists() else []
    framing_path = proj_dir / "framing.json"
    framing = json.loads(framing_path.read_text(encoding="utf-8")) if framing_path.exists() else {}
    overlays_path = proj_dir / "overlays.json"
    all_overlays = json.loads(overlays_path.read_text(encoding="utf-8")) if overlays_path.exists() else {}
    ep_overlays = all_overlays.get(str(ep_index), [])
    src = ROOT / transcript["source"]

    ep = next(e for e in episodes if e["index"] == ep_index)
    start, end = ep["start"], ep["end"]
    dur = end - start

    work = proj_dir / "output" / f"ep{ep_index:02d}_build"
    work.mkdir(parents=True, exist_ok=True)
    out_dir = proj_dir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. reframed clip, original speaker audio kept
    raw = work / "raw.mp4"
    segs = render_source_clip(src, start, dur, framing, raw)
    if segs:
        print(f"  framing: {len(segs)} segment(s) " +
              ", ".join(f"{s['crop']['w']}x{s['crop']['h']}" for s in segs))

    # 1b. optional semi-transparent B-roll overlays, before captions so captions stay on top
    base = raw
    if ep_overlays:
        overlaid = work / "overlaid.mp4"
        apply_overlays(raw, ep_overlays, proj_dir, overlaid)
        base = overlaid

    # 2. word-synced captions for this episode's speech, offset to clip-local time
    def muted(w):
        mid = (w["start"] + w["end"]) / 2
        return any(a <= mid <= b for a, b in mutes)

    ep_words = [{"w": w["w"], "start": w["start"] - start, "end": w["end"] - start}
                for w in transcript["words"] if start <= w["start"] < end and not muted(w)]
    chunks = chunk_words(ep_words) if ep_words else []
    caps_dir = work / "caps"
    caps_dir.mkdir(exist_ok=True)
    inputs = ["-i", str(base)]
    filt = []
    last = "0:v"
    for ci, chunk in enumerate(chunks):
        text = " ".join(w["w"] for w in chunk)
        cs, ce = max(0.0, chunk[0]["start"]), min(dur, chunk[-1]["end"])
        png = caps_dir / f"{ci:04d}.png"
        make_caption_png(text, png)
        inputs += ["-i", str(png)]
        idx = ci + 1
        out_l = f"v{idx}"
        filt.append(f"[{last}][{idx}:v]overlay=0:0:enable='between(t,{cs:.3f},{ce:.3f})'[{out_l}]")
        last = out_l
    captioned = work / "captioned.mp4"
    if filt:
        run(["ffmpeg", "-y", "-v", "error"] + inputs + ["-filter_complex", ";".join(filt),
             "-map", f"[{last}]", "-map", "0:a", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "18", "-c:a", "aac", "-b:a", "160k", str(captioned)])
    else:
        captioned = base   # every word in this episode is inside a caption-mute range

    result = captioned
    total_dur = dur

    if use_bumper and ep_index in interrupts:
        # 3. bumper: Inworld TTS bridge line + centered text card
        bridge_text = interrupts[ep_index]
        audio, words, bumper_dur = tts_with_timestamps(bridge_text, voice_id="Nikolai",
                                                         model="inworld-tts-1.5-max")
        bumper_mp3 = work / "bumper.mp3"
        bumper_mp3.write_bytes(audio)
        card_png = work / "card.png"
        make_bumper_card(bridge_text, card_png)
        hold = bumper_dur + 0.6
        bumper_mp4 = work / "bumper.mp4"
        run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-t", f"{hold:.3f}", "-i", str(card_png),
             "-i", str(bumper_mp3), "-vf", f"fade=t=in:st=0:d=0.25,fps={FPS}",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "160k", "-shortest", str(bumper_mp4)])

        # 4. concat episode + bumper — filter_complex concat (not the concat demuxer: re-encoding
        # two independently-timestamped mp4s through "-f concat" produced DTS discontinuities
        # that silently dropped the whole bumper segment; concat as a filter resets PTS itself)
        concatenated = work / "concatenated.mp4"
        run(["ffmpeg", "-y", "-v", "error", "-i", str(captioned), "-i", str(bumper_mp4),
             "-filter_complex", "[0:v:0][0:a:0][1:v:0][1:a:0]concat=n=2:v=1:a=1[outv][outa]",
             "-map", "[outv]", "-map", "[outa]",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "160k",
             str(concatenated)])
        result = concatenated
        total_dur = dur + hold

    if use_logo:
        logo_out = work / "logo.mp4"
        add_logo(result, logo_out, total_dur)
        result = logo_out

    if use_music:
        music_out = work / "music.mp4"
        add_music_bed(result, music_out, total_dur)
        result = music_out

    final = out_dir / f"ep{ep_index:02d}.mp4"
    result.replace(final)
    print(f"episode {ep_index} -> {final}  (total {total_dur:.1f}s, "
          f"overlays={len(ep_overlays)}, logo={use_logo}, music={use_music})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True, help="media/projects/<name>")
    ap.add_argument("--episode", type=int, required=True)
    ap.add_argument("--no-bumper", action="store_true")
    ap.add_argument("--no-logo", action="store_true")
    ap.add_argument("--no-music", action="store_true")
    args = ap.parse_args()
    proj_dir = ROOT / "media/projects" / args.project
    build_episode(proj_dir, args.episode, not args.no_bumper, not args.no_logo, not args.no_music)


if __name__ == "__main__":
    main()
