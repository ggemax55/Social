"""Historical simulation of regular investing (dollar-cost averaging)."""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from .fees import Broker
from .planner import FREQUENCIES, PERIODS_PER_YEAR, allocate_contribution, normalize_targets, schedule


def xirr(flows: list[tuple[pd.Timestamp, float]]) -> float:
    """Annualized money-weighted return of dated cash flows (negative = money in)."""
    if not flows or all(cf >= 0 for _, cf in flows) or all(cf <= 0 for _, cf in flows):
        return math.nan
    t0 = min(d for d, _ in flows)
    years = [((d - t0).days / 365.0, cf) for d, cf in flows]
    if max(y for y, _ in years) == 0:
        return math.nan

    def npv(rate: float) -> float:
        return sum(cf / (1 + rate) ** y for y, cf in years)

    lo, hi = -0.9999, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return math.nan
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if f_lo * f_mid <= 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


@dataclass
class BacktestResult:
    history: pd.DataFrame  # columns: value, invested
    total_invested: float
    final_value: float
    contributions: int
    annualized: float  # money-weighted (XIRR)
    fees: float = 0.0

    @property
    def profit(self) -> float:
        return self.final_value - self.total_invested

    @property
    def total_return(self) -> float:
        return self.profit / self.total_invested if self.total_invested else math.nan


def _aligned_prices(prices: pd.DataFrame, tickers: list[str], start, end) -> pd.DataFrame:
    missing = [t for t in tickers if t not in prices.columns]
    if missing:
        raise ValueError(f"No price data for: {', '.join(missing)}")
    px = prices[tickers].sort_index().ffill().dropna()
    px = px[px.index >= pd.Timestamp(start)]
    if end is not None:
        px = px[px.index <= pd.Timestamp(end)]
    if px.empty:
        raise ValueError("No overlapping price history for these tickers in that date range")
    return px


def _simulate(
    px: pd.DataFrame, weights: dict[str, float], buys: pd.Series,
    broker: Broker | None = None, single_order: bool = False,
) -> BacktestResult:
    """Buy at each day's close in `buys` (date -> amount), steering toward `weights`.

    With a `broker`, each order pays its fee out of the money being invested
    (fractional shares are assumed so results stay comparable)."""
    tickers = list(weights)
    share_delta = pd.DataFrame(0.0, index=px.index, columns=tickers)
    held = {t: 0.0 for t in tickers}
    total_fees = 0.0
    for day, amount in buys.items():
        day_prices = px.loc[day].to_dict()
        current = {t: held[t] * day_prices[t] for t in tickers}
        orders, _ = allocate_contribution(amount, weights, current, day_prices, single_order=single_order)
        for row in orders.itertuples():
            if row.amount <= 0:
                continue
            fee = broker.order_fee(row.amount, row.price) if broker else 0.0
            shares = max(row.amount - fee, 0.0) / row.price
            total_fees += min(fee, row.amount)
            held[row.ticker] += shares
            share_delta.loc[day, row.ticker] += shares
    value = (share_delta.cumsum() * px).sum(axis=1)
    invested = buys.reindex(px.index, fill_value=0.0).cumsum()
    history = pd.DataFrame({"value": value, "invested": invested})
    history = history[history["invested"] > 0]
    final = float(history["value"].iloc[-1])
    flows = [(d, -a) for d, a in buys.items()] + [(history.index[-1], final)]
    return BacktestResult(history, float(buys.sum()), final, int(len(buys)), xirr(flows), total_fees)


def backtest_plan(
    prices: pd.DataFrame,
    targets: dict[str, float],
    amount: float,
    frequency: str,
    start,
    end=None,
    broker: Broker | None = None,
    single_order: bool = False,
) -> BacktestResult:
    """Invest `amount` every period, buying at the close of the first trading day
    on or after each scheduled date. New money is steered toward target weights."""
    weights = normalize_targets(targets)
    px = _aligned_prices(prices, list(weights), start, end)
    dates = schedule(frequency, px.index[0], px.index[-1])
    positions = px.index.searchsorted(dates)
    days = [px.index[p] for p in positions if p < len(px.index)]
    buys = pd.Series(float(amount), index=pd.DatetimeIndex(days)).groupby(level=0).sum()
    return _simulate(px, weights, buys, broker, single_order)


def backtest_lump_sum(
    prices: pd.DataFrame, targets: dict[str, float], total: float, start, end=None, broker: Broker | None = None
) -> BacktestResult:
    """Invest everything on the first trading day and hold."""
    weights = normalize_targets(targets)
    px = _aligned_prices(prices, list(weights), start, end)
    return _simulate(px, weights, pd.Series([float(total)], index=px.index[:1]), broker)


def compare_frequencies(
    prices: pd.DataFrame, targets: dict[str, float], yearly_budget: float, start, end=None,
    broker: Broker | None = None, single_order: bool = False,
) -> pd.DataFrame:
    """Same yearly budget, invested daily vs weekly vs monthly vs yearly vs all at once."""
    rows = []
    results: dict[str, BacktestResult] = {}
    for freq in FREQUENCIES:
        each = yearly_budget / PERIODS_PER_YEAR[freq]
        res = backtest_plan(prices, targets, each, freq, start, end, broker, single_order)
        results[freq] = res
        rows.append(_row(f"{freq.capitalize()} ({each:,.2f} each)", res))
    lump = backtest_lump_sum(prices, targets, results["monthly"].total_invested, start, end, broker)
    rows.append(_row("Lump sum (all at the start)", lump))
    return pd.DataFrame(rows)


def _row(label: str, r: BacktestResult) -> dict:
    return {
        "strategy": label,
        "contributions": r.contributions,
        "invested": r.total_invested,
        "final_value": r.final_value,
        "profit": r.profit,
        "total_return": r.total_return,
        "annualized": r.annualized,
        "fees": r.fees,
    }
