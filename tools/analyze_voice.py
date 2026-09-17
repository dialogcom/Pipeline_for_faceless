#!/usr/bin/env python3
"""
analyze_voice.py — build a voice profile from a corpus of the author's own writing.

This is the repo-native replacement for the video's "upload your texts to NotebookLM and
ask it to describe your style" step. Instead of asking a model to characterise rhythm,
transitions, vocabulary and punctuation, it measures them, per document, and stores the
resulting distributions. audit_voice.py then scores drafts against those distributions, so
"does this sound like me" becomes a number derived from the author's own text rather than
a second model's opinion.

Usage:
  python tools/analyze_voice.py --profile voice-profiles/uka-ru
  python tools/analyze_voice.py --profile voice-profiles/uka-ru --show   # print, write nothing

Reads  voice-profiles/<name>/sources.json   (which files make up the corpus)
Writes voice-profiles/<name>/metrics.json   (per-doc metrics + p10/p50/p90 bands + inventories)
       voice-profiles/<name>/PROFILE.md     (the readable profile; everything below the
                                             HAND-WRITTEN marker is preserved on re-runs)
"""
import json
import sys
from collections import Counter
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from voice_corpus import load_corpus  # noqa: E402
from voice_metrics import (  # noqa: E402
    CONNECTIVES, connective_counts, doc_metrics, opener_counts, repeated_ngrams, words,
)

# Metrics an audit scores against. Everything else in metrics.json is descriptive.
BAND_KEYS = ["wps_mean", "wps_cv", "adj_delta", "short_share", "long_share", "wps_max",
             "word_len_mean", "ttr", "hapax_share", "opener_diversity", "question_share",
             "comma_per_100w", "colon_per_100w", "hyphen_per_100w", "triad_per_100w"]

MARKER = "<!-- HAND-WRITTEN BELOW — analyze_voice.py never touches anything past this line -->"


def pct(values, q):
    """Plain nearest-rank percentile; the corpus is dozens of docs, not thousands."""
    s = sorted(values)
    if not s:
        return 0.0
    k = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[k]


def build(profile_dir):
    profile_dir = Path(profile_dir)
    cfg = json.loads((profile_dir / "sources.json").read_text(encoding="utf-8"))
    docs, skipped = load_corpus(cfg["sources"], ROOT, cfg.get("min_cyrillic_ratio", 0.0))
    if len(docs) < 5:
        sys.exit(f"only {len(docs)} usable documents — a profile needs at least 5 "
                 f"(skipped: {'; '.join(skipped) or 'nothing'})")

    per_doc = {did: doc_metrics(t) for did, t in docs}
    bands = {k: {"p10": pct([m[k] for m in per_doc.values()], 0.10),
                 "p50": pct([m[k] for m in per_doc.values()], 0.50),
                 "p90": pct([m[k] for m in per_doc.values()], 0.90),
                 "mean": mean([m[k] for m in per_doc.values()])} for k in BAND_KEYS}

    joined = " ".join(t for _, t in docs)
    total_words = len(words(joined))
    conn = {k: v for k, v in sorted(connective_counts(joined).items(),
                                    key=lambda kv: -kv[1]) if v}
    openers = opener_counts(joined)
    vocab = Counter(w.lower() for w in words(joined))
    # Content words only: drop the connective/function words already reported above.
    content = {w: c for w, c in vocab.items() if w not in set(CONNECTIVES) and len(w) > 4}

    metrics = {
        "profile": cfg["name"],
        "language": cfg.get("language", "ru"),
        "corpus": {"documents": len(docs), "words": total_words,
                   "sources": [s["path"] for s in cfg["sources"]], "skipped": skipped},
        "bands": bands,
        "per_doc": per_doc,
        "connectives": conn,
        "connectives_per_1000w": {k: round(v / total_words * 1000, 2) for k, v in conn.items()},
        "openers": dict(openers.most_common(30)),
        "vocabulary_top": dict(Counter(content).most_common(60)),
        "repeated_ngrams": dict(sorted(repeated_ngrams(joined, 3, 3).items(),
                                       key=lambda kv: -kv[1])[:30]),
    }
    return metrics, docs


