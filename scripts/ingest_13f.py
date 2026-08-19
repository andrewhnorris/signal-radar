#!/usr/bin/env python3
"""Ingest a Form 13F-HR information table and emit a ranked portfolio seed.

This is the answer to "defining important is part of the problem". The brief
points at 13F, so this goes and reads one rather than asserting what is in it.

What 13F actually gives you, per position:
    issuer name, CUSIP, class, market value, share count, discretion, voting

What it does NOT give you, and therefore what this script cannot rank on:
    - shares outstanding, so ownership % needs a second source
    - therapeutic area, mechanism, indication
    - catalyst dates
    - anything about a private, venture, non-US or derivative position

So the output is a SEED, not a portfolio. It ranks on what 13F can support
(value, weight, concentration) and emits explicit TODO fields for the judgement
that a filing cannot supply. The finished config is a curated artefact.

Also worth knowing: `value` is reported in whole dollars for periods after
Q4 2022 and in THOUSANDS before that. Getting this wrong silently changes every
number by 1000x, so the scale is detected and reported rather than assumed.

Usage:
    python scripts/ingest_13f.py --xml data/13f/rtw_2026q1.xml
    python scripts/ingest_13f.py --xml <path> --top 10 --out config/portfolio.seed.yaml
    python scripts/ingest_13f.py --cik 1493215          # requires network
"""
from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EDGAR_UA = "signal-radar research prototype (contact: analyst@example.com)"

# 13F information tables are namespaced, and the namespace URI changes between
# EDGAR releases. Matching on the local tag name is version-proof.
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


@dataclass
class Position:
    issuer: str
    cusip: str
    title: str = ""
    value: float = 0.0          # normalised to dollars
    shares: float = 0.0
    classes: set[str] = field(default_factory=set)

    @property
    def key(self) -> str:
        # CUSIP issuer prefix: first 6 chars identify the issuer, last 3 the
        # issue. Aggregating on the prefix merges share classes and any
        # options/notes lines into one economic position.
        return self.cusip[:6] if len(self.cusip) >= 6 else self.issuer.upper()


def parse_info_table(xml_text: str) -> list[Position]:
    root = ET.fromstring(xml_text)
    rows: list[Position] = []

    for node in root.iter():
        if _local(node.tag) != "infoTable":
            continue
        f: dict[str, str] = {}
        for child in node.iter():
            name = _local(child.tag)
            if child.text and child.text.strip():
                f.setdefault(name, child.text.strip())
        try:
            rows.append(Position(
                issuer=f.get("nameOfIssuer", "UNKNOWN"),
                cusip=f.get("cusip", "").strip().upper(),
                title=f.get("titleOfClass", ""),
                value=float(f.get("value", 0) or 0),
                shares=float(f.get("sshPrnamt", 0) or 0),
                classes={f.get("titleOfClass", "")},
            ))
        except ValueError:
            continue

    if not rows:
        raise ValueError("No <infoTable> entries found. Is this the information "
                         "table XML rather than the cover page (primary_doc.xml)?")
    return rows


def detect_value_scale(rows: list[Position]) -> tuple[float, str]:
    """Return (multiplier, explanation).

    Pre-2023 filings report value in thousands. A total under ~$50m across a
    large filer is the tell that the figures are thousands, not dollars.
    """
    total = sum(r.value for r in rows)
    if total and total < 50_000_000 and len(rows) > 20:
        return 1000.0, f"raw total ${total:,.0f} looks like THOUSANDS - scaled x1000"
    return 1.0, f"raw total ${total:,.0f} treated as whole dollars"


def aggregate(rows: list[Position], scale: float) -> list[Position]:
    merged: dict[str, Position] = {}
    for r in rows:
        p = merged.get(r.key)
        if p is None:
            merged[r.key] = Position(issuer=r.issuer, cusip=r.cusip, title=r.title,
                                     value=r.value * scale, shares=r.shares,
                                     classes=set(r.classes))
        else:
            p.value += r.value * scale
            p.shares += r.shares
            p.classes |= r.classes
    return sorted(merged.values(), key=lambda p: p.value, reverse=True)


def slug(name: str) -> str:
    """Best-effort ticker placeholder. 13F carries CUSIP, not ticker.

    Deliberately left as a placeholder rather than guessed: mapping CUSIP to
    ticker needs a reference dataset, and a wrong ticker silently mislabels a
    position for the rest of the pipeline.
    """
    cleaned = re.sub(r"\b(INC|CORP|CO|LTD|PLC|SA|NV|AG|HOLDINGS|GROUP|THE|"
                     r"CLASS|COM|ADR|PHARMACEUTICALS?|THERAPEUTICS?)\b", "",
                     name.upper())
    words = [w for w in re.split(r"[^A-Z]+", cleaned) if w]
    return (words[0][:4] if words else "TBD")


