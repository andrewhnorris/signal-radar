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


def test_alias_map_resolves_renamed_asset():
    from signal_radar.config import load_aliases
    a = load_aliases()
    # The live false positive this map was built to fix.
    assert a.canonical("ARO-PNPLA3") == a.canonical("MGL-0795")
    assert a.canonical("Rezdiffra") == a.canonical("resmetirom")
    assert a.canonical("NASH") == a.canonical("MASH")
    assert a.canonical("Wegovy") == "semaglutide"
    # Unknown terms pass through rather than being silently dropped.
    assert a.canonical("not-a-real-drug") == "not-a-real-drug"


def test_renamed_asset_not_reported_as_dropped():
    from signal_radar.diff import dropped_topics
    from signal_radar.extract import Claim

    def mk(drug):
        return Claim(claim="x", quote="x", passage_idx=1, speaker="s",
                     signal_type="clinical_readout", affected_holdings=["MDGL"],
                     linkage="named_asset", materiality=0.5, reasoning="r",
                     entities={"drugs": [drug]})

    assert dropped_topics([mk("MGL-0795")], [mk("ARO-PNPLA3")]) == []
    assert dropped_topics([mk("MGL-0795")], [mk("ervogastat")]) == ["ervogastat"]


def test_13f_parses_and_ranks():
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "scripts"))
    from ingest_13f import aggregate, detect_value_scale, parse_info_table

    xml = (root / "data" / "13f" / "sample_information_table.xml").read_text()
    rows = parse_info_table(xml)
    assert len(rows) == 15
    scale, _ = detect_value_scale(rows)
    positions = aggregate(rows, scale)
    assert positions[0].issuer.startswith("MADRIGAL")
    # Ranked descending by value.
    assert all(positions[i].value >= positions[i + 1].value
               for i in range(len(positions) - 1))


# Real vendor failure mode, observed in the Inventiva FY2025 transcript: the
# operator's turns are attributed to an analyst with a numeric suffix, and the
# same name is reused for several different speakers.
MISLABELLED = """
**Anna Kripa, Analyst, Truist Securities**0: Good day, and thank you for standing by. Welcome to the call. At this time, all participants are in listen-only mode. To ask a question you will need to press star one and one.
**Andrew Obenshain, Chief Executive Officer, Inventiva**: Thank you. Today we are updating the expected timing of our top-line readout to Q4 2026, reflecting disciplined sequencing of our clinical milestones.
**Anna Kripa, Analyst, Truist Securities**0: Our next question comes from the line of Ritu Baral from TD Cowen. Please go ahead.
**Anna Kripa, Analyst, Truist Securities**2: Good morning, I want to drill down on final powering and what effect size that powering assumes for the primary combined endpoint.
"""


def test_operator_detected_by_content_not_label():
    from signal_radar.parse import parse_transcript
    ps = parse_transcript(MISLABELLED)
    # Both mislabelled operator turns must be dropped despite the analyst label.
    assert len(ps) == 2, [p.text[:40] for p in ps]
    assert not any("press star one" in p.text for p in ps)
    assert not any("next question comes from" in p.text.lower() for p in ps)


def test_numeric_speaker_suffix_stripped():
    from signal_radar.parse import parse_transcript
    ps = parse_transcript(MISLABELLED)
    assert all(not p.speaker[-1].isdigit() for p in ps)
    assert "Anna Kripa" in {p.speaker for p in ps}


def test_qa_flips_on_next_question_not_only_first():
    """Some operators open Q&A with 'our next question comes from'."""
    from signal_radar.parse import parse_transcript
    doc = (
        "**Jane Doe, Chief Executive Officer, Example Bio**: Net sales grew 71% "
        "and the Phase 3 remains on track for a 2027 readout this year.\n"
        "**Operator**: Our next question comes from the line of Sam Analyst "
        "from Big Bank. Please go ahead.\n"
        "**Sam Analyst, Analyst, Big Bank**: Can you narrow the readout timing, "
        "or is 2027 still the guide you are comfortable with today?\n"
    )
    ps = parse_transcript(doc)
    assert [p.section for p in ps] == ["prepared", "qa"], [(p.speaker, p.section) for p in ps]


