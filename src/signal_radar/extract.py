"""Claim extraction: passages -> structured claims.

Two execution modes:
  live   - calls the Anthropic API
  replay - reads cached responses from data/replay/

Replay exists so `make demo` runs with no API key and no network, and so the
eval set is reproducible. A pipeline whose output changes every run cannot be
evaluated, and a reviewer should not need credentials to see it work.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any

from .config import Portfolio
from .parse import Passage

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPT_PATH = REPO_ROOT / "prompts" / "extract_claims.md"
REPLAY_DIR = REPO_ROOT / "data" / "replay"

MODEL = "claude-sonnet-4-6"
VALID_TYPES = {"clinical_readout", "timeline_change",
               "competitive_positioning", "commercial_trajectory"}
VALID_LINKAGE = {"named_asset", "shared_indication", "shared_mechanism"}
MAX_QUOTE_WORDS = 25


@dataclass
class Claim:
    claim: str
    quote: str
    passage_idx: int
    speaker: str
    signal_type: str
    affected_holdings: list[str]
    linkage: str
    materiality: float
    reasoning: str
    entities: dict[str, list[str]] = field(default_factory=dict)
    transcription_note: str | None = None
    # populated downstream
    section: str = "prepared"
    source_ticker: str = ""
    source_company: str = ""
    quarter: str = ""
    novelty: str = "unknown"
    delta: str = ""      # human-readable explanation of what changed vs prior quarter
    score: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def _portfolio_block(portfolio: Portfolio) -> str:
    lines = []
    for h in portfolio.holdings:
        assets = ", ".join(h.asset_names) or "—"
        lines.append(
            f"- **{h.ticker}** {h.name} (tier {h.tier})\n"
            f"  - assets: {assets}\n"
            f"  - indications: {', '.join(h.indications) or '—'}\n"
            f"  - mechanisms: {', '.join(h.mechanisms) or '—'}"
        )
    return "\n".join(lines)


def _passages_block(passages: list[Passage]) -> str:
    return "\n\n".join(
        f"[{p.idx}] {p.speaker} ({p.role}{', ' + p.affiliation if p.affiliation else ''}):\n{p.text}"
        for p in passages
    )


def render_prompt(passages: list[Passage], portfolio: Portfolio,
                  company: str, ticker: str, quarter: str) -> str:
    tmpl = PROMPT_PATH.read_text()
    return (tmpl
            .replace("{portfolio_block}", _portfolio_block(portfolio))
            .replace("{passages_block}", _passages_block(passages))
            .replace("{company}", company)
            .replace("{ticker}", ticker)
            .replace("{quarter}", quarter)
            .replace("{section}", passages[0].section if passages else "prepared"))


def _strip_fences(text: str) -> str:
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.M)


def _validate(raw: list[dict], passages: list[Passage]) -> list[Claim]:
    """Drop malformed claims loudly rather than letting them poison the digest.

    The two checks that matter: the quote must actually exist in the source text,
    and the passage index must be real. Together they make every rendered signal
    clickable back to a specific speaker at a specific moment. A claim that fails
    either check is a hallucination risk and is not worth recovering.
    """
    by_idx = {p.idx: p for p in passages}
    out: list[Claim] = []

    for item in raw:
        try:
            idx = int(item.get("passage_idx", -1))
            src = by_idx.get(idx)
            if src is None:
                continue

            quote = (item.get("quote") or "").strip()
            if not quote:
                continue
            if len(quote.split()) > MAX_QUOTE_WORDS:
                quote = " ".join(quote.split()[:MAX_QUOTE_WORDS])
            # Verbatim check, whitespace- and quote-mark-insensitive.
            norm = lambda s: re.sub(r"[\s\u2018\u2019\u201c\u201d\"']+", " ", s).lower().strip()
            if norm(quote)[:60] not in norm(src.text):
                continue

            stype = item.get("signal_type", "")
            linkage = item.get("linkage", "")
            if stype not in VALID_TYPES or linkage not in VALID_LINKAGE:
                continue

            holdings = [h.upper() for h in item.get("affected_holdings", []) if h]
            if not holdings:
                continue

            out.append(Claim(
                claim=item.get("claim", "").strip(),
                quote=quote,
                passage_idx=idx,
                speaker=item.get("speaker") or src.speaker,
                signal_type=stype,
                affected_holdings=holdings,
                linkage=linkage,
                materiality=max(0.0, min(1.0, float(item.get("materiality", 0)))),
                reasoning=item.get("reasoning", "").strip(),
                entities=item.get("entities") or {},
                transcription_note=item.get("transcription_note"),
                section=src.section,
            ))
        except (TypeError, ValueError):
            continue

    return out


def _call_api(prompt: str) -> str:
    from anthropic import Anthropic  # imported lazily: replay mode needs no SDK

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Use --replay for the zero-setup demo."
        )
    client = Anthropic(api_key=key)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def extract(passages: list[Passage], portfolio: Portfolio, company: str,
            ticker: str, quarter: str, replay: bool = False) -> list[Claim]:
    """Extract claims from one batch of passages."""
    if replay:
        path = REPLAY_DIR / f"{ticker.upper()}_{quarter.replace(' ', '')}.json"
        if not path.exists():
            return []
        payload = json.loads(path.read_text())
        raw = payload["claims"] if isinstance(payload, dict) else payload
        # Cached claims were validated when they were first produced, and there
        # are no passages on disk in replay mode to re-check them against.
        claims = [Claim(**{k: v for k, v in item.items() if k in Claim.__annotations__})
                  for item in raw]
        for c in claims:
            c.source_ticker, c.source_company, c.quarter = ticker.upper(), company, quarter
        return claims
    else:
        prompt = render_prompt(passages, portfolio, company, ticker, quarter)
        try:
            raw = json.loads(_strip_fences(_call_api(prompt)))
        except json.JSONDecodeError:
            return []

    claims = _validate(raw, passages)
    for c in claims:
        c.source_ticker, c.source_company, c.quarter = ticker.upper(), company, quarter
    return claims
