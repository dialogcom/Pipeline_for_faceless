#!/usr/bin/env python3
"""
voice_corpus.py — pull narration text out of this repo's script formats.

Shared by analyze_voice.py (build a profile from a corpus) and audit_voice.py (audit one
draft). Every track stores its narration differently, so each format gets a tiny extractor
and the rest of the voice system only ever sees {"id": ..., "text": ...} documents.

Kinds:
  narrated_scripts  narrated-shorts/<series>/scripts.json  — hook + vo + ending per episode
  retelling_script  retellings/<slug>/script.json          — one doc per beat
  vox_script_md     vox-shorts/vox-N-*/script.md           — the quoted VO cells of the beat table
  text              any .txt/.md file, whole file as one doc

Optional per-source post-processing, for literary sources that are not already shaped like
narration (see voice-profiles/chekhov-ru/sources.json):
  drop_lines_re     [regex, ...]  drop whole lines matching any of these (titles, byline,
                                  roman-numeral section markers)
  strip_dialogue    true          drop dash-initial dialogue lines, keeping narration only
  normalize_dashes  true          rewrite — and – to a plain hyphen
  chunk_words       N             split each document into ~N-word chunks at paragraph
                                  boundaries, so one long story yields several samples
"""
import json
import re
from pathlib import Path

STRESS = "́"
CYR = re.compile(r"[А-Яа-яЁё]")
LAT = re.compile(r"[A-Za-z]")


def clean(text):
    return text.replace(STRESS, "").strip()


DIALOGUE_LINE = re.compile(r"^\s*[—–-]\s")


def strip_dialogue_lines(text):
    """Keep narration, drop spoken lines.

    Chekhov is largely dialogic, and in these files each utterance is its own dash-initial
    line. Dialogue and narration have different rhythms — a page of one-word retorts posts a
    burstiness no monologue can reach — so mixing them produces bands that describe neither.
    A narrator's voice profile wants the narration."""
    return "\n".join(l for l in text.splitlines() if not DIALOGUE_LINE.match(l))


def chunk_by_words(text, target):
    """Split at paragraph boundaries into ~target-word pieces. Bands need samples: seven
    stories are seven numbers, and a p10/p90 off seven numbers is noise."""
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    out, cur, n = [], [], 0
    for para in paras:
        cur.append(para)
        n += len(para.split())
        if n >= target:
            out.append("\n".join(cur))
            cur, n = [], 0
    if cur and (n >= target * 0.4 or not out):
        out.append("\n".join(cur))
    elif cur and out:
        out[-1] += "\n" + "\n".join(cur)
    return out


def postprocess(text, src):
    for pattern in src.get("drop_lines_re", []):
        rx = re.compile(pattern)
        text = "\n".join(l for l in text.splitlines() if not rx.match(l.strip()))
    if src.get("strip_dialogue"):
        text = strip_dialogue_lines(text)
    if src.get("normalize_dashes"):
        # Glyph, not habit: the metrics care how often the author reaches for a dash-shaped
        # pause, and this repo's own convention writes that pause as a hyphen. Comparing
        # Chekhov's typography to the house style would measure the typesetter.
        text = text.replace("—", "-").replace("–", "-")
    return text


def cyrillic_ratio(text):
    c, l = len(CYR.findall(text)), len(LAT.findall(text))
    return c / (c + l) if (c + l) else 0.0


def _narrated_scripts(path):
    for e in json.loads(Path(path).read_text(encoding="utf-8")):
        parts = [e.get("hook", ""), e.get("vo", ""), e.get("ending", "")]
        yield f"{Path(path).parent.name}/{e.get('slug', e.get('id'))}", " ".join(p for p in parts if p)


def _retelling_script(path):
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    for i, b in enumerate(spec.get("beats", [])):
        yield f"{spec.get('slug', Path(path).parent.name)}/b{i:02d}-{b.get('role', '')}", b.get("text", "")


def _vox_script_md(path):
    """The VO lives in the beat table as the quoted cell. Take every double-quoted run that
    is long enough and Cyrillic enough to be narration rather than a chip label."""
    md = Path(path).read_text(encoding="utf-8")
    lines = [q for q in re.findall(r'"([^"]{40,})"', md) if cyrillic_ratio(q) > 0.5]
    if lines:
        yield Path(path).parent.name, " ".join(lines)


def _text(path):
    yield Path(path).stem, Path(path).read_text(encoding="utf-8")


EXTRACTORS = {
    "narrated_scripts": _narrated_scripts,
    "retelling_script": _retelling_script,
    "vox_script_md": _vox_script_md,
    "text": _text,
}


def load_corpus(sources, root, min_cyrillic=0.0):
    """sources: [{"kind": ..., "path": <glob relative to root>}, ...] -> [(id, text), ...]"""
    docs, skipped = [], []
    for src in sources:
        fn = EXTRACTORS.get(src["kind"])
        if not fn:
            raise SystemExit(f"unknown source kind {src['kind']!r} "
                             f"(known: {', '.join(EXTRACTORS)})")
        matches = sorted(Path(root).glob(src["path"]))
        if not matches:
            skipped.append(f"{src['path']} (no files matched)")
        for p in matches:
            for did, text in fn(p):
                text = clean(postprocess(text, src))
                pieces = ([(f"{did}#{i:02d}", t) for i, t in
                           enumerate(chunk_by_words(text, src["chunk_words"]))]
                          if src.get("chunk_words") else [(did, text)])
                for did, text in pieces:
                    _keep(docs, skipped, did, text, min_cyrillic)
    return docs, skipped


def _keep(docs, skipped, did, text, min_cyrillic):
    if len(text.split()) < 25:
        skipped.append(f"{did} (under 25 words)")
    elif cyrillic_ratio(text) < min_cyrillic:
        skipped.append(f"{did} (cyrillic {cyrillic_ratio(text):.2f} "
                       f"< {min_cyrillic}) — wrong-language source")
    else:
        docs.append((did, text))
