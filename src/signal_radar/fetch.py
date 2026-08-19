"""Transcript acquisition.

Design decision worth stating plainly: we do NOT scrape ten companies' investor
relations pages. Verified across the watchlist, IR pages publish webcast players
and PDF slide decks - not transcript text. Building ten bespoke scrapers to
extract text that is not there is the single easiest way to spend a whole build
on plumbing and ship nothing.

Instead we pull from a transcript aggregator with a consistent speaker-tag
format, and treat the source as swappable. In production this is a paid feed
(AlphaSense, Quartr, Sentieo) with an SLA and licensing that permits storage.

Transcript text is NOT committed to this repo - it is third-party licensed
content. Fetched files land in data/transcripts/, which is gitignored.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TRANSCRIPT_DIR = REPO_ROOT / "data" / "transcripts"

UA = "Mozilla/5.0 (compatible; signal-radar research prototype)"


@dataclass
class TranscriptRef:
    ticker: str
    company: str
    quarter: str
    url: str

    @property
    def path(self) -> Path:
        return TRANSCRIPT_DIR / f"{self.ticker}_{self.quarter.replace(' ', '')}.txt"


# Seed set for the demo. Kept as an explicit manifest rather than a search
# crawl: for a prototype, a reviewer needs to know exactly which four documents
# produced the output, and a crawl makes that unreproducible.
MANIFEST: list[TranscriptRef] = [
    TranscriptRef("MDGL", "Madrigal Pharmaceuticals", "Q2 2026", ""),
    TranscriptRef("MDGL", "Madrigal Pharmaceuticals", "Q1 2026", ""),
    TranscriptRef("IVA",  "Inventiva",                "Q2 2026", ""),
    TranscriptRef("NVO",  "Novo Nordisk",             "Q2 2026", ""),
]


def _clean(html: str) -> str:
    """Strip site chrome, keep the transcript body."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    text = soup.get_text("\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fetch_one(ref: TranscriptRef, force: bool = False) -> Path | None:
    """Fetch and cache one transcript. Returns None if unavailable."""
    if ref.path.exists() and not force:
        return ref.path
    if not ref.url:
        return None

    import requests

    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        resp = requests.get(ref.url, headers={"User-Agent": UA}, timeout=30)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - surface, do not crash the batch
        print(f"  ! {ref.ticker} {ref.quarter}: {exc}")
        return None

    ref.path.write_text(_clean(resp.text))
    return ref.path


def fetch_all(force: bool = False) -> list[TranscriptRef]:
    """Fetch everything in the manifest. Missing entries are reported, not fatal."""
    got = []
    for ref in MANIFEST:
        if fetch_one(ref, force=force):
            got.append(ref)
            print(f"  + {ref.ticker} {ref.quarter}")
        else:
            print(f"  - {ref.ticker} {ref.quarter}: no URL in manifest or fetch failed")
    return got


def available() -> list[TranscriptRef]:
    """Manifest entries whose text is already on disk."""
    return [r for r in MANIFEST if r.path.exists()]
