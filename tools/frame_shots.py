#!/usr/bin/env python3
"""
frame_shots.py — per-shot reframing of a mixed-aspect source into a fixed vertical canvas.

repurpose-recording assumes one locked crop rect, which is right for a talking-head
recording and wrong for an assembled film: an archival documentary alternates 4:3 material
pillarboxed inside a 16:9 master with full-width title and quote cards. One rect either
wastes a quarter of the width on the archival shots or guillotines the text on the cards.

Approach: scan the episode's own frames (one decode pass, a few fps, downscaled to
luminance) and measure where the picture actually ends. Classify each sample as FULL or
PILLARBOXED by content width, smooth the class track, and turn it into runs; each run gets
one crop rect — the union of its samples, so nothing that is on screen anywhere in the run
gets cut. The runs become one filter_complex that trims, crops, scales and composites each
over a blurred copy of itself, concatenated frame-exactly in a single pass.

Scene-cut detection is deliberately NOT used: films of this vintage transition on dissolves,
and scdet finds almost nothing. Classifying the frames themselves also handles dissolves
correctly on its own — while a 4:3 shot dissolves into a full-width one the side padding is
already lit by the incoming image, so the measurement flips exactly when it should.

Used by build_repurposed_episode.py when the project carries a framing.json with
{"mode": "auto_pillarbox"}. Standalone, it prints the detected plan:

  python tools/frame_shots.py --src raw-footage/<slug>/source.mp4 --start 120 --dur 50
"""
import argparse
import subprocess
import sys

PROBE_W, PROBE_H = 192, 108   # luminance scan resolution; ~100x cheaper than full frames
PROBE_FPS = 4
DARK = 18                     # a column dimmer than this everywhere is padding, not picture
FULL_W = 0.90                 # content this wide counts as the full 16:9 master
MIN_W = 0.60                  # narrower than this is a dark frame, not a padded one:
                              # cropping to it would punch a wild zoom into a fade
SNAP = 8                      # keep crop rects on even, tidy pixel boundaries


def scan(src, start, dur):
    """Per-sample content boxes (normalised), None where the frame is black."""
    import numpy as np
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(src),
         "-an", "-vf", f"fps={PROBE_FPS},scale={PROBE_W}:{PROBE_H},format=gray",
         "-f", "rawvideo", "-"], capture_output=True)
    n = len(p.stdout) // (PROBE_W * PROBE_H)
    if n == 0:
        return []
    a = np.frombuffer(p.stdout[:n * PROBE_W * PROBE_H], dtype=np.uint8).reshape(n, PROBE_H, PROBE_W)
    boxes = []
    for i in range(n):
        f = a[i]
        cols = np.where(f.max(axis=0) > DARK)[0]
        rows = np.where(f.max(axis=1) > DARK)[0]
        if len(cols) == 0 or len(rows) == 0:
            boxes.append(None)           # fade or black card — no opinion, inherit a neighbour
        else:
            boxes.append((cols[0] / PROBE_W, (cols[-1] + 1) / PROBE_W,
                          rows[0] / PROBE_H, (rows[-1] + 1) / PROBE_H))
    return boxes


def _snap(v, lo, hi):
    return max(lo, min(hi, int(round(v / SNAP)) * SNAP))


