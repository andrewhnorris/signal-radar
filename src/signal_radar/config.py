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


class AliasMap:
    """Resolves surface strings to canonical entity names.

    A drug is not a string. The same programme appears as an internal code, a
    generic name, a brand name, and a licensor code - and the label changes on
    in-licensing or acquisition. Canonicalising before any comparison is what
    stops the diff reporting a renamed asset as a dropped programme.
    """

    def __init__(self, raw: dict[str, Any]):
        self._lookup: dict[str, str] = {}
        self._meta: dict[str, dict] = {}
        for section in ("assets", "indications", "mechanisms"):
            for canonical, body in (raw.get(section) or {}).items():
                body = body or {}
                self._meta[canonical] = {"section": section, **body}
                for alias in [canonical, *(body.get("aliases") or [])]:
                    self._lookup[self._norm(alias)] = canonical

    @staticmethod
    def _norm(s: str) -> str:
        return " ".join(s.lower().replace("-", " ").replace("/", " ").split())

    def canonical(self, term: str) -> str:
        """Canonical name, or the cleaned original if unknown.

        Unknown terms pass through rather than being dropped: an alias map is
        always incomplete, and silently discarding an unrecognised drug name
        would be a worse failure than carrying it uncanonicalised.
        """
        if not term:
            return ""
        return self._lookup.get(self._norm(term), term.strip())

    def canonical_set(self, terms: list[str]) -> set[str]:
        return {c for t in terms if (c := self.canonical(t))}

    def owner(self, term: str) -> str | None:
        return self._meta.get(self.canonical(term), {}).get("owner")

    def note(self, term: str) -> str | None:
        return self._meta.get(self.canonical(term), {}).get("note")

    def __len__(self) -> int:
        return len(self._lookup)


def load_aliases(path: Path | None = None) -> AliasMap:
    p = path or CONFIG_DIR / "aliases.yaml"
    if not p.exists():
        return AliasMap({})
    return AliasMap(yaml.safe_load(p.read_text()) or {})
