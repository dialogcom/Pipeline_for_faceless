#!/usr/bin/env python3
"""
voice_metrics.py — the measurable half of a voice profile.

The NotebookLM flow this replaces asks a model to *describe* sentence rhythm, favourite
transitions, vocabulary and punctuation habits. A model describing prose is guessing; these
are all countable, so here they are counted. analyze_voice.py turns a corpus into
distributions of these numbers, audit_voice.py scores one draft against those distributions,
and no model opinion enters either step.

Every metric is per-document, so a corpus yields a distribution (p10/p50/p90) rather than a
single number — that spread is what an audit compares against.
"""
import re
from collections import Counter
from statistics import mean, median, pstdev

WORD = re.compile(r"[А-Яа-яЁёA-Za-z][А-Яа-яЁёA-Za-z\-']*")
SENT_SPLIT = re.compile(r"(?<=[.!?…])[»\"']?\s+")

# Connectives / discourse markers — "любимые связующие слова" from the video's prompt #1.
# Counted as whole words, so this doubles as the profile's transition inventory.
CONNECTIVES = [
    "но", "а", "и", "или", "зато", "однако", "впрочем", "хотя", "тем не менее",
    "потому что", "поэтому", "значит", "то есть", "именно", "ведь", "всё-таки",
    "при этом", "кроме того", "вместо", "пока", "когда", "если", "чтобы", "как будто",
    "теперь", "тогда", "дальше", "сначала", "потом", "наконец", "снова", "опять",
    "даже", "только", "уже", "ещё", "просто", "вот", "здесь", "именно поэтому",
]

TRIAD = re.compile(r"\b[\w\-]+,\s+[\w\-]+\s+и\s+[\w\-]+\b", re.UNICODE)

# Function words. Used to keep the repeated-phrase detector from firing on grammatical
# scaffolding ("в тысяча девятьсот") instead of on an author reusing a real phrase.
FUNCTION_WORDS = set("""
и а но или да не ни в во на за под над от до из к ко с со о об про для по при без через
между у же ли бы то это этот эта эти тот та те как что чем чему кто кого кому где когда
там тут вот вы вас вам ваш ваша ваше ваши он она они его её их им них себя свой своя своё
свои был была было были быть есть уже ещё только даже так такой такая такие все всё весь
я мы мне нам меня нас один одна одно два три сто тысяча тысяч сотня десять двадцать
тридцать сорок пятьдесят шестьдесят семьдесят восемьдесят девяносто двести триста
четыреста пятьсот шестьсот семьсот восемьсот девятьсот первый второй третий году лет год
""".split())

MATTR_WINDOW = 100  # tokens


def mattr(tokens, window=MATTR_WINDOW):
    """Moving-average type-token ratio: length-invariant vocabulary richness. Plain TTR
    falls as a document grows, so comparing a long draft to short corpus documents on raw
    TTR measures length, not vocabulary."""
    low = [t.lower() for t in tokens]
    if len(low) <= window:
        return len(set(low)) / max(1, len(low))
    ratios = [len(set(low[i:i + window])) / window for i in range(len(low) - window + 1)]
    return sum(ratios) / len(ratios)


