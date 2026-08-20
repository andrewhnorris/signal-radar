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

ACQUISITION STATUS, verified 19 Aug 2026
----------------------------------------
The aggregator used to identify the seed transcripts returns HTTP 403 to
automated requests, and its terms prohibit programmatic reproduction of site
content. We do not work around that: spoofing a user agent to defeat bot
detection is not a data pipeline a fund should depend on, and the licensing
question does not go away just because the request succeeds.

So the manifest URLs below are PROVENANCE - they record exactly which document
produced each cached extraction, and remain checkable by hand. They are not a
supported automated path.

Supported paths, in order of preference:

  1. Licensed API. Set TRANSCRIPT_API_BASE and TRANSCRIPT_API_KEY. Several
     vendors (Financial Modeling Prep, API Ninjas, Quartr, AlphaSense) sell
     earnings-transcript endpoints whose terms permit storage. This is what
     production should use.
  2. Manual import. Save the page in a browser, then
     `python scripts/import_transcript.py saved.html --ticker MDGL
      --quarter "Q2 2026"`. Adequate for a prototype and fully above board.
  3. SEC EDGAR. Some issuers file prepared remarks as an 8-K Ex-99. Public
     domain, and EDGAR permits automated access with an identifying UA. Covers
     prepared remarks only - never the Q&A, which is where most of the signal
     in this system comes from.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TRANSCRIPT_DIR = REPO_ROOT / "data" / "transcripts"

UA = "signal-radar research prototype (contact: analyst@example.com)"

# Optional licensed-API provider. Configure both to enable `make fetch`.
API_BASE = os.environ.get("TRANSCRIPT_API_BASE", "")
API_KEY = os.environ.get("TRANSCRIPT_API_KEY", "")


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
# crawl: for a prototype, a reviewer needs to know exactly which documents
# produced the output, and a crawl makes that unreproducible.
#
# Note on cadence, discovered while assembling this list: Inventiva is a French
# issuer and reports SEMI-ANNUALLY, not quarterly. There is no "IVA Q2 2026"
# call - the most recent full earnings call is FY2025, held 31 March 2026, and
# the next is scheduled for 25 September 2026. Any scheduler that assumes four
# calls a year per name will silently under-cover every European holding. The
# quarter label below is the company's own reporting period, not a calendar
# quarter we imposed.
MANIFEST: list[TranscriptRef] = [
    TranscriptRef(
        "MDGL", "Madrigal Pharmaceuticals", "Q2 2026",
        "https://www.investing.com/news/transcripts/"
        "earnings-call-transcript-madrigal-pharmaceuticals-posts-strong-q2-2026-"
        "sales-shares-fall-premarket-93CH-4824658",
    ),
    TranscriptRef(
        "MDGL", "Madrigal Pharmaceuticals", "Q1 2026",
        "https://www.investing.com/news/transcripts/"
        "earnings-call-transcript-madrigal-pharmaceuticals-q1-2026-surprises-"
        "with-earnings-beat-93CH-4663512",
    ),
    TranscriptRef(
        # Semi-annual reporter - FY2025 results call, 31 March 2026.
        # Contains the NATiV3 topline guide being narrowed to Q4 2026.
        "IVA", "Inventiva", "Q4 2025",
        "https://www.investing.com/news/transcripts/"
        "earnings-call-transcript-inventiva-q4-2025-miss-eps-stock-dips-"
        "93CH-4590585",
    ),
    TranscriptRef(
        # The haystack case: MASH commentary buried in a mega-cap call
        # dominated by obesity and diabetes, post-Akero acquisition.
        "NVO", "Novo Nordisk", "Q2 2026",
        "https://www.investing.com/news/transcripts/"
        "earnings-call-transcript-novo-nordisk-beats-q2-2026-estimates-"
        "shares-rise-premarket-93CH-4811192",
    ),
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
    """Fetch one transcript via a configured licensed API. None if unavailable.

    Deliberately does NOT fall back to scraping the manifest URL. A silent
    fallback would make the licensing posture depend on whether an env var
    happened to be set, which is exactly the kind of thing nobody notices
    until it matters.
    """
    if ref.path.exists() and not force:
        return ref.path
    if not (API_BASE and API_KEY):
        return None

    import requests

    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        resp = requests.get(
            API_BASE,
            params={"symbol": ref.ticker, "period": ref.quarter, "apikey": API_KEY},
            headers={"User-Agent": UA},
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - surface, do not crash the batch
        print(f"  ! {ref.ticker} {ref.quarter}: {exc}")
        return None

    body = resp.text
    ref.path.write_text(_clean(body) if "<" in body[:200] else body)
    return ref.path


def fetch_all(force: bool = False) -> list[TranscriptRef]:
    """Fetch everything in the manifest. Missing entries are reported, not fatal."""
    if not (API_BASE and API_KEY):
        print("  No licensed transcript API configured "
              "(set TRANSCRIPT_API_BASE and TRANSCRIPT_API_KEY).\n")
        cached = [r for r in MANIFEST if r.path.exists()]
        for ref in MANIFEST:
            mark = "+" if ref.path.exists() else "-"
            state = "cached" if ref.path.exists() else "not available"
            print(f"  {mark} {ref.ticker} {ref.quarter}: {state}")
        print("\n  To import a transcript you already have:")
        print("    python scripts/import_transcript.py saved.html "
              "--ticker MDGL --quarter \"Q2 2026\"")
        print("  Manifest URLs are recorded in this file as provenance.")
        print("  Or run `make demo` - cached extraction, no transcripts needed.")
        return cached

    got = []
    for ref in MANIFEST:
        if fetch_one(ref, force=force):
            got.append(ref)
            print(f"  + {ref.ticker} {ref.quarter}")
        else:
            print(f"  - {ref.ticker} {ref.quarter}: fetch failed")
    return got


def available() -> list[TranscriptRef]:
    """Manifest entries whose text is already on disk."""
    return [r for r in MANIFEST if r.path.exists()]
