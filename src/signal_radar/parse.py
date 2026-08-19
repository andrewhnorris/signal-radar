"""Turn a raw transcript into speaker-attributed, section-labelled passages.

Why this module exists at all: the single highest-value structural fact about an
earnings call is that it has two halves with very different information content.
Prepared remarks are written by IR and reviewed by counsel. Q&A is where the
hedging, the walk-backs, and the unscripted competitive jabs live. Collapsing
them into one blob of text throws that away before the model ever sees it.

Parsing is deliberately regex-based rather than model-based: transcript layout is
consistent per vendor, and a regex that fails loudly is easier to debug at 7am
than a model that silently mislabels a speaker.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Iterator, Literal

Section = Literal["prepared", "qa"]

# Vendor format: **Name, Title, Company**: text
# The optional trailing digits are a diarization artefact - investing.com emits
# "**Name, Analyst, Firm**0:" when its speaker separation is uncertain, reusing
# one name with different suffixes for different people. Without allowing for
# them here the line fails to match at all and is silently appended to the
# PREVIOUS speaker's turn, which is a far worse failure than a wrong label.
_SPEAKER_PATTERNS = [
    re.compile(r"^\*\*(?P<who>[^*]+?)\*\*\d*\s*:\s*(?P<text>.*)$"),
    re.compile(r"^(?P<who>[A-Z][A-Za-z.'\- ]{2,60}(?:,[^:]{0,80})?)\d*\s*:\s{1}(?P<text>.+)$"),
]

# Markers that the call has moved from prepared remarks into Q&A. Checked in
# order; first hit wins. Kept broad because vendors phrase this differently.
_QA_MARKERS = [
    re.compile(r"turn (?:the call |it )?(?:back )?over to .{0,40} (?:to )?(?:begin|start) the q\s*&\s*a", re.I),
    re.compile(r"(?:let'?s |we'?ll )?(?:move|turn) (?:in)?to the q\s*&\s*a", re.I),
    re.compile(r"(?:we will|we'll) now (?:begin|conduct|open).{0,40}question[- ]and[- ]answer", re.I),
    re.compile(r"^\s*question[- ]and[- ]answer session\s*$", re.I),
    re.compile(r"first question comes from", re.I),
]

_TITLE_HINTS = {
    "chief executive": "CEO", "ceo": "CEO",
    "chief medical": "CMO", "cmo": "CMO",
    "chief financial": "CFO", "cfo": "CFO",
    "investor relations": "IR",
    "analyst": "ANALYST",
    "operator": "OPERATOR",
}


@dataclass
class Passage:
    """One contiguous block of speech by one person."""
    idx: int
    speaker: str
    role: str          # CEO / CMO / CFO / IR / ANALYST / OPERATOR / OTHER
    affiliation: str   # company or bank, best effort
    section: Section
    text: str

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def is_management(self) -> bool:
        return self.role in {"CEO", "CMO", "CFO", "IR", "OTHER"} and self.role != "ANALYST"


# Operator boilerplate, matched on CONTENT rather than on the speaker label.
#
# Necessary because vendor diarization is not reliable. In the Inventiva
# FY2025 transcript the operator's turns are attributed to an analyst with a
# numeric suffix - "Anna Andre Kripa, Analyst, Truist Securities0:" - and the
# same analyst name is reused with different suffixes for several different
# people. Filtering on the OPERATOR role alone would let dial-in instructions
# through as analyst commentary, and would attribute other analysts' questions
# to the wrong bank.
_OPERATOR_CONTENT = re.compile(
    r"press star|press \*|listen[- ]only mode|withdraw your question|"
    r"conference is being recorded|hand the conference over|"
    r"next question comes from|question for today comes from|"
    r"concludes today'?s|you may now disconnect|please stand by",
    re.I,
)

# Trailing digits on a speaker label are a diarization artefact, not part of
# anyone's name.
_NAME_SUFFIX = re.compile(r"\d+$")


def _looks_like_operator(text: str) -> bool:
    """True if a passage is operator boilerplate regardless of its label."""
    head = text[:220]
    return bool(_OPERATOR_CONTENT.search(head))


def _classify_speaker(who: str) -> tuple[str, str, str]:
    """Split a '**Name, Title, Company**' blob into (name, role, affiliation)."""
    who = _NAME_SUFFIX.sub("", who.strip())
    parts = [p.strip() for p in who.split(",")]
    name = parts[0]
    tail = ", ".join(parts[1:]).lower()

    role = "OTHER"
    if name.strip().lower().startswith("operator"):
        role = "OPERATOR"
    else:
        for hint, label in _TITLE_HINTS.items():
            if hint in tail:
                role = label
                break

    affiliation = parts[-1] if len(parts) > 1 else ""
    return name, role, affiliation


def _is_qa_start(line: str) -> bool:
    return any(p.search(line) for p in _QA_MARKERS)


def _match_speaker(line: str):
    for pat in _SPEAKER_PATTERNS:
        m = pat.match(line.strip())
        if m:
            return m
    return None


def parse_transcript(raw: str) -> list[Passage]:
    """Parse transcript text into ordered, section-labelled passages.

    Section assignment is stateful and one-way: once we have seen a Q&A marker we
    never flip back to prepared. This is intentional - a stray 'question' in a
    closing remark should not reset the whole document.
    """
    passages: list[Passage] = []
    section: Section = "prepared"
    cur: Passage | None = None
    idx = 0

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        if section == "prepared" and _is_qa_start(stripped):
            section = "qa"

        m = _match_speaker(stripped)
        if m:
            if cur and cur.text.strip():
                passages.append(cur)
            name, role, affil = _classify_speaker(m.group("who"))
            # In Q&A, a non-management speaker asking a question is an analyst.
            if section == "qa" and role == "OTHER" and affil:
                role = "ANALYST"
            idx += 1
            cur = Passage(idx=idx, speaker=name, role=role, affiliation=affil,
                          section=section, text=m.group("text").strip())
        elif cur:
            cur.text += " " + stripped

    if cur and cur.text.strip():
        passages.append(cur)

    return [p for p in passages
            if p.role != "OPERATOR"
            and not _looks_like_operator(p.text)
            and len(p.text) > 40]


def chunk(passages: list[Passage], max_chars: int = 6000) -> Iterator[list[Passage]]:
    """Group passages into model-sized batches without splitting a passage.

    Chunks never span the prepared/Q&A boundary, so the section label stays
    unambiguous for every claim the model returns.
    """
    batch: list[Passage] = []
    size = 0
    for p in passages:
        if batch and (size + len(p.text) > max_chars or p.section != batch[0].section):
            yield batch
            batch, size = [], 0
        batch.append(p)
        size += len(p.text)
    if batch:
        yield batch


def summarize(passages: list[Passage]) -> dict:
    """Parse-quality stats. Printed on every run so a bad parse is visible."""
    prepared = [p for p in passages if p.section == "prepared"]
    qa = [p for p in passages if p.section == "qa"]
    return {
        "passages": len(passages),
        "prepared": len(prepared),
        "qa": len(qa),
        "analysts": len({p.affiliation for p in qa if p.role == "ANALYST" and p.affiliation}),
        "operator_turns_filtered": sum(1 for p in passages if _looks_like_operator(p.text)),
        "speakers": len({p.speaker for p in passages}),
        "chars": sum(len(p.text) for p in passages),
    }
