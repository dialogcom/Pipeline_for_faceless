#!/usr/bin/env python3
"""
vo_from_recording.py — build a shot's vo.gen.ts from a LIVE one-take voice recording.

gen_voice.py works front-to-back: it synthesises each VO line on its own and drops it at
the start time the script asked for. A live take is one continuous file, so the timings
have to travel the other way — out of the audio and into the captions.

This tool takes the recorded file, gets word-exact timings for it from tools/transcribe.py
(ElevenLabs Scribe), aligns those spoken words against the shot's AUTHORED line texts (so
the captions keep the wording and punctuation that was written, not whatever the recognizer
heard), and writes vo.gen.ts with the real times. Words the recognizer missed or split are
interpolated between their nearest anchored neighbours, so a line never loses words.

The authored lines come from --lines-from (a vo.gen.ts, a beats.json, or a plain .txt with
one line per VoLine). With no --lines-from, the vo.gen.ts being overwritten is read first
and its own texts are reused — the usual case when only the voice changed.

Usage:
  # transcribe the take and rewrite the shot's vo.gen.ts against its existing line texts
  python tools/vo_from_recording.py --audio voice/short-25-take3.wav \
      --emit-ts remotion/src/shots/short-25/vo.gen.ts

  # same, but line texts come from a script file, and mux the take onto a finished render
  python tools/vo_from_recording.py --audio voice/short-26.wav \
      --lines-from shorts/short-26-aphorism-mountain/script.txt \
      --emit-ts remotion/src/shots/short-26/vo.gen.ts \
      --mux remotion/out/Short26Mountain.mp4

  python tools/vo_from_recording.py --audio ... --emit-ts ... --dry-run   # report only

Transcription is cached next to the audio as <audio>.words.json; re-runs are free unless
--force-stt is passed. `--stt elevenlabs` (default) needs ELEVENLABS_API_KEY in .env;
`--stt local` runs faster-whisper offline instead — no key, no quota, a bit less accurate.
ffmpeg/ffprobe on PATH either way. Timings are never tempo-shifted: the file you transcribe is the file you mux.
"""
import argparse
import difflib
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAP_WARN = 1.5      # inter-line silence that reads as a "dead air" retention cliff
COVER_WARN = 0.75   # per-line share of words anchored to a real recognised word


def run(cmd):
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if r.returncode != 0:
        sys.exit(f"command failed: {' '.join(cmd)}\n{r.stdout}")
    return r.stdout


