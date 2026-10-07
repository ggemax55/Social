"""Recurring investment plans: schedules, what to buy, rebalancing, projections."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from itertools import takewhile
from typing import Iterator

import pandas as pd

FREQUENCIES = ("daily", "weekly", "monthly", "yearly")
# Daily plans contribute every weekday (about 261 a year).
PERIODS_PER_YEAR = {"daily": 261, "weekly": 52, "monthly": 12, "yearly": 1}

# Educational starting points built from broad, low-cost index ETFs. Not advice.
TEMPLATES: dict[str, dict[str, float]] = {
    "Simple: S&P 500 only": {"VOO": 100},
    "Simple: whole world in one fund": {"VT": 100},
    "Conservative: 30% stocks / 70% bonds": {"VTI": 20, "VXUS": 10, "BND": 70},
    "Balanced: 60% stocks / 40% bonds": {"VTI": 40, "VXUS": 20, "BND": 40},
    "Growth: 90% stocks / 10% bonds": {"VTI": 60, "VXUS": 30, "BND": 10},
}


def normalize_targets(targets: dict[str, float]) -> dict[str, float]:
    """Turn any positive weights (e.g. percentages) into fractions summing to 1."""
    clean = {k.strip().upper(): float(v) for k, v in targets.items() if k and k.strip() and float(v) > 0}
    total = sum(clean.values())
    if total <= 0:
        raise ValueError("A plan needs at least one ticker with a positive weight")
    return {k: v / total for k, v in clean.items()}


@dataclass
class Plan:
    name: str
    amount: float
    frequency: str
    targets: dict[str, float] = field(default_factory=dict)
    start_date: str = ""
    whole_shares: bool = False
    active: bool = True
    last_done: str = ""  # date the most recent contribution was recorded

    def __post_init__(self) -> None:
        self.frequency = self.frequency.strip().lower()
        if self.frequency not in FREQUENCIES:
            raise ValueError(f"frequency must be one of {FREQUENCIES}")
        self.amount = float(self.amount)
        if self.amount <= 0:
            raise ValueError("amount must be positive")
        self.start_date = str(pd.Timestamp(self.start_date or pd.Timestamp.today()).date())
        self.targets = normalize_targets(self.targets)

    @property
    def yearly_amount(self) -> float:
        return self.amount * PERIODS_PER_YEAR[self.frequency]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Plan":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


def iter_dates(frequency: str, start, from_date=None) -> Iterator[pd.Timestamp]:
    """Contribution dates of a schedule, starting at `start`, endlessly.

    Daily plans contribute on weekdays. Weekly/monthly/yearly plans repeat the
    start date's weekday / day-of-month / calendar date (month-end is clamped,
    e.g. a plan started Jan 31 contributes Feb 28). A date that lands on a
    weekend moves to the following Monday, when markets are open.
    """
    start = pd.Timestamp(start).normalize()
    lower = pd.Timestamp(from_date).normalize() if from_date is not None else start
    if frequency == "daily":
        day = max(start, lower)
        while True:
            if day.weekday() < 5:
                yield day
            day += pd.Timedelta(days=1)
    step = {"weekly": pd.DateOffset(weeks=1), "monthly": pd.DateOffset(months=1), "yearly": pd.DateOffset(years=1)}
    if frequency not in step:
        raise ValueError(f"frequency must be one of {FREQUENCIES}")
    k = 0
    if frequency == "weekly" and lower > start:
        k = max(0, (lower - start).days // 7)  # jump ahead instead of walking from the start
    while True:
        day = start + step[frequency] * k
        if day.weekday() >= 5:
            day += pd.Timedelta(days=7 - day.weekday())
        if day >= lower:
            yield day
        k += 1


def schedule(frequency: str, start, end, from_date=None) -> list[pd.Timestamp]:
    """All contribution dates between `start` (or `from_date`) and `end`, inclusive."""
    end = pd.Timestamp(end).normalize()
    return list(takewhile(lambda d: d <= end, iter_dates(frequency, start, from_date)))


def next_dates(plan: Plan, today=None, n: int = 5) -> list[pd.Timestamp]:
    today = pd.Timestamp(today or pd.Timestamp.today()).normalize()
    it = iter_dates(plan.frequency, plan.start_date, today)
    return [next(it) for _ in range(n)]


def is_due(plan: Plan, today=None) -> bool:
    return plan.active and next_dates(plan, today, 1)[0] == pd.Timestamp(today or pd.Timestamp.today()).normalize()


def allocate_contribution(
    amount: float,
    targets: dict[str, float],
    current_values: dict[str, float] | None = None,
    prices: dict[str, float] | None = None,
    whole_shares: bool = False,
) -> tuple[pd.DataFrame, float]:
    """Split new money so the portfolio moves toward its target weights.

    Money goes only to assets that are below target after the contribution, in
    proportion to how far below target they are. With an empty portfolio this is
    simply amount x weight. Selling is never needed.

    Returns (orders, leftover_cash). Orders columns: ticker, target_weight,
    current_value, amount, price, shares.
    """
    weights = normalize_targets(targets)
    current = {t: float((current_values or {}).get(t, 0.0) or 0.0) for t in weights}
    prices = prices or {}
    total_after = sum(current.values()) + amount
    gaps = {t: max(0.0, w * total_after - current[t]) for t, w in weights.items()}
    gap_sum = sum(gaps.values())
    alloc = {t: amount * g / gap_sum if gap_sum > 0 else amount * weights[t] for t, g in gaps.items()}

    def price_of(t: str) -> float:
        p = prices.get(t)
        return float(p) if p is not None and p > 0 and not math.isnan(p) else math.nan

    leftover = 0.0
    if whole_shares:
        shares = {t: math.floor(alloc[t] / price_of(t)) if not math.isnan(price_of(t)) else 0 for t in weights}
        spent = {t: shares[t] * price_of(t) if shares[t] else 0.0 for t in weights}
        leftover = amount - sum(spent.values())
        # Spend what's left one share at a time on whichever asset is furthest below target.
        while True:
            affordable = [t for t in weights if not math.isnan(price_of(t)) and price_of(t) <= leftover + 1e-9]
            if not affordable:
                break
            best = max(affordable, key=lambda t: weights[t] * total_after - current[t] - spent[t])
            shares[best] += 1
            spent[best] += price_of(best)
            leftover -= price_of(best)
        alloc = spent
    else:
        shares = {t: alloc[t] / price_of(t) for t in weights}

    orders = pd.DataFrame(
        [
            {
                "ticker": t,
                "target_weight": weights[t],
                "current_value": current[t],
                "amount": alloc[t],
                "price": price_of(t),
                "shares": shares[t],
            }
            for t in weights
        ]
    )
    return orders, max(leftover, 0.0)


def rebalance_trades(
    targets: dict[str, float], current_values: dict[str, float], threshold: float = 0.05
) -> pd.DataFrame:
    """Buy/sell amounts that would restore target weights (a yearly check-up).

    `needs_rebalance` is True for assets whose weight drifted by at least
    `threshold` (absolute, e.g. 0.05 = 5 percentage points).
    """
    weights = normalize_targets(targets)
    tickers = list(weights) + [t for t in current_values if t not in weights]
    values = {t: float(current_values.get(t, 0.0) or 0.0) for t in tickers}
    total = sum(values.values())
    rows = []
    for t in tickers:
        cw = values[t] / total if total > 0 else 0.0
        tw = weights.get(t, 0.0)
        rows.append(
            {
                "ticker": t,
                "current_value": values[t],
                "current_weight": cw,
                "target_weight": tw,
                "drift": cw - tw,
                "trade_value": tw * total - values[t],
                "needs_rebalance": abs(cw - tw) >= threshold,
            }
        )
    return pd.DataFrame(rows)


def project_growth(
    amount: float, frequency: str, years: int, annual_return: float, initial: float = 0.0
) -> pd.DataFrame:
    """Future value of regular contributions at a constant yearly return.

    Real markets never return a constant rate; this only shows how regular
    investing and compounding add up. Returns one row per year.
    """
    ppy = PERIODS_PER_YEAR[frequency]
    rate = (1 + annual_return) ** (1 / ppy) - 1
    value, invested = float(initial), float(initial)
    rows = [{"year": 0, "invested": invested, "value": value}]
    for year in range(1, years + 1):
        for _ in range(ppy):
            value = (value + amount) * (1 + rate)
            invested += amount
        rows.append({"year": year, "invested": invested, "value": value})
    return pd.DataFrame(rows)
