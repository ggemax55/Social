"""Saving and loading your watchlist, transactions and plans (a local JSON file)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .data import MARKET_OVERVIEW
from .planner import Plan
from .portfolio import Transaction

DEFAULT_PATH = Path(
    os.environ.get("INVESTAPP_DATA", Path(__file__).resolve().parent.parent / "data" / "portfolio.json")
)


@dataclass
class AppState:
    currency: str = "USD"
    watchlist: list[str] = field(default_factory=lambda: ["SPY", "QQQ", "VTI", "VXUS", "BND"])
    transactions: list[Transaction] = field(default_factory=list)
    plans: list[Plan] = field(default_factory=list)
    market_overview: list[str] = field(default_factory=lambda: list(MARKET_OVERVIEW))

    def to_dict(self) -> dict:
        return {
            "currency": self.currency,
            "watchlist": self.watchlist,
            "market_overview": self.market_overview,
            "transactions": [t.to_dict() for t in self.transactions],
            "plans": [p.to_dict() for p in self.plans],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AppState":
        default = cls()
        return cls(
            currency=d.get("currency", default.currency),
            watchlist=[s.upper() for s in d.get("watchlist", default.watchlist)],
            market_overview=d.get("market_overview", default.market_overview),
            transactions=[Transaction.from_dict(t) for t in d.get("transactions", [])],
            plans=[Plan.from_dict(p) for p in d.get("plans", [])],
        )

    def all_tickers(self) -> list[str]:
        tickers = set(self.watchlist) | {t.ticker for t in self.transactions}
        for p in self.plans:
            tickers |= set(p.targets)
        return sorted(tickers)


def to_json(state: AppState) -> str:
    return json.dumps(state.to_dict(), indent=2)


def from_json(text: str) -> AppState:
    return AppState.from_dict(json.loads(text))


def load_state(path: Path | str | None = None) -> AppState:
    path = Path(path or DEFAULT_PATH)
    if not path.exists():
        return AppState()
    return from_json(path.read_text())


def save_state(state: AppState, path: Path | str | None = None) -> None:
    path = Path(path or DEFAULT_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(to_json(state))
    tmp.replace(path)