def probe_duration(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", path])
    return float(out.strip())


# ---------------------------------------------------------------- authored lines

def unescape_ts(s):
    return s.replace("\\\\", "\x00").replace("\\'", "'").replace("\x00", "\\")


def lines_from_vo_gen(path):
    """Pull the `text:` field out of every VoLine in an existing vo.gen.ts."""
    src = open(path, encoding="utf-8").read()
    return [unescape_ts(m) for m in re.findall(r"\{\s*text:\s*'((?:[^'\\]|\\.)*)'", src)]


def lines_from_beats(path):
    beats = json.load(open(path, encoding="utf-8"))
    return [l["text"] for l in beats["vo"]]


def load_lines(path):
    if path.endswith(".ts") or path.endswith(".tsx"):
        return lines_from_vo_gen(path)
    if path.endswith(".json"):
        return lines_from_beats(path)
    return [l.strip() for l in open(path, encoding="utf-8") if l.strip()]


# ---------------------------------------------------------------- transcription

def transcribe(audio, cache, force, engine, model):
    """Word timings for the take, cached next to the audio.

    Either recogniser will do — they write the same transcript.json — so this only picks
    which script to shell out to. Scribe is the more accurate; `local` (faster-whisper) is
    the offline/no-quota route."""
    if os.path.exists(cache) and not force:
        print(f"using cached word timings: {os.path.relpath(cache, ROOT)}  (--force-stt to redo)")
    else:
        print(f"transcribing {os.path.relpath(audio, ROOT)} via {engine} ...")
        if engine == "local":
            cmd = [sys.executable, os.path.join(ROOT, "tools", "transcribe_local.py"),
                   "--in", audio, "--out", cache, "--no-vad"]
            if model:
                cmd += ["--model", model]
        else:
            cmd = [sys.executable, os.path.join(ROOT, "tools", "transcribe.py"),
                   "--in", audio, "--out", cache]
        run(cmd)
    data = json.load(open(cache, encoding="utf-8"))
    if data.get("engine"):
        print(f"  recogniser: {data['engine']}")
    return [w for w in data["words"] if w.get("w")]


# ---------------------------------------------------------------- alignment

def key(tok):
    """Comparison form: case/ё/punctuation-insensitive. '' = nothing to match on (e.g. '—')."""
    t = tok.lower().replace("ё", "е")
    return re.sub(r"[^0-9a-zа-я\-]", "", t).strip("-")


def weight(tok):
    """Share of a silent gap this token should get — mirrors timeWords() in lib/shorts.tsx."""
    return max(2, len(re.sub(r"[^0-9A-Za-zА-Яа-яЁё]", "", tok))) + 1.6


def anchor(script_toks, heard):
    """Map script-token index -> heard-word index, order-preserving, best-effort.

    Punctuation-only tokens carry no key and are excluded from the match entirely — left in
    they would happily pair '—' with '—' across half the script and drag the alignment with
    them."""
    s_idx = [i for i, t in enumerate(script_toks) if key(t)]
    h_idx = [j for j, w in enumerate(heard) if key(w["w"])]
    s_keys = [key(script_toks[i]) for i in s_idx]
    h_keys = [key(heard[j]["w"]) for j in h_idx]
    # autojunk would treat common short words ("не", "в") as noise on a long take
    sm = difflib.SequenceMatcher(None, s_keys, h_keys, autojunk=False)
    out = {}
    for i, j, n in sm.get_matching_blocks():
        for k in range(n):
            out[s_idx[i + k]] = h_idx[j + k]
    return out


def time_tokens(script_toks, heard, anchors, audio_dur, starts_line):
    """Give every script token a (start, end), interpolating whatever wasn't anchored."""
    if not anchors:
        sys.exit("alignment failed: not one script word was recognised in the recording.\n"
                 "  Check that --audio is the right take and --lines-from the right script.")

    times = [None] * len(script_toks)
    for i, j in anchors.items():
        times[i] = [heard[j]["start"], heard[j]["end"]]

    # seconds per unit of weight, measured on the words we DID hear — used to size the
    # runs that fall outside the anchored span (before the first / after the last anchor)
    aw = sum(weight(script_toks[i]) for i in anchors)
    ad = sum(max(0.0, times[i][1] - times[i][0]) for i in anchors)
    rate = (ad / aw) if aw and ad else 0.06

    def spread(run_idx, t0, t1):
        ws = [weight(script_toks[i]) for i in run_idx]
        total = sum(ws) or 1.0
        span = max(0.0, t1 - t0)
        t = t0
        for i, w in zip(run_idx, ws):
            d = span * w / total
            times[i] = [t, t + d]
            t += d

    known = sorted(anchors)
    first, last = known[0], known[-1]

    lead = list(range(0, first))
    if lead:
        est = sum(weight(script_toks[i]) for i in lead) * rate
        spread(lead, max(0.0, times[first][0] - est), times[first][0])

    for a, b in zip(known, known[1:]):
        gap = list(range(a + 1, b))
        if not gap:
            continue
        t0, t1 = times[a][1], max(times[a][1], times[b][0])
        est = [weight(script_toks[i]) * rate for i in gap]
        if t1 - t0 <= sum(est):
            spread(gap, t0, t1)
            continue
        # The gap is longer than these words could plausibly fill, so part of it is real
        # silence. Handing the slack to the words would park a caption on screen through the
        # pause; it belongs at the seam — before the word that opens the next line, or after
        # the run when the pause sits mid-line.
        seam = next((k for k, i in enumerate(gap) if starts_line[i]), len(gap))
        t = t0
        for k in range(seam):
            times[gap[k]] = [t, t + est[k]]
            t += est[k]
        t = t1
        for k in range(len(gap) - 1, seam - 1, -1):
            times[gap[k]] = [t - est[k], t]
            t -= est[k]

    tail = list(range(last + 1, len(script_toks)))
    if tail:
        est = sum(weight(script_toks[i]) for i in tail) * rate
        end = times[last][1] + est
        if audio_dur:
            end = min(end, audio_dur)
        spread(tail, times[last][1], max(times[last][1], end))

    # a caption that starts before the previous one ended reads as a stutter
    prev = 0.0
    for t in times:
        t[0] = max(t[0], prev)
        t[1] = max(t[1], t[0])
        prev = t[1]
    return times


# ---------------------------------------------------------------- emit

def emit_ts(vo, path):
    """Same VoLine module shape gen_voice.py writes — only the provenance line differs."""
    out = ["// AUTO-GENERATED by tools/vo_from_recording.py — do not edit.",
           "// Word times are the REAL Scribe alignment of the live take; captions sync exactly.",
           "import type { VoLine } from '../../lib/shorts';", "",
           "export const VO: VoLine[] = ["]
    for line in vo:
        esc = line["text"].replace("\\", "\\\\").replace("'", "\\'")
        ws = ", ".join(
            "{ w: '%s', start: %s, end: %s }" % (w["w"].replace("\\", "\\\\").replace("'", "\\'"),
                                                 w["start"], w["end"])
            for w in line["words"])
        out.append(f"  {{ text: '{esc}', start: {line['start']}, end: {line['end']}, words: [{ws}] }},")
    out += ["];", ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True, help="the recorded one-take VO file")
    ap.add_argument("--emit-ts", required=True, help="vo.gen.ts to write, e.g. remotion/src/shots/short-25/vo.gen.ts")
    ap.add_argument("--lines-from", help="authored line texts: a vo.gen.ts, a beats.json, or a "
                                         "one-line-per-VoLine .txt (default: the --emit-ts file itself)")
    ap.add_argument("--words-json", help="word-timing cache path (default: <audio>.words.json)")
    ap.add_argument("--stt", choices=["elevenlabs", "local"], default="elevenlabs",
                    help="recogniser: elevenlabs (Scribe, default) or local (faster-whisper, offline/free)")
    ap.add_argument("--stt-model", help="model for --stt local (default: transcribe_local.py's)")
    ap.add_argument("--offset", type=float, default=0.0, help="shift every time by N seconds")
    ap.add_argument("--fps", type=float, default=30.0, help="fps for the reported cue frames")
    ap.add_argument("--gap-warn", type=float, default=GAP_WARN, help=f"flag silences over N sec (default {GAP_WARN})")
    ap.add_argument("--voice-out", help="also write a loudnorm'd 44.1k stereo wav of the take here")
    ap.add_argument("--mux", help="rendered mp4 to mux the take onto (-voiced.mp4)")
    ap.add_argument("--force-stt", action="store_true", help="re-transcribe even if the cache exists")
    ap.add_argument("--dry-run", action="store_true", help="report the alignment, write nothing")
    args = ap.parse_args()

    audio = os.path.abspath(args.audio)
    if not os.path.exists(audio):
        sys.exit(f"no such recording: {args.audio}")
    ts_path = os.path.abspath(args.emit_ts)

    src = os.path.abspath(args.lines_from) if args.lines_from else ts_path
    if not os.path.exists(src):
        sys.exit(f"no authored line texts to align against: {os.path.relpath(src, ROOT)}\n"
                 "  pass --lines-from with the script (vo.gen.ts / beats.json / .txt)")
    lines = load_lines(src)
    if not lines:
        sys.exit(f"no line texts found in {os.path.relpath(src, ROOT)}")

    audio_dur = probe_duration(audio)
    heard = transcribe(audio, args.words_json or audio + ".words.json", args.force_stt,
                       args.stt, args.stt_model)
    print(f"take: {audio_dur:.2f}s, {len(heard)} words heard | script: {len(lines)} lines, "
          f"{sum(len(l.split()) for l in lines)} words (from {os.path.relpath(src, ROOT)})\n")

    # flatten to tokens, remembering which line each came from
    toks, owner = [], []
    for n, line in enumerate(lines):
        for t in line.split():
            toks.append(t)
            owner.append(n)

    anchors = anchor(toks, heard)
    starts_line = [i == 0 or owner[i] != owner[i - 1] for i in range(len(toks))]
    times = time_tokens(toks, heard, anchors, audio_dur, starts_line)

    vo = []
    for n, text in enumerate(lines):
        idx = [i for i in range(len(toks)) if owner[i] == n]
        words = [{"w": toks[i], "start": round(times[i][0] + args.offset, 3),
                  "end": round(times[i][1] + args.offset, 3)} for i in idx]
        vo.append({"text": text, "start": round(words[0]["start"], 2),
                   "end": round(words[-1]["end"], 2), "words": words,
                   "_hit": sum(1 for i in idx if i in anchors), "_n": len(idx)})

    print(f"{'line':>4s} {'start':>7s} {'end':>7s} {'gap':>6s} {'@f':>6s}  anchored  text")
    worst_gap = 0.0
    for n, line in enumerate(vo):
        gap = line["start"] - vo[n - 1]["end"] if n else line["start"]
        worst_gap = max(worst_gap, gap)
        cover = line["_hit"] / line["_n"]
        flag = ""
        if gap > args.gap_warn:
            flag += "  <-- LONG PAUSE"
        if cover < COVER_WARN:
            flag += "  <-- LOW MATCH"
        print(f"{n:4d} {line['start']:7.2f} {line['end']:7.2f} {gap:6.2f} "
              f"{round(line['start'] * args.fps):6d}  {line['_hit']:3d}/{line['_n']:<3d}  "
              f"{line['text'][:44]}{flag}")

    total_hit = sum(l["_hit"] for l in vo)
    total_n = sum(l["_n"] for l in vo)
    print(f"\nanchored {total_hit}/{total_n} script words ({total_hit / total_n:.0%}); "
          f"longest silence before a line {worst_gap:.2f}s")

    # words the recogniser heard that no caption claims — usually an ad-lib worth writing down
    used = set(anchors.values())
    stray, runs = [], []
    for j, w in enumerate(heard):
        if j in used:
            if len(stray) >= 4:
                runs.append(stray)
            stray = []
        else:
            stray.append(w["w"])
    if len(stray) >= 4:
        runs.append(stray)
    for r in runs:
        print(f"  heard but not captioned ({len(r)} words): {' '.join(r)[:100]}")
    if worst_gap > args.gap_warn:
        print(f"  a silence over {args.gap_warn}s is what sank short-23/24 — consider a retake "
              f"or trimming it in the audio before muxing")
    if total_hit / total_n < COVER_WARN:
        print("  low overall match: the take and the script have drifted apart — captions would "
              "be interpolated guesses, not real timings")

    print(f"\nsuggested composition duration: {audio_dur + 0.8:.1f}s "
          f"({round((audio_dur + 0.8) * args.fps)} frames @ {args.fps:g}fps)")

    for l in vo:
        del l["_hit"], l["_n"]

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return

    emit_ts(vo, ts_path)
    print(f"\nVO TS module -> {os.path.relpath(ts_path, ROOT)}")

    voice = audio
    if args.voice_out:
        voice = os.path.abspath(args.voice_out)
        os.makedirs(os.path.dirname(voice), exist_ok=True)
        run(["ffmpeg", "-y", "-v", "error", "-i", audio,
             "-filter:a", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "44100", "-ac", "2", voice])
        print(f"voice track -> {os.path.relpath(voice, ROOT)}")

    if args.mux:
        out = os.path.splitext(args.mux)[0] + "-voiced.mp4"
        run(["ffmpeg", "-y", "-v", "error", "-i", args.mux, "-i", voice,
             "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", out])
        print(f"voiced preview -> {os.path.relpath(out, ROOT)}")


if __name__ == "__main__":
    main()