def render_profile_md(metrics):
    b = metrics["bands"]
    c = metrics["corpus"]
    r = lambda k, p, n=2: f"{b[k][p]:.{n}f}"
    lines = [
        f"# Voice profile: `{metrics['profile']}`",
        "",
        "**Сгенерировано `tools/analyze_voice.py` — не редактируйте руками выше маркера.**",
        f"Корпус: {c['documents']} документов, {c['words']} слов. "
        f"Источники: {', '.join('`' + s + '`' for s in c['sources'])}.",
        "",
        "Это измеренная половина профиля. Всё здесь посчитано по текстам автора; полосы "
        "p10-p90 — то, во что должен попадать новый текст, чтобы звучать как этот корпус. "
        "`tools/audit_voice.py` сверяет черновик именно с этими числами.",
        "",
        "## Ритм предложений",
        "",
        "| метрика | p10 | медиана | p90 | что это |",
        "|---|---|---|---|---|",
        f"| слов в предложении | {r('wps_mean','p10',1)} | {r('wps_mean','p50',1)} | {r('wps_mean','p90',1)} | средняя длина |",
        f"| **burstiness (CV)** | {r('wps_cv','p10')} | {r('wps_cv','p50')} | {r('wps_cv','p90')} | разброс длин / средняя. Главное число: ИИ по умолчанию даёт ~0.25-0.35 |",
        f"| скачок между соседними | {r('adj_delta','p10',1)} | {r('adj_delta','p50',1)} | {r('adj_delta','p90',1)} | на сколько слов соседние предложения отличаются |",
        f"| доля коротких (<=6 слов) | {r('short_share','p10')} | {r('short_share','p50')} | {r('short_share','p90')} | |",
        f"| доля длинных (>=25 слов) | {r('long_share','p10')} | {r('long_share','p50')} | {r('long_share','p90')} | |",
        f"| самое длинное предложение | {r('wps_max','p10',0)} | {r('wps_max','p50',0)} | {r('wps_max','p90',0)} | потолок, а не цель |",
        "",
        "## Словарь",
        "",
        "| метрика | p10 | медиана | p90 |",
        "|---|---|---|---|",
        f"| TTR (уникальных / всего) | {r('ttr','p10')} | {r('ttr','p50')} | {r('ttr','p90')} |",
        f"| доля hapax (слов-однократок) | {r('hapax_share','p10')} | {r('hapax_share','p50')} | {r('hapax_share','p90')} |",
        f"| средняя длина слова | {r('word_len_mean','p10')} | {r('word_len_mean','p50')} | {r('word_len_mean','p90')} |",
        f"| разнообразие зачинов | {r('opener_diversity','p10')} | {r('opener_diversity','p50')} | {r('opener_diversity','p90')} |",
        "",
        "## Пунктуация",
        "",
        "| метрика | p10 | медиана | p90 |",
        "|---|---|---|---|",
        f"| запятых на 100 слов | {r('comma_per_100w','p10',1)} | {r('comma_per_100w','p50',1)} | {r('comma_per_100w','p90',1)} |",
        f"| двоеточий на 100 слов | {r('colon_per_100w','p10',1)} | {r('colon_per_100w','p50',1)} | {r('colon_per_100w','p90',1)} |",
        f"| дефисов-тире на 100 слов | {r('hyphen_per_100w','p10',1)} | {r('hyphen_per_100w','p50',1)} | {r('hyphen_per_100w','p90',1)} |",
        f"| доля вопросов | {r('question_share','p10')} | {r('question_share','p50')} | {r('question_share','p90')} |",
        f"| триад «X, Y и Z» на 100 слов | {r('triad_per_100w','p10',1)} | {r('triad_per_100w','p50',1)} | {r('triad_per_100w','p90',1)} |",
        "",
        "## Связки, которыми автор пользуется на самом деле",
        "",
        "На 1000 слов, по убыванию:",
        "",
    ]
    top = list(metrics["connectives_per_1000w"].items())[:20]
    lines.append(" · ".join(f"**{k}** {v}" for k, v in top))
    lines += ["", "## Чем начинаются предложения", "",
              " · ".join(f"{k} ({v})" for k, v in list(metrics["openers"].items())[:20]), "",
              "## Характерная лексика", "",
              " · ".join(f"{k} ({v})" for k, v in list(metrics["vocabulary_top"].items())[:40]), ""]
    if metrics["repeated_ngrams"]:
        lines += ["## Повторяющиеся обороты корпуса", "",
                  "Это привычки автора, а не ошибки, — но новый текст, где та же тройка слов "
                  "встречается дважды, звучит машинно:", "",
                  " · ".join(f"«{k}» ×{v}" for k, v in list(metrics["repeated_ngrams"].items())[:15]), ""]
    lines += ["---", "", MARKER, "",
              "## Качественная часть (заполняется человеком или Claude при чтении корпуса)", "",
              "- **Регистр:** ",
              "- **Отношение к читателю:** ",
              "- **Что автор никогда не делает:** ",
              "- **Фирменные ходы:** ", ""]
    return "\n".join(lines)


def main():
    args = sys.argv[1:]
    if "--profile" not in args:
        sys.exit("usage: analyze_voice.py --profile voice-profiles/<name> [--show]")
    pdir = Path(args[args.index("--profile") + 1])
    metrics, docs = build(pdir)
    c = metrics["corpus"]
    print(f"corpus: {c['documents']} docs, {c['words']} words", file=sys.stderr)
    for s in c["skipped"]:
        print(f"  skipped: {s}", file=sys.stderr)
    b = metrics["bands"]
    print(f"  burstiness CV p10-p90: {b['wps_cv']['p10']:.2f}-{b['wps_cv']['p90']:.2f} "
          f"(median {b['wps_cv']['p50']:.2f})", file=sys.stderr)
    if "--show" in args:
        print(render_profile_md(metrics))
        return

    (pdir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8")
    md_path = pdir / "PROFILE.md"
    generated = render_profile_md(metrics)
    if md_path.exists() and MARKER in md_path.read_text(encoding="utf-8"):
        kept = md_path.read_text(encoding="utf-8").split(MARKER, 1)[1]
        generated = generated.split(MARKER, 1)[0] + MARKER + kept
    md_path.write_text(generated, encoding="utf-8")
    print(f"-> {pdir/'metrics.json'}\n-> {md_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