def render_seed(positions: list[Position], total: float, meta: dict) -> str:
    lines = [
        "# GENERATED by scripts/ingest_13f.py - a SEED, not a finished config.",
        "#",
        "# Ranked on what 13F can support: market value and weight in the",
        "# disclosed book. Every `TODO` below is judgement a filing cannot",
        f"# supply and an analyst must fill in.",
        "#",
        f"# Source: {meta.get('source', 'unknown')}",
        f"# Period:  {meta.get('period', 'unknown')}",
        f"# Positions: {meta.get('n_positions', 0)}   "
        f"Disclosed equity value: ${total:,.0f}",
        "#",
        "# Known limits of this basis:",
        "#   - filed 45 days after period end; stale by construction",
        "#   - long US-listed equity only; excludes private, venture, non-US,",
        "#     short and derivative exposure",
        "#   - CUSIP is authoritative here; ticker is a PLACEHOLDER to replace",
        "",
        "holdings:",
    ]
    for i, p in enumerate(positions, 1):
        weight = 100 * p.value / total if total else 0
        tier = 1 if weight >= 5.0 else 2
        lines += [
            f"  # {i}. {p.issuer}  |  ${p.value:,.0f}  |  {weight:.2f}% of book",
            f"  - ticker: {slug(p.issuer)}   # TODO verify - CUSIP {p.cusip}",
            f"    name: {p.issuer.title()}",
            f"    cusip: '{p.cusip}'",
            f"    value_usd: {int(p.value)}",
            f"    weight_pct: {weight:.2f}",
            f"    tier: {tier}   # >=5% of book -> tier 1; review by hand",
            f"    rationale: TODO   # why this name matters beyond its size",
            f"    indications: []   # TODO",
            f"    mechanisms: []    # TODO - drives shared_mechanism linkage",
            f"    catalysts: []     # TODO - near-term events drive sensitivity",
            f"    named_competitors: []  # TODO",
            "",
        ]
    return "\n".join(lines)


def fetch_from_edgar(cik: str) -> tuple[str, dict]:
    """Pull the most recent 13F-HR information table for a CIK."""
    import json
    import urllib.request

    def get(url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": EDGAR_UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()

    cik10 = str(int(cik)).zfill(10)
    subs = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik10}.json"))
    recent = subs["filings"]["recent"]

    idx = next((i for i, f in enumerate(recent["form"]) if f == "13F-HR"), None)
    if idx is None:
        raise ValueError(f"No 13F-HR found for CIK {cik}")

    acc = recent["accessionNumber"][idx].replace("-", "")
    period = recent["reportDate"][idx]
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}"

    listing = get(f"{base}/").decode("utf-8", "replace")
    # The information table is the XML that is not the cover page.
    xmls = [m for m in re.findall(r'href="[^"]*?/([^/"]+\.xml)"', listing)
            if "primary_doc" not in m.lower()]
    if not xmls:
        raise ValueError(f"No information table XML found at {base}")

    return get(f"{base}/{xmls[0]}").decode("utf-8", "replace"), {
        "source": f"EDGAR CIK {cik}, accession {recent['accessionNumber'][idx]}",
        "period": period,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--xml", type=Path, help="local 13F information table XML")
    src.add_argument("--cik", help="fetch latest 13F-HR from EDGAR (needs network)")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--out", type=Path, help="write seed YAML here")
    args = ap.parse_args(argv)

    if args.xml:
        if not args.xml.exists():
            print(f"No such file: {args.xml}", file=sys.stderr)
            return 1
        xml_text = args.xml.read_text()
        meta = {"source": str(args.xml), "period": "see filing"}
    else:
        try:
            xml_text, meta = fetch_from_edgar(args.cik)
        except Exception as exc:  # noqa: BLE001
            print(f"EDGAR fetch failed: {exc}\n"
                  f"Download the information table XML and pass --xml instead.",
                  file=sys.stderr)
            return 1

    rows = parse_info_table(xml_text)
    scale, scale_note = detect_value_scale(rows)
    positions = aggregate(rows, scale)
    total = sum(p.value for p in positions)
    meta["n_positions"] = len(positions)

    print(f"Parsed {len(rows)} info table rows -> {len(positions)} issuers")
    print(f"Value scale: {scale_note}")
    print(f"Disclosed equity book: ${total:,.0f}\n")

    top = positions[: args.top]
    cum = 0.0
    print(f"{'#':>3} {'issuer':<34} {'value':>16} {'wt%':>7} {'cum%':>7}")
    for i, p in enumerate(top, 1):
        w = 100 * p.value / total if total else 0
        cum += w
        print(f"{i:>3} {p.issuer[:34]:<34} ${p.value:>15,.0f} {w:>6.2f}% {cum:>6.2f}%")

    print(f"\nTop {len(top)} = {cum:.1f}% of the disclosed book.")
    print("Concentration is the argument for ranking on weight, not just value.\n")
    print("13F cannot supply: shares outstanding (ownership %), therapeutic area,")
    print("mechanism, or catalyst dates. Those are TODO in the seed and must be")
    print("filled in by hand - see README on the portfolio config as a curated artefact.")

    seed = render_seed(top, total, meta)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(seed)
        print(f"\nSeed written -> {args.out}")
    else:
        print("\n--- seed (pass --out to write) ---")
        print(seed[:1200] + ("\n..." if len(seed) > 1200 else ""))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
