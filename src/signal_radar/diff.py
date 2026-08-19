"""Quarter-over-quarter novelty detection.

The core insight this module encodes: companies recite the same talking points
every quarter. "Large unmet need", "strong launch execution", "well positioned"
are constants, not news. What is material is what CHANGED - a number that moved,
a date that slipped, a hedge that appeared where none was before, or a program
that stopped being mentioned at all.

Without this the digest reprints the same five signals every quarter and the
analyst stops opening it. This is the difference between a summarizer and a
monitor.

Implementation is deliberately lexical, not semantic. Embeddings would catch
paraphrase better, but they also smooth over exactly the small edits that carry
the signal - "in 2027" to "tracking toward 2027" is a near-identical vector and
a materially different statement.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from .extract import Claim

# Phrases that mark a statement as hedged. Their APPEARANCE between quarters is
# the signal, more than their presence in any single quarter.
HEDGE_MARKERS = [
    "tracking toward", "tracking towards", "on track", "in the ballpark",
    "more precision", "when we can be more precise", "we haven't confirmed",
    "have not confirmed", "roughly", "approximately", "around", "we expect",
    "declined to", "no more precise", "cannot quantify", "can't quantify",
    "anticipate", "currently projecting", "at this point", "no specific date",
    "we'll provide an update", "will provide more", "some variability",
]

_NUM = re.compile(r"\b\d[\d,\.]*%?\b")
_DATE = re.compile(r"\b(?:1H|2H|H1|H2|Q[1-4]|early|mid|late|first half|second half)?\s*20\d{2}\b", re.I)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 %]", " ", text.lower())


def _keys(claim: Claim) -> list[tuple]:
    """Bucket keys for a claim - one per affected holding.

    Deliberately NOT keyed on the full holding tuple. A claim that gains a
    second affected holding between quarters (MDGL alone -> MDGL and IVA) is
    the same underlying topic, and keying on the exact set would classify it as
    brand new every time the linkage widened.
    """
    return [(claim.signal_type, h) for h in claim.affected_holdings]


def _entities(claim: Claim) -> set[str]:
    """Flatten the entity payload into a comparable bag.

    Entities are the stable identity of a topic across quarters. The `claim`
    field is the model's paraphrase and rewords itself run to run; the trial
    name and the drug name do not.
    """
    out: set[str] = set()
    for field_name in ("trials", "drugs", "indications", "mechanisms"):
        out |= {v.lower().strip() for v in claim.entities.get(field_name, []) if v}
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _topic_match(c: Claim, p: Claim) -> float:
    """How likely two claims are about the same running topic.

    Weighted toward entities over prose for the reason above, but text
    similarity still contributes so that two claims about the same trial but
    genuinely different subjects do not collapse together.
    """
    return 0.65 * _jaccard(_entities(c), _entities(p)) + 0.35 * _similarity(c.claim, p.claim)


TOPIC_THRESHOLD = 0.30


# Some hedges take an interpolated adverb - "haven't ACTUALLY confirmed",
# "tracking BROADLY toward". Match with a small gap rather than exact substring,
# otherwise the most informative hedges are the ones we miss.
_GAP = r"(?:\s+\w+){0,2}\s+"
_HEDGE_RE = [
    # Escape word by word: re.escape() escapes the space itself on some
    # Python builds, which would leave a stray backslash before the group.
    (m, re.compile(_GAP.join(re.escape(w) for w in m.split()), re.I))
    for m in HEDGE_MARKERS
]


def _hedges(text: str) -> set[str]:
    return {m for m, pat in _HEDGE_RE if pat.search(text)}


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def classify_novelty(current: list[Claim], prior: list[Claim]) -> list[Claim]:
    """Tag each current claim as new / changed / repeated / unknown.

    Also writes a human-readable `delta` onto changed claims so the digest can
    show the analyst WHAT changed, not just that something did. A flag with no
    explanation gets ignored; a flag that says "date acquired three new hedges"
    gets clicked.
    """
    if not prior:
        for c in current:
            c.novelty = "unknown"
        return current

    buckets: dict[tuple, list[Claim]] = {}
    for p in prior:
        for k in _keys(p):
            buckets.setdefault(k, []).append(p)

    for c in current:
        candidates: list[Claim] = []
        seen: set[int] = set()
        for k in _keys(c):
            for p in buckets.get(k, []):
                if id(p) not in seen:
                    seen.add(id(p))
                    candidates.append(p)

        if not candidates:
            c.novelty = "new"
            continue

        best = max(candidates, key=lambda p: _topic_match(c, p))
        match = _topic_match(c, best)

        if match < TOPIC_THRESHOLD:
            c.novelty = "new"
            continue

        deltas: list[str] = []

        new_nums = set(_NUM.findall(c.quote)) - set(_NUM.findall(best.quote))
        if new_nums:
            deltas.append(f"figures changed: {', '.join(sorted(new_nums)[:4])}")

        cur_dates, prior_dates = set(_DATE.findall(c.quote)), set(_DATE.findall(best.quote))
        if cur_dates and prior_dates and cur_dates != prior_dates:
            deltas.append(f"timing moved: {'/'.join(sorted(prior_dates))} -> {'/'.join(sorted(cur_dates))}")

        new_hedges = _hedges(c.quote) - _hedges(best.quote)
        if new_hedges:
            deltas.append(f"new hedging: {', '.join(sorted(new_hedges)[:3])}")

        if deltas:
            c.novelty = "changed"
            c.delta = "; ".join(deltas)
        elif match > 0.75:
            c.novelty = "repeated"
        else:
            c.novelty = "changed"
            c.delta = "rewording without figure or date change"

    return current


def dropped_topics(current: list[Claim], prior: list[Claim]) -> list[str]:
    """Programs discussed last quarter and absent this quarter.

    Silence is a signal. A pipeline asset that vanishes from the script between
    quarters is often the first observable sign of a deprioritisation, and it is
    invisible to any approach that only reads what was said.
    """
    def drugs(claims: list[Claim]) -> set[str]:
        return {d.lower() for c in claims for d in c.entities.get("drugs", []) if d}

    gone = drugs(prior) - drugs(current)
    return sorted(gone)
