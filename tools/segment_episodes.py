#!/usr/bin/env python3
"""
segment_episodes.py — walk a word-timestamped transcript.json and propose cut points
for a serialized run of ~TARGET_SEC episodes, snapped to the nearest sentence-ending
word (., !, ?, ...) inside [MIN_SEC, MAX_SEC] of the running episode start. Falls back
to a comma, then to a hard cut at MAX_SEC, if no sentence end is in range.

Usage:
  python tools/segment_episodes.py --transcript media/projects/rossienko-talk/transcript.json \
      --out media/projects/rossienko-talk/episodes.json
"""
import argparse
import json
import re

TARGET_SEC = 52.0
MIN_SEC = 40.0
MAX_SEC = 70.0
# Defaults suit a talking-head recording where the bumper is the only thing appended.
# Sources that must land inside a hard platform cap (YouTube Shorts) pass --min/--max.

SENTENCE_END = re.compile(r'[.!?…]"?$')
COMMA_END = re.compile(r',"?$')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--transcript", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--min", type=float, default=MIN_SEC, dest="min_sec")
    ap.add_argument("--max", type=float, default=MAX_SEC, dest="max_sec")
    ap.add_argument("--floor", type=float, default=None,
                    help="episodes shorter than this are merged into a neighbour (default max/3)")
    ap.add_argument("--lead", type=float, default=0.6, help="seconds of pre-roll before the first word")
    ap.add_argument("--tail", type=float, default=1.0, help="seconds held after the last word")
    args = ap.parse_args()
    min_sec, max_sec = args.min_sec, args.max_sec
    floor = args.floor if args.floor is not None else max_sec / 3.0

    data = json.load(open(args.transcript, encoding="utf-8"))
    words = data["words"]

    episodes = []
    ep_start_idx = 0
    ep_start_t = words[0]["start"]

    i = 0
    n = len(words)
    while ep_start_idx < n:
        # search window for a cut point
        best_cut = None  # index of last word to include
        best_comma = None
        j = ep_start_idx
        while j < n and words[j]["end"] - ep_start_t <= max_sec:
            elapsed = words[j]["end"] - ep_start_t
            if elapsed >= min_sec and SENTENCE_END.search(words[j]["w"]):
                best_cut = j
            if elapsed >= min_sec and best_comma is None and COMMA_END.search(words[j]["w"]):
                best_comma = j
            j += 1

        if best_cut is None:
            # no sentence end in [min,max] window — prefer a comma, else hard cut at MAX
            if best_comma is not None:
                best_cut = best_comma
            else:
                # hard cut at the last word before exceeding max_sec (or single overlong word)
                best_cut = j - 1 if j > ep_start_idx else ep_start_idx

        ep_words = words[ep_start_idx:best_cut + 1]
        episodes.append({
            "index": len(episodes) + 1,
            "start": round(ep_words[0]["start"], 2),
            "end": round(ep_words[-1]["end"], 2),
            "text": " ".join(w["w"] for w in ep_words),
        })
        ep_start_idx = best_cut + 1
        if ep_start_idx < n:
            ep_start_t = words[ep_start_idx]["start"]

    # --- post-pass 1: absorb runt episodes ------------------------------------------
    # A cut can strand a fragment — a lone word before a long silent stretch, or a short
    # closing sentence. Fold each runt into whichever neighbour it actually abuts (the
    # smaller gap), as long as the merge stays inside a slack-extended max.
    hard_max = max_sec * 1.3
    merged = True
    while merged and len(episodes) > 1:
        merged = False
        for k, ep in enumerate(episodes):
            if ep["end"] - ep["start"] >= floor:
                continue
            prev_gap = ep["start"] - episodes[k - 1]["end"] if k > 0 else float("inf")
            next_gap = episodes[k + 1]["start"] - ep["end"] if k + 1 < len(episodes) else float("inf")
            order = [k - 1, k + 1] if prev_gap <= next_gap else [k + 1, k - 1]
            for nb in order:
                if not (0 <= nb < len(episodes)):
                    continue
                a, b = (episodes[nb], ep) if nb < k else (ep, episodes[nb])
                if b["end"] - a["start"] > hard_max:
                    continue
                a["end"] = b["end"]
                a["start"] = a["start"]
                a["text"] = (a["text"] + " " + b["text"]).strip()
                episodes.pop(k)
                merged = True
                break
            if merged:
                break
    for k, ep in enumerate(episodes):
        ep["index"] = k + 1

    # --- post-pass 2: breathing room -------------------------------------------------
    # Word boundaries are tight to the syllable; starting exactly on the first word clips
    # its attack and ending on the last one cuts the thought off. Borrow from the silence
    # on either side, never from a neighbouring episode.
    for k, ep in enumerate(episodes):
        floor_t = episodes[k - 1]["end"] if k > 0 else 0.0
        ceil_t = episodes[k + 1]["start"] if k + 1 < len(episodes) else data["duration_sec"]
        ep["start"] = round(max(floor_t, ep["start"] - args.lead), 2)
        ep["end"] = round(min(ceil_t, ep["end"] + args.tail), 2)

    out = {"source_duration_sec": data["duration_sec"], "episode_count": len(episodes),
           "episodes": episodes}
    json.dump(out, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    durs = [e["end"] - e["start"] for e in episodes]
    print(f"{len(episodes)} episodes, duration {min(durs):.1f}-{max(durs):.1f}s "
          f"(avg {sum(durs)/len(durs):.1f}s) -> {args.out}")


if __name__ == "__main__":
    main()
