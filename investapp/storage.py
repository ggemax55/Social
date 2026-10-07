"""Saving and loading your watchlist, transactions and plans (a local JSON file)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .data import ARMENIA_STARTER, MARKET_OVERVIEW
from .fees import Broker
from .money import fx_ticker
from .planner import Plan
from .portfolio import Transaction

DEFAULT_PATH = Path(
    os.environ.get("INVESTAPP_DATA", Path(__file__).resolve().parent.parent / "data" / "portfolio.json")
)


@dataclass
class AppState:
    currency: str = "USD"  # trading currency: prices, trades and holdings
    watchlist: list[str] = field(default_factory=lambda: ["SPY", "QQQ", "VT", "VTI", "VXUS", "BND"])
    transactions: list[Transaction] = field(default_factory=list)
    plans: list[Plan] = field(default_factory=list)
    market_overview: list[str] = field(default_factory=lambda: [*MARKET_OVERVIEW, "AMD=X"])
    country: str = "Armenia"
    home_currency: str = "AMD"  # amounts are also shown in this currency
    broker: dict = field(default_factory=lambda: Broker().to_dict())
    allowed_tickers: list[str] = field(default_factory=lambda: list(ARMENIA_STARTER))
    task_log: dict[str, dict] = field(default_factory=dict)  # task key -> {"status", "date"}

    def to_dict(self) -> dict:
        return {
            "currency": self.currency,
            "country": self.country,
            "home_currency": self.home_currency,
            "broker": self.broker,
            "allowed_tickers": self.allowed_tickers,
            "watchlist": self.watchlist,
            "market_overview": self.market_overview,
            "transactions": [t.to_dict() for t in self.transactions],
            "plans": [p.to_dict() for p in self.plans],
            "task_log": self.task_log,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AppState":
        default = cls()
        return cls(
            currency=d.get("currency", default.currency),
            country=d.get("country", default.country),
            home_currency=d.get("home_currency", default.home_currency).upper(),
            broker=d.get("broker", default.broker),
            allowed_tickers=[s.upper() for s in d.get("allowed_tickers", default.allowed_tickers)],
            watchlist=[s.upper() for s in d.get("watchlist", default.watchlist)],
            market_overview=d.get("market_overview", default.market_overview),
            transactions=[Transaction.from_dict(t) for t in d.get("transactions", [])],
            plans=[Plan.from_dict(p) for p in d.get("plans", [])],
            task_log=dict(d.get("task_log", {})),
        )

    @property
    def broker_profile(self) -> Broker:
        return Broker.from_dict(self.broker)

    def plan_by_id(self, plan_id: str) -> Plan | None:
        return next((p for p in self.plans if p.id == plan_id), None)

    def add_plan(self, plan: Plan) -> Plan:
        """Add a plan, making sure its id is unique."""
        base, n = plan.id, 1
        while any(p.id == plan.id for p in self.plans):
            plan.id = f"{base}-{n}"
            n += 1
        self.plans.append(plan)
        return plan

    def all_tickers(self) -> list[str]:
        tickers = set(self.watchlist) | {t.ticker for t in self.transactions}
        for p in self.plans:
            tickers |= set(p.targets)
        for cur in {self.home_currency, *(p.currency for p in self.plans)}:
            if fx_ticker(cur):
                tickers.add(fx_ticker(cur))
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
