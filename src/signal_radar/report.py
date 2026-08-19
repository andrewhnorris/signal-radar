"""Render the analyst-facing digest.

Format choice: markdown, delivered as an email or Slack post before the open on
call days. Not a dashboard. Nobody logs into a dashboard to find out whether
something happened - the artefact has to arrive where the analyst already is.

Every rendered signal carries speaker, section, and a verbatim quote. An analyst
will not act on a model summary they cannot verify in one click, so traceability
is a rendering requirement, not a nice-to-have.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from .config import Portfolio
from .extract import Claim

_TYPE_LABEL = {
    "clinical_readout": "Clinical",
    "timeline_change": "Timeline",
    "competitive_positioning": "Competitive",
    "commercial_trajectory": "Commercial",
}
_NOVELTY_LABEL = {"new": "NEW", "changed": "CHANGED", "repeated": "repeat", "unknown": ""}


def _render_claim(c: Claim, n: int) -> str:
    holdings = ", ".join(c.affected_holdings)
    flag = _NOVELTY_LABEL.get(c.novelty, "")
    flag_str = f" · `{flag}`" if flag else ""

    lines = [
        f"#### {n}. {holdings} — {c.claim}",
        "",
        f"**{_TYPE_LABEL.get(c.signal_type, c.signal_type)}** · score `{c.score}` · "
        f"{c.linkage.replace('_', ' ')}{flag_str}",
        "",
        f"> {c.quote}",
        f"> — {c.speaker}, {c.source_company} {c.quarter}, {c.section.upper()} "
        f"[passage {c.passage_idx}]",
        "",
        f"**Why it matters:** {c.reasoning}",
    ]
    if c.delta:
        lines += ["", f"**Changed since last quarter:** {c.delta}"]
    if c.transcription_note:
        lines += ["", f"*Transcript note: {c.transcription_note}*"]
    lines.append("")
    return "\n".join(lines)


def render_digest(partitioned: dict[str, list[Claim]], portfolio: Portfolio,
                  calls_processed: list[dict], dropped: dict[str, list[str]],
                  coverage_gaps: list[str] | None = None) -> str:
    alerts, watch, archive = (partitioned["alerts"], partitioned["watch"],
                              partitioned["archive"])

    out = [
        "# Competitor Call Digest",
        f"*Generated {date.today().isoformat()} · "
        f"{len(calls_processed)} call(s) · "
        f"{len(alerts)} alerts, {len(watch)} watch, {len(archive)} archived*",
        "",
        "---",
        "",
    ]

    # --- Alerts -----------------------------------------------------------
    out.append("## Needs an analyst")
    out.append("")
    if not alerts:
        out += ["*Nothing crossed the alert threshold. This is a normal and "
                "expected outcome for most calls — see README on precision vs "
                "recall.*", ""]
    else:
        by_holding: dict[str, list[Claim]] = defaultdict(list)
        for c in alerts:
            for h in c.affected_holdings:
                by_holding[h].append(c)
        seen: set[int] = set()
        n = 0
        for holding in sorted(by_holding, key=lambda h: -max(c.score for c in by_holding[h])):
            for c in by_holding[holding]:
                if id(c) in seen:
                    continue
                seen.add(id(c))
                n += 1
                out.append(_render_claim(c, n))

    # --- Watch ------------------------------------------------------------
    if watch:
        out += ["---", "", "## Context", "",
                "*Below the alert bar. Retained so the picture is complete, "
                "not because it needs action.*", ""]
        for c in watch[:20]:
            holdings = ", ".join(c.affected_holdings)
            out.append(
                f"- **{holdings}** · {_TYPE_LABEL.get(c.signal_type, c.signal_type)} "
                f"(`{c.score}`) — {c.claim} "
                f"<sub>{c.speaker}, {c.section.upper()}, passage {c.passage_idx}</sub>"
            )
        out.append("")

    # --- Silence ----------------------------------------------------------
    if any(dropped.values()):
        out += ["---", "", "## Went quiet", "",
                "*Discussed last quarter, absent this quarter. Often the first "
                "observable sign of a deprioritised program.*", ""]
        for ticker, items in dropped.items():
            if items:
                out.append(f"- **{ticker}**: {', '.join(items)}")
        out.append("")

    # --- Coverage ---------------------------------------------------------
    out += ["---", "", "## Coverage", ""]
    for call in calls_processed:
        s = call.get("stats", {})
        out.append(
            f"- **{call['ticker']}** {call['quarter']} — "
            f"{s.get('passages', 0)} passages "
            f"({s.get('prepared', 0)} prepared / {s.get('qa', 0)} Q&A), "
            f"{s.get('analysts', 0)} analysts, {call.get('claims', 0)} claims extracted"
        )
    if coverage_gaps:
        out += ["", "**Not ingested this window** — known blind spots:", ""]
        out += [f"- {g}" for g in coverage_gaps]
    out.append("")

    out += ["---", "",
            "<sub>All inputs are public disclosure — 13F filings and published "
            "earnings call transcripts. No MNPI, no expert networks. Scores are "
            "config-driven and fully traceable; see `config/materiality.yaml`.</sub>",
            ""]

    return "\n".join(out)
