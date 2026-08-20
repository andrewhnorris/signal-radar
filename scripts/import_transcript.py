#!/usr/bin/env python3
"""Import a transcript you have already obtained into the local cache.

Why this exists: the aggregator used to identify the seed transcripts blocks
automated requests (HTTP 403) and its terms prohibit programmatic reproduction
of site content. That is the correct outcome, not a bug to route around -
transcript text is licensed content, and a research system at a fund should
acquire it through a channel that permits storage.

So acquisition is deliberately split in two:

    scripts/import_transcript.py   you obtained the document; normalise it
    signal_radar/fetch.py          a licensed API, when one is configured

This script takes a file you saved from your browser (Cmd-S / Ctrl-S, or copy
the visible transcript into a .txt) and normalises it into the speaker-tagged
form the parser expects. Nothing it writes is committed - data/transcripts/ is
gitignored.

Usage:
    python scripts/import_transcript.py saved.html --ticker MDGL --quarter "Q2 2026"
    python scripts/import_transcript.py saved.txt  --ticker IVA  --quarter "Q4 2025"
    python scripts/import_transcript.py --list
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TRANSCRIPT_DIR = REPO / "data" / "transcripts"

# Site chrome that appears before the transcript body on aggregator pages.
# Everything up to the first of these markers is dropped.
_BODY_START = re.compile(
    r"(full transcript|Conference Call Participants|Company Participants|"
    r"Operator\s*[:：]|Good (?:day|morning|afternoon)[, ])",
    re.I,
)
# Everything from here on is comments, disclaimers, and market tickers.
_BODY_END = re.compile(
    r"(This article was generated with the support of AI|"
    r"Latest comments|Risk Disclosure|Comment Guidelines|"
    r"Most Popular Articles|you may now (?:all )?disconnect)",
    re.I,
)

# Speaker forms seen across vendors, normalised to "**Name, Title, Company**:".
_SPEAKER_FORMS = [
    # Already bold-tagged (investing.com), optional diarization digit suffix.
    re.compile(r"^\*\*([^*]{3,90})\*\*\d*\s*[:：]\s*(.*)$"),
    # Seeking Alpha / Insider Monkey: "Name - Title, Company" then text.
    re.compile(r"^([A-Z][\w.'’\- ]{2,40})\s+[-–]\s+([^:]{3,70})[:：]\s*(.*)$"),
    # Plain "Name, Title, Company: text"
    re.compile(r"^([A-Z][\w.'’\- ]{2,40},[^:：]{3,70})[:：]\s*(.*)$"),
]


def strip_html(raw: str) -> str:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("beautifulsoup4 required for HTML input: pip install beautifulsoup4",
              file=sys.stderr)
        raise SystemExit(1)

    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside",
                     "form", "table", "iframe", "noscript"]):
        tag.decompose()

    # Preserve bold speaker labels as markdown so the parser can see them.
    for tag in soup.find_all(["strong", "b"]):
        if tag.get_text(strip=True):
            tag.replace_with(f"**{tag.get_text(strip=True)}**")

    text = soup.get_text("\n")
    # Block-level tags put a newline between the bold speaker label and the
    # text that follows it, leaving "**Name**" and ": said something" on
    # separate lines. Rejoin them before any speaker matching happens.
    text = re.sub(r"\*\*[ \t]*\n[ \t]*(\d*\s*[:：])", r"**\1", text)
    return re.sub(r"[ \t]+", " ", text)


def trim_to_body(text: str) -> str:
    start = _BODY_START.search(text)
    if start:
        text = text[start.start():]
    end = _BODY_END.search(text)
    if end:
        text = text[: end.start()]
    return text


def normalise_speakers(text: str) -> tuple[str, int]:
    """Rewrite speaker lines into one consistent form. Returns (text, count)."""
    out, hits = [], 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        for pat in _SPEAKER_FORMS:
            m = pat.match(line)
            if m:
                groups = m.groups()
                who = ", ".join(g.strip() for g in groups[:-1] if g and g.strip())
                body = groups[-1].strip()
                out.append(f"**{who}**: {body}")
                hits += 1
                break
        else:
            out.append(line)
    return "\n".join(out), hits


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", nargs="?", type=Path, help=".html or .txt you saved")
    ap.add_argument("--ticker")
    ap.add_argument("--quarter", help='e.g. "Q2 2026"')
    ap.add_argument("--list", action="store_true", help="show what is cached")
    args = ap.parse_args(argv)

    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)

    if args.list:
        files = sorted(p for p in TRANSCRIPT_DIR.glob("*.txt"))
        if not files:
            print("Cache is empty. Import a transcript, or run `make demo`.")
        for p in files:
            print(f"  {p.name:<28} {p.stat().st_size:>8,} bytes")
        return 0

    if not (args.source and args.ticker and args.quarter):
        ap.error("source, --ticker and --quarter are required (or use --list)")
    if not args.source.exists():
        print(f"No such file: {args.source}", file=sys.stderr)
        return 1

    raw = args.source.read_text(errors="replace")
    text = strip_html(raw) if args.source.suffix.lower() in {".html", ".htm"} else raw
    text = trim_to_body(text)
    text, hits = normalise_speakers(text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    dest = TRANSCRIPT_DIR / f"{args.ticker.upper()}_{args.quarter.replace(' ', '')}.txt"
    dest.write_text(text)

    print(f"Wrote {dest}  ({len(text):,} chars, {hits} speaker turns normalised)")
    if hits < 10:
        print("\n  ! Only a few speaker turns were recognised. Check the file "
              "actually contains the transcript body rather than a summary or "
              "a paywall stub, then inspect the head of the output:")
        print(f"    head -40 {dest}")
    else:
        print("\nNow run:  make run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
