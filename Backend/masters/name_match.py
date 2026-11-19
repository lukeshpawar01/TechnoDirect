"""Match the names people type in sheets ("Tirupati Entps", "OM SATNAM", "Jwahar") to dashboard records.

Order of tries, first unique hit wins - never a guess between two candidates:
  1. exact (case / spaces / punctuation ignored) on name, code, aliases (and full name for people)
  2. the same after expanding common abbreviations (Entps -> Enterprises, Mktg -> Marketing, ...)
  3. words: every typed word fuzzily present in the record's name (spelling slips like Jwahar / Jawahar),
     or every word of the record's short name present in what was typed ("Anil Kumar" -> ASM "Anil")
"""
import re
from difflib import SequenceMatcher

from ingestion.normalize import norm

ABBREV = {"entps": "enterprises", "entp": "enterprises", "ent": "enterprises", "mktg": "marketing",
          "dist": "distribution", "distr": "distributors", "corp": "corporation", "co": "company",
          "intl": "international", "bros": "brothers", "apparel": "apparels"}
STOP = {"the", "and", "m", "s", "ms", "pvt", "ltd", "private", "limited", "inc"}
FUZZY = 0.75


def words(text):
    out = []
    for w in re.findall(r"[a-z0-9]+", (text or "").lower()):
        w = ABBREV.get(w, w)
        if w not in STOP:
            out.append(w)
    return out


def _close(a, b):
    return a == b or (len(a) > 2 and len(b) > 2 and SequenceMatcher(None, a, b).ratio() >= FUZZY)


def _covers(typed, name_words):
    """every typed word has a close word in the record name"""
    return bool(typed) and all(any(_close(t, n) for n in name_words) for t in typed)


def best(text, records, keys):
    """The one record matching `text`, or None. keys(record) -> list of names for that record."""
    if not (text or "").strip():
        return None
    k = norm(text)
    hits = [r for r in records if k in {norm(x) for x in keys(r) if x}]
    if len(hits) == 1:
        return hits[0]
    kx = norm(" ".join(words(text)))
    hits = [r for r in records if kx in {norm(" ".join(words(x))) for x in keys(r) if x}]
    if len(hits) == 1:
        return hits[0]
    typed = words(text)
    hits = [r for r in records if any(_covers(typed, words(x)) for x in keys(r) if x)]
    if len(hits) == 1:
        return hits[0]
    # the record's own (short) name is fully inside what was typed: "Anil Kumar" -> "Anil", "Mohd Jafar" -> "Jafar"
    rev = [r for r in records if any(_covers(words(x), typed) for x in keys(r)[:1] if x)]
    if len(rev) == 1:
        return rev[0]
    # several partial hits: keep the one covering the most typed words (an exact word beats a near one)
    if hits:
        def fit(x):
            ws = words(x)
            return sum(1.0 if t in ws else 0.9 if any(_close(t, n) for n in ws) else 0 for t in typed)

        score = {id(r): max(fit(x) for x in keys(r) if x) for r in hits}
        top = max(score.values())
        tops = [r for r in hits if score[id(r)] == top]
        if len(tops) == 1:
            return tops[0]
    # most typed words present (e.g. "Om Sri Sai Satnam" -> "Om Sri Satnam Sakhi Traders"): 3 of 4 or better
    if len(typed) >= 3:
        scored = []
        for r in records:
            s = max((sum(any(_close(t, n) for n in words(x)) for t in typed) for x in keys(r) if x), default=0)
            scored.append((s, r))
        top = max(s for s, _ in scored)
        tops = [r for s, r in scored if s == top]
        if top >= 0.75 * len(typed) and len(tops) == 1:
            return tops[0]
    return None


def distributor(text, dists):
    return best(text, dists, lambda d: [d.name, d.code, *(d.aliases or [])])


def person(text, people):
    """ASM or field staff (name first, then the HR full name)."""
    return best(text, people, lambda p: [p.name, getattr(p, "full_name", "") or ""])