def plan_segments(src, start, dur, width, height, min_seg=1.2):
    """[{t0, t1, crop}] over the episode, in episode-local seconds."""
    boxes = scan(src, start, dur)
    if not boxes:
        return [{"t0": 0.0, "t1": dur, "crop": dict(w=width, h=height, x=0, y=0)}]

    # Bucket each sample by WHERE the picture ends, not just whether it is full-width: a
    # run has to break when the framing actually changes, or the union of a long run drifts
    # wider than any single shot in it and we end up cropping to a rect nothing matches.
    def key(b):
        if b is None:
            return None
        w = b[1] - b[0]
        if w >= FULL_W or w < MIN_W:
            return "full"
        return (round(b[0] * 20), round(b[1] * 20))

    keys = [key(b) for b in boxes]
    last = next((k for k in keys if k is not None), "full")
    for i, k in enumerate(keys):
        if k is None:
            keys[i] = last          # black frames inherit the framing around them
        else:
            last = k

    runs = []
    for i, k in enumerate(keys):
        if runs and runs[-1]["key"] == k:
            runs[-1]["i1"] = i
        else:
            runs.append({"key": k, "i0": i, "i1": i})

    # a run under min_seg is a dissolve caught mid-way, not a shot worth re-framing for
    changed = True
    while changed and len(runs) > 1:
        changed = False
        for k, r in enumerate(runs):
            if (r["i1"] - r["i0"] + 1) / PROBE_FPS >= min_seg:
                continue
            # give it to whichever neighbour is longer, so brief flashes never win
            prev_len = runs[k - 1]["i1"] - runs[k - 1]["i0"] if k > 0 else -1
            next_len = runs[k + 1]["i1"] - runs[k + 1]["i0"] if k + 1 < len(runs) else -1
            nb = k - 1 if prev_len >= next_len else k + 1
            runs[nb]["i0"] = min(runs[nb]["i0"], r["i0"])
            runs[nb]["i1"] = max(runs[nb]["i1"], r["i1"])
            runs.pop(k)
            changed = True
            break

    def median(vals):
        v = sorted(vals)
        return v[len(v) // 2]

    segs = []
    for k, r in enumerate(runs):
        t0 = 0.0 if k == 0 else r["i0"] / PROBE_FPS
        t1 = dur if k == len(runs) - 1 else (r["i1"] + 1) / PROBE_FPS
        span = [b for b in boxes[r["i0"]:r["i1"] + 1] if b]
        # median, not union: an absorbed dissolve shouldn't widen the whole run's rect
        med_w = median([b[1] - b[0] for b in span]) if span else 1.0
        med_h = median([b[3] - b[2] for b in span]) if span else 1.0
        if not span or med_w >= FULL_W or med_w < MIN_W or med_h < MIN_W:
            crop = dict(w=width, h=height, x=0, y=0)
        else:
            px = _snap(median([b[0] for b in span]) * width, 0, width)
            py = _snap(median([b[2] for b in span]) * height, 0, height)
            pw = min(_snap(median([b[1] - b[0] for b in span]) * width, SNAP, width), width - px)
            ph = min(_snap(median([b[3] - b[2] for b in span]) * height, SNAP, height), height - py)
            crop = dict(w=pw, h=ph, x=px, y=py)
        if segs and segs[-1]["crop"] == crop:
            segs[-1]["t1"] = round(t1, 3)      # neighbours that frame alike stay one segment
        else:
            segs.append({"t0": round(t0, 3), "t1": round(t1, 3), "crop": crop})
    return segs


def build_filter(segments, out_w, out_h, band_offset_y=-150, blur=42,
                 brightness=-0.18, saturation=0.65, fps=30):
    """filter_complex placing each segment's content band, scaled to full canvas width, over
    a blurred cover-crop of itself. Band centres stay on one axis, so the picture grows and
    shrinks about a fixed point instead of sliding up the frame."""
    n = len(segments)
    parts = [f"[0:v]fps={fps},split={n}" + "".join(f"[src{i}]" for i in range(n))]
    for i, s in enumerate(segments):
        c = s["crop"]
        parts.append(
            f"[src{i}]trim={s['t0']:.3f}:{s['t1']:.3f},setpts=PTS-STARTPTS,"
            f"crop={c['w']}:{c['h']}:{c['x']}:{c['y']},split[b{i}][f{i}]")
        parts.append(
            f"[b{i}]scale=-2:{out_h}:force_original_aspect_ratio=increase,"
            f"crop={out_w}:{out_h}:(iw-{out_w})/2:(ih-{out_h})/2,"
            f"gblur=sigma={blur},eq=brightness={brightness}:saturation={saturation},"
            f"setsar=1[bg{i}]")
        parts.append(
            f"[f{i}]scale={out_w}:-2:flags=lanczos,unsharp=5:5:0.4:5:5:0.0,setsar=1[fg{i}]")
        parts.append(f"[bg{i}][fg{i}]overlay=0:(H-h)/2+({band_offset_y}),format=yuv420p[v{i}]")
    parts.append("".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vout]")
    return ";".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--start", type=float, required=True)
    ap.add_argument("--dur", type=float, required=True)
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    args = ap.parse_args()
    for s in plan_segments(args.src, args.start, args.dur, args.width, args.height):
        c = s["crop"]
        print(f"{s['t0']:6.2f}-{s['t1']:6.2f}  crop {c['w']}x{c['h']}+{c['x']}+{c['y']}"
              f"  -> band 1080x{round(1080 * c['h'] / c['w'])}")


if __name__ == "__main__":
    main()