def window_hapax(tokens, window=MATTR_WINDOW):
    """Same idea for the once-only-word share."""
    low = [t.lower() for t in tokens]
    if len(low) <= window:
        c = Counter(low)
        return sum(1 for v in c.values() if v == 1) / max(1, len(set(low)))
    vals = []
    for i in range(0, len(low) - window + 1, max(1, window // 4)):
        c = Counter(low[i:i + window])
        vals.append(sum(1 for v in c.values() if v == 1) / max(1, len(c)))
    return sum(vals) / len(vals)


def sentences(text):
    parts = [s.strip() for s in SENT_SPLIT.split(text.strip()) if s.strip()]
    return [s for s in parts if WORD.search(s)]


def words(text):
    return WORD.findall(text)


def ngrams(tokens, n):
    low = [t.lower() for t in tokens]
    return [" ".join(low[i:i + n]) for i in range(len(low) - n + 1)]


def doc_metrics(text):
    """All per-document numbers. Returns a flat dict of floats/ints."""
    sents = sentences(text)
    lens = [len(words(s)) for s in sents] or [0]
    toks = words(text)
    low = [t.lower() for t in toks]
    nw = max(1, len(toks))
    ns = max(1, len(sents))
    adj = [abs(a - b) for a, b in zip(lens, lens[1:])] or [0]
    openers = [words(s)[0].lower() for s in sents if words(s)]
    sd = pstdev(lens) if len(lens) > 1 else 0.0
    m = {
        "sentences": len(sents),
        "words": len(toks),
        "wps_mean": mean(lens),
        "wps_median": median(lens),
        "wps_sd": sd,
        # burstiness: the video's "динамичность". Coefficient of variation of sentence
        # length — the single number that separates human prose from flat LLM output.
        "wps_cv": sd / mean(lens) if mean(lens) else 0.0,
        "wps_min": min(lens),
        "wps_max": max(lens),
        # how far consecutive sentences jump. A high CV with a low adj_delta means the text
        # is sorted (all short, then all long); real writing alternates.
        "adj_delta": mean(adj),
        "short_share": sum(1 for l in lens if l <= 6) / ns,
        "long_share": sum(1 for l in lens if l >= 25) / ns,
        "word_len_mean": sum(len(t) for t in toks) / nw,
        "ttr": mattr(toks),
        "hapax_share": window_hapax(toks),
        "opener_diversity": len(set(openers)) / max(1, len(openers)),
        "question_share": sum(1 for s in sents if s.rstrip('»"\'').endswith("?")) / ns,
        "exclam_share": sum(1 for s in sents if s.rstrip('»"\'').endswith("!")) / ns,
        "comma_per_100w": text.count(",") / nw * 100,
        "colon_per_100w": text.count(":") / nw * 100,
        "semicolon_per_100w": text.count(";") / nw * 100,
        "hyphen_per_100w": len(re.findall(r"\s-\s", text)) / nw * 100,
        "quote_per_100w": text.count("«") / nw * 100,
        "triad_per_100w": len(TRIAD.findall(text)) / nw * 100,
    }
    return m


def connective_counts(text):
    low = " " + " ".join(w.lower() for w in words(text)) + " "
    return {c: low.count(f" {c} ") for c in CONNECTIVES}


def opener_counts(text):
    return Counter(words(s)[0].lower() for s in sentences(text) if words(s))


def monotony_runs(text, run=4, rel_tol=0.25, min_mean=9.0, long_run=6):
    """Runs of consecutive sentences all within rel_tol of the run's own mean length — the
    literal shape of 'ИИ пишет монотонно'.

    Judged relatively, not in absolute words, because a burst of very short sentences
    ("Попытка первая. Попытка вторая.") is a deliberate human device, while four 13-word
    sentences in a row is the machine tell. A short run therefore only counts once it gets
    long enough (long_run) to stop reading as emphasis.
    """
    sents = sentences(text)
    lens = [len(words(s)) for s in sents]
    out, i = [], 0
    while i < len(lens):
        j = i
        while j + 1 < len(lens):
            span = lens[i:j + 2]
            if (max(span) - min(span)) / (sum(span) / len(span)) > rel_tol:
                break
            j += 1
        span = lens[i:j + 1]
        n = len(span)
        if n >= run and (sum(span) / n >= min_mean or n >= long_run):
            out.append((i, span))
            i = j + 1
        else:
            i += 1
    return out


def has_content(gram):
    return any(t not in FUNCTION_WORDS and len(t) > 4 for t in gram.split())


def repeated_ngrams(text, n=3, min_count=2):
    """Repeated phrases that carry meaning. Grammatical scaffolding is excluded — a script
    that spells out several years necessarily repeats "в тысяча девятьсот", and that is a
    house convention, not the author reusing a phrase."""
    c = Counter(g for g in ngrams(words(text), n) if len(g) > 12 and has_content(g))
    return {g: k for g, k in c.items() if k >= min_count}
