"""Load and validate the two config files. Everything downstream reads from here."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"


@dataclass
class Holding:
    ticker: str
    name: str
    tier: int = 2
    rationale: str = ""
    assets: list[dict] = field(default_factory=list)
    indications: list[str] = field(default_factory=list)
    mechanisms: list[str] = field(default_factory=list)
    catalysts: list[dict] = field(default_factory=list)
    named_competitors: list[str] = field(default_factory=list)

    @property
    def asset_names(self) -> list[str]:
        """Every string a company might use to refer to this holding's assets.

        Brand name and INN are both in play on a call - a rival will say
        'resmetirom' where the label says 'Rezdiffra'. Both must match.
        """
        out: list[str] = []
        for a in self.assets:
            for key in ("name", "inn"):
                if a.get(key):
                    out.append(a[key])
        return out


@dataclass
class Portfolio:
    holdings: list[Holding]
    competitor_universe: list[dict]
    meta: dict[str, Any] = field(default_factory=dict)

    def by_ticker(self, ticker: str) -> Holding | None:
        return next((h for h in self.holdings if h.ticker == ticker.upper()), None)

    @property
    def tickers(self) -> list[str]:
        return [h.ticker for h in self.holdings]

    def all_indications(self) -> set[str]:
        return {i.lower() for h in self.holdings for i in h.indications}

    def all_mechanisms(self) -> set[str]:
        return {m.lower() for h in self.holdings for m in h.mechanisms}


def load_portfolio(path: Path | None = None) -> Portfolio:
    raw = yaml.safe_load((path or CONFIG_DIR / "portfolio.yaml").read_text())
    holdings = [Holding(**h) for h in raw["holdings"]]
    if not holdings:
        raise ValueError("portfolio.yaml defines no holdings")
    return Portfolio(
        holdings=holdings,
        competitor_universe=raw.get("competitor_universe", []),
        meta=raw.get("meta", {}),
    )


def load_materiality(path: Path | None = None) -> dict[str, Any]:
    cfg = yaml.safe_load((path or CONFIG_DIR / "materiality.yaml").read_text())
    for key in ("signal_types", "section_multipliers", "alert_threshold"):
        if key not in cfg:
            raise ValueError(f"materiality.yaml missing required key: {key}")
    return cfg
