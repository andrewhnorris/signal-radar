"""Pipeline entrypoint.

    python -m signal_radar.cli run --replay      # zero-setup demo
    python -m signal_radar.cli fetch             # populate data/transcripts/
    python -m signal_radar.cli run               # live, needs ANTHROPIC_API_KEY
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from . import fetch as fetch_mod
from .config import load_materiality, load_portfolio
from .diff import classify_novelty, dropped_topics
from .extract import Claim, extract
from .parse import chunk, parse_transcript, summarize
from .report import render_digest
from .score import partition, score_all

REPO_ROOT = Path(__file__).resolve().parents[2]

# Known blind spots, surfaced in every digest. A monitoring system that cannot
# say what it did not look at invites false confidence.
COVERAGE_GAPS = [
    "Novo Nordisk MASH commentary — Akero/efruxifermin now sits inside a "
    "mega-cap call dominated by obesity and diabetes; low signal-to-noise, "
    "needs section-targeted retrieval",
    "Investor days and medical conferences (AASLD, EASL) — not earnings calls, "
    "different format, not yet ingested",
    "Non-US listings and private holdings — outside 13F, outside this watchlist",
]


def _load_claims(ticker: str, quarter: str) -> list[Claim]:
    """Load a prior quarter's claims from the run cache, for QoQ diffing."""
    path = REPO_ROOT / "out" / "claims" / f"{ticker}_{quarter.replace(' ', '')}.json"
    if not path.exists():
        return []
    return [Claim(**c) for c in json.loads(path.read_text())]


def _save_claims(ticker: str, quarter: str, claims: list[Claim]) -> None:
    d = REPO_ROOT / "out" / "claims"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{ticker}_{quarter.replace(' ', '')}.json").write_text(
        json.dumps([c.to_dict() for c in claims], indent=2)
    )


def _sort_key(quarter: str) -> tuple[int, int]:
    """Chronological order. Diffing is only meaningful if the prior quarter has
    already been processed and cached when the current quarter runs."""
    try:
        q, y = quarter.split()
        return (int(y), int(q[1]))
    except (ValueError, IndexError):
        return (0, 0)


def _prior_quarter(quarter: str) -> str:
    """Q2 2026 -> Q1 2026; Q1 2026 -> Q4 2025."""
    try:
        q, y = quarter.split()
        n, year = int(q[1]), int(y)
        return f"Q4 {year - 1}" if n == 1 else f"Q{n - 1} {year}"
    except (ValueError, IndexError):
        return ""


def cmd_run(args: argparse.Namespace) -> int:
    portfolio = load_portfolio()
    cfg = load_materiality()

    refs = fetch_mod.available()
    if args.replay and not refs:
        # Replay does not need transcript text on disk - cached claims already
        # carry their passage metadata. Fall back to the manifest.
        refs = fetch_mod.MANIFEST

    if not refs:
        print("No transcripts available. Run `make fetch` first, "
              "or `make demo` for the cached demo.", file=sys.stderr)
        return 1

    # Oldest first, so each quarter has its predecessor cached when it runs.
    refs = sorted(refs, key=lambda r: (r.ticker, _sort_key(r.quarter)))

    # Only the most recent quarter per ticker reaches the digest. Earlier
    # quarters are processed as the diff baseline, not reported as news — the
    # digest answers "what happened since last time", not "what was ever said".
    latest: dict[str, tuple[int, int]] = {}
    for r in refs:
        k = _sort_key(r.quarter)
        if k > latest.get(r.ticker, (0, 0)):
            latest[r.ticker] = k

    all_claims: list[Claim] = []
    calls_processed: list[dict] = []
    dropped: dict[str, list[str]] = defaultdict(list)

    for ref in refs:
        is_current = _sort_key(ref.quarter) == latest[ref.ticker]
        print(f"[{ref.ticker} {ref.quarter}] processing...")

        passages, stats = [], {}
        if ref.path.exists():
            passages = parse_transcript(ref.path.read_text())
            stats = summarize(passages)
            print(f"  parsed: {stats['passages']} passages "
                  f"({stats['prepared']} prepared / {stats['qa']} Q&A), "
                  f"{stats['analysts']} analysts")
            if stats["qa"] == 0:
                print("  ! WARNING: no Q&A section detected — check parse markers")

        claims: list[Claim] = []
        if args.replay:
            claims = extract([], portfolio, ref.company, ref.ticker, ref.quarter, replay=True)
        else:
            for batch in chunk(passages):
                claims += extract(batch, portfolio, ref.company, ref.ticker,
                                  ref.quarter, replay=False)

        prior = _load_claims(ref.ticker, _prior_quarter(ref.quarter))
        claims = classify_novelty(claims, prior)
        if prior:
            gone = dropped_topics(claims, prior)
            if gone:
                dropped[ref.ticker] = gone

        _save_claims(ref.ticker, ref.quarter, claims)
        if is_current:
            all_claims += claims
            calls_processed.append({"ticker": ref.ticker, "quarter": ref.quarter,
                                    "stats": stats, "claims": len(claims)})
        print(f"  claims: {len(claims)}"
              f"{'' if is_current else '  (baseline only — not reported)'}")

    scored = score_all(all_claims, portfolio, cfg)
    parts = partition(scored, cfg)

    digest = render_digest(parts, portfolio, calls_processed, dict(dropped), COVERAGE_GAPS)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(digest)

    print(f"\n{len(parts['alerts'])} alert(s), {len(parts['watch'])} watch, "
          f"{len(parts['archive'])} archived")
    print(f"digest -> {out_path}")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    print("Fetching transcripts into data/transcripts/ (gitignored)...")
    got = fetch_mod.fetch_all(force=args.force)
    print(f"\n{len(got)}/{len(fetch_mod.MANIFEST)} available")
    if not got:
        print("\nNo URLs in the manifest. Populate MANIFEST in "
              "src/signal_radar/fetch.py, or use `make demo`.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="signal-radar",
                                 description="Competitor call monitoring for a concentrated life sciences book.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="run the pipeline and render a digest")
    run.add_argument("--replay", action="store_true",
                     help="use cached model output; no API key or network required")
    run.add_argument("--out", default="out/digest.md")
    run.set_defaults(func=cmd_run)

    f = sub.add_parser("fetch", help="download transcripts into the local cache")
    f.add_argument("--force", action="store_true")
    f.set_defaults(func=cmd_fetch)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
