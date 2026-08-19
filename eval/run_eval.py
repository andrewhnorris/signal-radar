#!/usr/bin/env python3
"""Evaluate the ranker against a hand-labelled set.

There is no ground truth for "material signal". The honest substitute is a small
set labelled by hand, with the labelling rationale committed alongside so a
reader can disagree with a specific call rather than with an opaque number.

What this measures: whether the SCORING puts alert-worthy claims above the bar.
What it does not measure: whether extraction found everything worth finding.
That is the recall question, and 20 labelled rows cannot answer it — see the
README section on what this eval does not cover.

    python eval/run_eval.py
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from signal_radar.config import load_materiality, load_portfolio  # noqa: E402
from signal_radar.diff import classify_novelty  # noqa: E402
from signal_radar.extract import Claim  # noqa: E402
from signal_radar.score import score_all  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
LABELS = REPO / "eval" / "labeled_set.csv"
REPLAY = REPO / "data" / "replay"


def load_replay(ticker: str, quarter: str) -> list[Claim]:
    path = REPLAY / f"{ticker}_{quarter.replace(' ', '')}.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text())
    raw = payload["claims"] if isinstance(payload, dict) else payload
    claims = [Claim(**{k: v for k, v in c.items() if k in Claim.__annotations__})
              for c in raw]
    for c in claims:
        c.source_ticker, c.quarter = ticker, quarter
    return claims


def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def main() -> int:
    portfolio, cfg = load_portfolio(), load_materiality()

    labels = list(csv.DictReader(LABELS.open()))
    if not labels:
        print("No labels found.", file=sys.stderr)
        return 1

    q2 = load_replay("MDGL", "Q2 2026")
    q1 = load_replay("MDGL", "Q1 2026")
    scored = score_all(classify_novelty(q2, q1) + q1, portfolio, cfg)

    # Match labels to claims on (source, quarter, passage_idx).
    by_key = {(c.source_ticker, c.quarter, c.passage_idx): c for c in scored}
    rows, unmatched = [], []
    for lab in labels:
        key = (lab["source"], lab["quarter"], int(lab["passage_idx"]))
        claim = by_key.get(key)
        if claim is None:
            unmatched.append(lab)
            continue
        rows.append((lab, claim))

    # An unmatched row means the extractor produced no claim for a passage a
    # human labelled. For a `noise` row that is correct suppression. For an
    # `alert` or `watch` row it is a genuine miss, and the more damaging error.
    missed = [l for l in unmatched if l["label"] in ("alert", "watch")]
    suppressed = [l for l in unmatched if l["label"] == "noise"]

    print(f"Labelled rows: {len(labels)}   scored: {len(rows)}")
    print(f"Correctly suppressed (noise, no claim emitted): {len(suppressed)}")
    print(f"EXTRACTOR MISSES (alert/watch, no claim emitted): {len(missed)}")
    for l in missed:
        print(f"  ! {l['source']} {l['quarter']} p{l['passage_idx']} "
              f"[{l['label']}] {l['rationale']}")
    print()

    # --- performance at the configured threshold -------------------------
    thr = cfg["alert_threshold"]
    tp = sum(1 for l, c in rows if l["label"] == "alert" and c.score >= thr)
    fp = sum(1 for l, c in rows if l["label"] != "alert" and c.score >= thr)
    fn = sum(1 for l, c in rows if l["label"] == "alert" and c.score < thr)
    p, r, f1 = prf(tp, fp, fn)

    print(f"=== Alert threshold = {thr} ===")
    print(f"precision {p:.2f}   recall {r:.2f}   F1 {f1:.2f}   "
          f"(tp={tp} fp={fp} fn={fn})\n")

    # --- sweep ------------------------------------------------------------
    print("=== Threshold sweep ===")
    print(f"{'thr':>6} {'prec':>6} {'rec':>6} {'F1':>6} {'alerts':>7}")
    for t in [round(x * 0.1, 2) for x in range(5, 25)]:
        tp_ = sum(1 for l, c in rows if l["label"] == "alert" and c.score >= t)
        fp_ = sum(1 for l, c in rows if l["label"] != "alert" and c.score >= t)
        fn_ = sum(1 for l, c in rows if l["label"] == "alert" and c.score < t)
        p_, r_, f_ = prf(tp_, fp_, fn_)
        mark = "  <-- configured" if abs(t - thr) < 0.05 else ""
        print(f"{t:>6.2f} {p_:>6.2f} {r_:>6.2f} {f_:>6.2f} {tp_ + fp_:>7}{mark}")

    # --- errors, named ----------------------------------------------------
    print("\n=== False positives (fired, labelled below alert) ===")
    for l, c in sorted(rows, key=lambda x: -x[1].score):
        if l["label"] != "alert" and c.score >= thr:
            print(f"  [{c.score:.2f}] {l['label']:>5} | {c.claim[:78]}")
            print(f"         why not: {l['rationale']}")

    print("\n=== False negatives (labelled alert, did not fire) ===")
    for l, c in sorted(rows, key=lambda x: -x[1].score):
        if l["label"] == "alert" and c.score < thr:
            print(f"  [{c.score:.2f}] {c.claim[:78]}")
            print(f"         why it matters: {l['rationale']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
