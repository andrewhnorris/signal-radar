"""Materiality scoring: model judgement x structural multipliers.

Kept deliberately transparent and non-learned. An analyst who disagrees with a
ranking must be able to look at one YAML file, see exactly which multiplier
caused it, and change it. A tuned model that cannot be argued with does not get
adopted, however good its AUC.
"""
from __future__ import annotations

from .config import Portfolio
from .extract import Claim


def score_claim(claim: Claim, portfolio: Portfolio, cfg: dict) -> float:
    base = claim.materiality

    type_w = cfg["signal_types"].get(claim.signal_type, {}).get("weight", 0.5)
    section_w = cfg["section_multipliers"].get(claim.section, 1.0)
    linkage_w = cfg["linkage_multipliers"].get(claim.linkage, 0.0)
    novelty_w = cfg["novelty_multipliers"].get(claim.novelty, 1.0)

    # A claim can touch several holdings; the strongest link sets the tier.
    tiers = [h.tier for t in claim.affected_holdings if (h := portfolio.by_ticker(t))]
    tier_w = max((cfg["tier_multipliers"].get(t, 1.0) for t in tiers), default=1.0)

    claim.score = round(base * type_w * section_w * linkage_w * novelty_w * tier_w, 3)
    return claim.score


def score_all(claims: list[Claim], portfolio: Portfolio, cfg: dict) -> list[Claim]:
    for c in claims:
        score_claim(c, portfolio, cfg)
    return sorted(claims, key=lambda c: c.score, reverse=True)


def partition(claims: list[Claim], cfg: dict) -> dict[str, list[Claim]]:
    """Split into alert / watch / archive.

    Nothing is discarded. Archive stays in the JSON so a missed signal can be
    recovered and used to retune the thresholds - which is the only honest way
    to measure recall on a problem with no labelled ground truth.
    """
    alert_t, watch_t = cfg["alert_threshold"], cfg["watch_threshold"]
    per_call = cfg.get("max_alerts_per_call", 5)
    per_digest = cfg.get("max_alerts_per_digest", 12)

    # Caps are applied per source call before the global cap. Without this, one
    # unusually candid management team floods the digest and genuinely material
    # items from quieter calls never surface. Overflow demotes to watch rather
    # than disappearing.
    alerts: list[Claim] = []
    used: dict[str, int] = {}
    for c in claims:                      # already score-sorted
        if c.score < alert_t or len(alerts) >= per_digest:
            continue
        if used.get(c.source_ticker, 0) >= per_call:
            continue
        used[c.source_ticker] = used.get(c.source_ticker, 0) + 1
        alerts.append(c)

    alert_ids = {id(c) for c in alerts}
    return {
        "alerts": alerts,
        "watch": [c for c in claims
                  if id(c) not in alert_ids and c.score >= watch_t],
        "archive": [c for c in claims if c.score < watch_t],
    }
