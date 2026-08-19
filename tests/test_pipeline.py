"""Smoke tests: the parser and the scorer are where silent breakage hides."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from signal_radar.config import load_materiality, load_portfolio
from signal_radar.parse import parse_transcript, summarize

SAMPLE = """
**Operator**: Good morning and welcome to the call. Please stand by while we compile the roster.
**Jane Doe, Chief Executive Officer, Example Bio**: Thanks. Revenue grew 40% this quarter and our Phase 3 remains on track for a 2027 readout.
**Operator**: Our first question comes from the line of Sam Analyst of Big Bank.
**Sam Analyst, Analyst, Big Bank**: Can you narrow the readout timing at all, or is 2027 still the guide you are comfortable with?
**Jane Doe, Chief Executive Officer, Example Bio**: We are tracking toward 2027 and will provide more precision when we have it.
"""


def test_parse_splits_prepared_and_qa():
    ps = parse_transcript(SAMPLE)
    assert [p.section for p in ps] == ["prepared", "qa", "qa"]


def test_parse_drops_operator_and_tags_roles():
    ps = parse_transcript(SAMPLE)
    assert all(p.role != "OPERATOR" for p in ps)
    assert ps[0].role == "CEO"
    assert ps[1].role == "ANALYST" and ps[1].affiliation == "Big Bank"


def test_summarize_counts():
    s = summarize(parse_transcript(SAMPLE))
    assert s["prepared"] == 1 and s["qa"] == 2 and s["analysts"] == 1


def test_configs_load_and_validate():
    p, cfg = load_portfolio(), load_materiality()
    assert len(p.holdings) >= 10
    assert p.by_ticker("MDGL").tier == 1
    assert "resmetirom" in p.by_ticker("MDGL").asset_names
    assert cfg["alert_threshold"] > cfg["watch_threshold"]


if __name__ == "__main__":
    # Runnable without pytest installed: `python tests/test_pipeline.py`
    import traceback
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception:
            failed += 1
            print(f"  FAIL  {name}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    raise SystemExit(1 if failed else 0)
