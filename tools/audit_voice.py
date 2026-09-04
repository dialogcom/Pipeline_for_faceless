#!/usr/bin/env python3
"""
audit_voice.py — score one draft against a voice profile. 100 points, deterministic.

The repo-native replacement for the video's "Auditor Gem in a fresh chat". The video needs a
second model because the first one grades its own homework generously; the fix here is
stronger — the part of the audit that can be counted *is* counted, against distributions
measured from the author's own corpus (analyze_voice.py), so it returns the same number for
the same text every time and points at the exact sentences that failed.

What it cannot do is judge meaning: whether a claim is invented, whether the story lands,
whether a metaphor is the author's or a stock one. That half stays with a reader working
from voice-profiles/reference/RUBRIC.md in a clean context (see the audit-voice skill).

Usage:
  python tools/audit_voice.py --profile voice-profiles/uka-ru --text-file draft.txt
  python tools/audit_voice.py --profile voice-profiles/uka-ru --spec retellings/x/script.json
  python tools/audit_voice.py --profile voice-profiles/uka-ru --spec ... --json

Exit code 0 if the draft passes the gate (80 by default), 1 if not, so it can gate a build.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from voice_metrics import (  # noqa: E402
    connective_counts, doc_metrics, monotony_runs, repeated_ngrams, sentences, words,
)

BANNED = ROOT / "voice-profiles/reference/banned-patterns.json"
PASS_GATE = 80        # publish-ready
FLOOR_GATE = 70       # below this the draft goes back to the writer wholesale

# (metric, points, direction). "min" penalises only falling below p10 — writing with MORE
# rhythm or a richer vocabulary than the corpus is not a defect to be corrected downward.
# "band" penalises both sides, for the metrics where excess is itself the machine tell
# (triads, commas, mid-length uniformity).
WEIGHTS = [
    ("Ритм", [("wps_cv", 12, "min"), ("adj_delta", 9, "min"), ("short_share", 7, "band"),
              ("wps_mean", 4, "band")]),
    ("Словарь", [("ttr", 7, "min"), ("hapax_share", 5, "min"), ("word_len_mean", 3, "band"),
                 ("opener_diversity", 5, "min")]),
    ("Пунктуация", [("comma_per_100w", 5, "band"), ("question_share", 4, "band"),
                    ("colon_per_100w", 3, "band"), ("triad_per_100w", 3, "band")]),
]
MONOTONY_POINTS = 3
CONNECTIVE_POINTS = 10
BANNED_POINTS = 20


def band_score(value, band, points, direction="band"):
    """Full points inside p10..p90; linear decay to zero one band-width outside it.
    direction "min" treats anything above p90 as fine."""
    lo, hi = band["p10"], band["p90"]
    width = max(hi - lo, 1e-6)
    if value > hi and direction == "min":
        return points, "ok"
    if lo <= value <= hi:
        return points, "ok"
    dist = (lo - value) if value < lo else (value - hi)
    frac = max(0.0, 1.0 - dist / width)
    return points * frac, ("низко" if value < lo else "высоко")


def load_drafts(args):
    """Returns [(name, text), ...] — one entry per thing that is actually one piece of
    writing. A narrated-shorts scripts.json is a *series*: glueing its 17 episodes into one
    document would score the series' recurring teaser as self-repetition and average away
    every episode's own rhythm, so each episode is audited on its own. A retelling's beats
    are one continuous narration and stay joined."""
    if "--text-file" in args:
        p = Path(args[args.index("--text-file") + 1])
        return [(p.name, p.read_text(encoding="utf-8"))]
    if "--spec" in args:
        p = Path(args[args.index("--spec") + 1])
        spec = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(spec, list):   # narrated-shorts scripts.json — a series of episodes
            eps = [(f"{e.get('id', i)}-{e.get('slug', '')}",
                    " ".join(filter(None, [e.get("hook"), e.get("vo"), e.get("ending")])))
                   for i, e in enumerate(spec)]
            return [(f"{p.parent.name}/{n}", t) for n, t in eps]
        return [(spec.get("slug", p.name),
                 "\n".join(b.get("text", "") for b in spec.get("beats", [])))]
    if "--text" in args:
        return [("<stdin>", args[args.index("--text") + 1])]
    sys.exit("need --text-file, --spec or --text")


def audit(profile_dir, name, text):
    metrics = json.loads((Path(profile_dir) / "metrics.json").read_text(encoding="utf-8"))
    bands = metrics["bands"]
    text = text.replace("́", "")
    m = doc_metrics(text)
    sents = sentences(text)

    groups, flags, score = [], [], 0.0
    for gname, items in WEIGHTS:
        got = total = 0.0
        rows = []
        for key, pts, direction in items:
            s, verdict = band_score(m[key], bands[key], pts, direction)
            got += s
            total += pts
            rows.append({"metric": key, "value": round(m[key], 3),
                         "band": [round(bands[key]["p10"], 3), round(bands[key]["p90"], 3)],
                         "points": round(s, 1), "max": pts, "verdict": verdict})
            if verdict != "ok":
                flags.append(f"{key} = {m[key]:.3f}, профиль ожидает "
                             f"{bands[key]['p10']:.3f}-{bands[key]['p90']:.3f} ({verdict})")
        groups.append({"group": gname, "points": round(got, 1), "max": round(total, 1), "rows": rows})
        score += got

    # Monotony: the literal shape of flat LLM prose. Any run costs the whole sub-score and
    # names the sentences, because "make it less monotonous" is unactionable and
    # "sentences 4-8 are all 12-14 words" is not.
    runs = monotony_runs(text)
    score += MONOTONY_POINTS if not runs else 0.0
    for start, lens in runs:
        flags.append(f"монотонный ряд: предложения {start+1}-{start+len(lens)} длиной {lens} — "
                     f"«{sents[start][:70]}...»")

    # Connectives: does the draft reach for the same joins the author does? Scored on the
    # profile's top 12 markers, by presence rather than exact rate — a 600-word draft cannot
    # reproduce a 3700-word corpus's rates, but it can sound like it came from the same hand.
    top = [k for k, _ in list(metrics["connectives_per_1000w"].items())[:12]]
    used = connective_counts(text)
    hit = sum(1 for k in top if used.get(k, 0) > 0)
    conn_score = CONNECTIVE_POINTS * min(1.0, hit / max(1, min(len(top), 7)))
    score += conn_score
    if hit < 4:
        flags.append(f"связки: использовано {hit} из профильных {top[:8]} — текст не звучит как автор")

    # Banned patterns.
    cfg = json.loads(BANNED.read_text(encoding="utf-8"))
    hits, hard = [], False
    for pat in cfg["patterns"]:
        found = re.findall(pat["re"], text, re.I | re.U)
        if found:
            hits.append({"id": pat["id"], "severity": pat["severity"], "count": len(found),
                         "label": pat["label"], "sample": str(found[0])[:60]})
            if pat["severity"] == "hard":
                hard = True
            flags.append(f"[{pat['severity']}] {pat['id']}: {pat['label']} (×{len(found)})")
    # Self-repetition inside the draft is the same failure the video calls "повторяющиеся
    # тройные паттерны": the model reusing its own phrasing.
    rep = repeated_ngrams(text, 3, 2)
    for g, c in list(rep.items())[:10]:
        hits.append({"id": "self-repeat", "severity": "soft", "count": c,
                     "label": f"тройка слов «{g}» повторяется", "sample": g})
        flags.append(f"[soft] повтор: «{g}» ×{c}")
    soft_hits = [h for h in hits if h["severity"] == "soft"]
    penalty = sum(3.0 + 1.0 * (h["count"] - 1) for h in soft_hits)
    banned_score = max(0.0, BANNED_POINTS - penalty)
    score += banned_score

    score = round(score, 1)
    if hard:
        score = min(score, FLOOR_GATE - 1.0)

    return {
        "draft": name, "profile": metrics["profile"], "score": score,
        "gate": PASS_GATE, "floor": FLOOR_GATE,
        "verdict": ("готово к публикации" if score >= PASS_GATE else
                    "правки по списку" if score >= FLOOR_GATE else "переписать"),
        "hard_fail": hard,
        "groups": groups + [
            {"group": "Монотонность", "points": round(MONOTONY_POINTS if not runs else 0.0, 1),
             "max": MONOTONY_POINTS, "rows": []},
            {"group": "Связки", "points": round(conn_score, 1), "max": CONNECTIVE_POINTS, "rows": []},
            {"group": "Запрещённые паттерны", "points": round(banned_score, 1),
             "max": BANNED_POINTS, "rows": []}],
        "banned_hits": hits, "flags": flags,
        "measured": {k: round(v, 3) for k, v in m.items()},
    }


def report(res):
    print(f"=== {res['draft']}  профиль {res['profile']} ===")
    for g in res["groups"]:
        print(f"  {g['group']:<22} {g['points']:>5.1f} / {g['max']}")
        for r in g["rows"]:
            mark = " " if r["verdict"] == "ok" else "!"
            print(f"   {mark} {r['metric']:<18} {r['value']:>8.3f}  "
                  f"[{r['band'][0]:.3f}..{r['band'][1]:.3f}]  {r['points']:>4.1f}/{r['max']}")
    print(f"\n  ИТОГО: {res['score']} / 100  ->  {res['verdict']}"
          + ("   [HARD FAIL]" if res["hard_fail"] else ""))
    if res["flags"]:
        print("\n  Что чинить:")
        for f in res["flags"]:
            print(f"   - {f}")
    else:
        print("\n  Замечаний нет.")


def main():
    args = sys.argv[1:]
    if "--profile" not in args:
        sys.exit("usage: audit_voice.py --profile voice-profiles/<name> "
                 "(--text-file F | --spec F | --text S) [--json] [--brief]")
    pdir = args[args.index("--profile") + 1]
    drafts = load_drafts(args)
    results = [audit(pdir, name, text) for name, text in drafts]

    if "--json" in args:
        print(json.dumps(results if len(results) > 1 else results[0],
                         ensure_ascii=False, indent=2))
    elif len(results) > 1 or "--brief" in args:
        for r in sorted(results, key=lambda r: r["score"]):
            mark = "ok " if r["score"] >= PASS_GATE else ("~  " if r["score"] >= FLOOR_GATE else "!! ")
            print(f"{mark}{r['score']:>5.1f}  {r['draft']}  ({r['verdict']})")
        worst = min(results, key=lambda r: r["score"])
        print(f"\n{len(results)} документов, средний балл "
              f"{sum(r['score'] for r in results)/len(results):.1f}, "
              f"ниже порога {PASS_GATE}: {sum(1 for r in results if r['score'] < PASS_GATE)}")
        if len(results) > 1 and worst["score"] < PASS_GATE:
            print(f"\nХудший — {worst['draft']}, разбор:")
            report(worst)
    else:
        report(results[0])
    sys.exit(0 if all(r["score"] >= PASS_GATE for r in results) else 1)


if __name__ == "__main__":
    main()