def test_import_script_normalises_saved_html(tmp_path=None):
    """The manual-import path must produce text the parser can actually read."""
    import sys
    from pathlib import Path as _P
    root = _P(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "scripts"))
    from import_transcript import normalise_speakers, strip_html, trim_to_body
    from signal_radar.parse import parse_transcript

    html = (
        "<html><body><nav>Markets</nav>"
        "<h2>Full transcript - Example Bio (EXBI) Q2 2026:</h2>"
        "<p><strong>Operator</strong>: Good day. Please stand by. All "
        "participants are in listen-only mode.</p>"
        "<p><strong>Jane Doe, Chief Executive Officer, Example Bio</strong>: "
        "Net sales were $364 million, up 71% year over year in the quarter.</p>"
        "<p>Risk Disclosure: Trading involves high risks.</p></body></html>"
    )
    text, hits = normalise_speakers(trim_to_body(strip_html(html)))
    assert hits >= 2, text
    ps = parse_transcript(text)
    # Operator dropped, CEO kept with the right role.
    assert len(ps) == 1 and ps[0].role == "CEO", [(p.speaker, p.role) for p in ps]
    assert "Risk Disclosure" not in text


def test_persisted_claims_carry_scores():
    """The archive is the retune surface. Claims were being written before
    scoring, so every score on disk was 0.0 and the below-threshold archive the
    README leans on for recall was unusable."""
    import json, subprocess, tempfile, os
    repo = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(repo / "src")}
    with tempfile.TemporaryDirectory() as td:
        r = subprocess.run(
            [sys.executable, "-m", "signal_radar.cli", "run", "--replay",
             "--out", str(Path(td) / "digest.md")],
            cwd=repo, env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    saved = json.loads((repo / "out" / "claims" / "MDGL_Q22026.json").read_text())
    assert saved, "no claims persisted"
    assert all(c["score"] > 0 for c in saved), \
        [c["score"] for c in saved if c["score"] <= 0]


def test_speaker_normalisation_collapses_role_suffix():
    """The prompt shows the model a "Name (ROLE, Affiliation)" header and it
    echoes the header back roughly half the time, splitting one person across
    two labels in live output."""
    from signal_radar.extract import normalize_speaker
    assert normalize_speaker("Bill Sibold (CEO, Madrigal Pharmaceuticals)") == "Bill Sibold"
    assert normalize_speaker("Bill Sibold") == "Bill Sibold"
    assert normalize_speaker("David Allegretti, CMO, Madrigal") == "David Allegretti"
    assert normalize_speaker("  Mardi   Dier ") == "Mardi Dier"


def test_delta_ignores_years_and_strips_date_padding():
    """Years were being counted as figures, and the optional period prefix in
    the date pattern made findall return a leading space - so deltas read
    "figures changed: 2025" and "timing moved:  2026 ->  2025"."""
    from signal_radar.diff import _figures, _dates
    assert _figures("net sales were $364.3 million in 2026, up 71%") == {"364.3", "71"}
    assert _dates("tracking to 2027") == {"2027"}
    assert _dates("readout in 1H 2027") == {"1H 2027"}
    assert all(not d.startswith(" ") for d in _dates("quarter 2026 net"))


def test_reconstructed_fixtures_do_not_claim_a_passage_citation():
    """A passage index promises the quote was checked against a parsed span.
    Reconstructed fixtures have no span, so they must not print one."""
    from signal_radar.extract import Claim
    from signal_radar.report import _cite
    def mk(prov):
        return Claim(claim="c", quote="q", passage_idx=7, speaker="S",
                     signal_type="clinical_readout", affected_holdings=["MDGL"],
                     linkage="named_asset", materiality=0.5, reasoning="r",
                     provenance=prov)
    assert _cite(mk("verbatim")) == "[passage 7]"
    assert "passage" not in _cite(mk("reconstructed"))
    assert "reconstructed" in _cite(mk("reconstructed"))


def test_replay_uses_full_manifest_regardless_of_local_transcripts():
    """Replay reads cached claims, so it must not be gated on what happens to
    be on disk - one imported transcript used to drop the other three calls and
    with them the prior quarter every diff needs."""
    from signal_radar import fetch as fetch_mod
    from signal_radar.extract import replay_stats
    assert len(fetch_mod.MANIFEST) == 4
    covered = {(r.ticker, r.quarter) for r in fetch_mod.MANIFEST}
    assert ("NVO", "Q2 2026") in covered and ("IVA", "Q4 2025") in covered
    # MDGL Q2 carries real parse counts so the coverage table is populated
    # even when no transcript is cached locally.
    assert replay_stats("MDGL", "Q2 2026")["passages"] == 47


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
