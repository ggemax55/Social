"""Portfolio bookkeeping: transactions, holdings, valuation and performance."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import pandas as pd

from .indicators import _OFFSETS

EPS = 1e-9


@dataclass
class Transaction:
    date: str  # ISO date, YYYY-MM-DD
    ticker: str
    side: str  # "buy" or "sell"
    shares: float
    price: float
    fee: float = 0.0
    note: str = ""

    def __post_init__(self) -> None:
        self.ticker = self.ticker.strip().upper()
        self.side = self.side.strip().lower()
        self.date = str(pd.Timestamp(self.date).date())
        self.shares = float(self.shares)
        self.price = float(self.price)
        self.fee = float(self.fee or 0.0)
        if self.side not in ("buy", "sell"):
            raise ValueError(f"side must be 'buy' or 'sell', got {self.side!r}")
        if self.shares <= 0 or self.price < 0 or self.fee < 0:
            raise ValueError("shares must be positive; price and fee cannot be negative")

    @property
    def cash_flow(self) -> float:
        """Money put into (+) or taken out of (-) the portfolio by this trade."""
        gross = self.shares * self.price
        return gross + self.fee if self.side == "buy" else -(gross - self.fee)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Transaction":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


def _sorted(transactions: list[Transaction]) -> list[Transaction]:
    # Buys before sells on the same day so a same-day round trip is valid.
    return sorted(transactions, key=lambda t: (t.date, t.side != "buy"))


def _positions(transactions: list[Transaction]) -> dict[str, list[float]]:
    """Replay trades with the average-cost method: ticker -> [shares, cost, realized]."""
    pos: dict[str, list[float]] = {}
    for t in _sorted(transactions):
        shares, cost, realized = pos.get(t.ticker, [0.0, 0.0, 0.0])
        if t.side == "buy":
            shares += t.shares
            cost += t.shares * t.price + t.fee
        else:
            if t.shares > shares + EPS:
                raise ValueError(
                    f"{t.date}: selling {t.shares:g} {t.ticker} but only {shares:g} held"
                )
            removed = cost * (t.shares / shares)
            realized += (t.shares * t.price - t.fee) - removed
            shares -= t.shares
            cost -= removed
            if shares < EPS:
                shares, cost = 0.0, 0.0
        pos[t.ticker] = [shares, cost, realized]
    return pos


def compute_holdings(transactions: list[Transaction]) -> pd.DataFrame:
    """Current positions using the average-cost method.

    Columns: ticker, shares, cost_basis, avg_cost, realized_pl.
    Fully sold positions are dropped (their realized P/L is in `realized_total`).
    Raises ValueError if a sale exceeds the shares held at that date.
    """
    rows = [
        {"ticker": tk, "shares": sh, "cost_basis": c, "avg_cost": c / sh, "realized_pl": r}
        for tk, (sh, c, r) in sorted(_positions(transactions).items())
        if sh > EPS
    ]
    return pd.DataFrame(rows, columns=["ticker", "shares", "cost_basis", "avg_cost", "realized_pl"])


def realized_total(transactions: list[Transaction]) -> float:
    """Profit or loss locked in by all sales, including fully closed positions."""
    return sum(r for _, _, r in _positions(transactions).values())


def value_holdings(holdings: pd.DataFrame, prices: dict[str, float]) -> pd.DataFrame:
    """Add price, market value, unrealized P/L and portfolio weight."""
    df = holdings.copy()
    df["price"] = df["ticker"].map(prices).astype(float)
    df["market_value"] = df["shares"] * df["price"]
    df["unrealized_pl"] = df["market_value"] - df["cost_basis"]
    df["unrealized_pct"] = df["unrealized_pl"] / df["cost_basis"].where(df["cost_basis"] > 0)
    total = df["market_value"].sum(min_count=1)
    df["weight"] = df["market_value"] / total if total and not math.isnan(total) else math.nan
    return df


def value_history(transactions: list[Transaction], prices: pd.DataFrame) -> pd.DataFrame:
    """Daily portfolio value and cumulative net money invested.

    Returns a frame indexed by date with columns `value` and `invested`.
    A trade dated on a non-trading day takes effect on the next trading day.
    """
    if not transactions or prices.empty:
        return pd.DataFrame(columns=["value", "invested"])
    start = pd.Timestamp(min(t.date for t in transactions))
    px = prices.sort_index().ffill()
    px = px[px.index >= start]
    if px.empty:
        return pd.DataFrame(columns=["value", "invested"])

    tickers = sorted({t.ticker for t in transactions} & set(px.columns))
    share_delta = pd.DataFrame(0.0, index=px.index, columns=tickers)
    flows = pd.Series(0.0, index=px.index)
    for t in transactions:
        pos = px.index.searchsorted(pd.Timestamp(t.date))
        if pos >= len(px.index):
            continue  # trade is newer than the latest price
        day = px.index[pos]
        flows.loc[day] += t.cash_flow
        if t.ticker in share_delta.columns:
            share_delta.loc[day, t.ticker] += t.shares if t.side == "buy" else -t.shares

    held = share_delta.cumsum()
    value = (held * px[tickers].fillna(0.0)).sum(axis=1)
    return pd.DataFrame({"value": value, "invested": flows.cumsum()})


PORTFOLIO_PERIODS = {"Day": "1D", "Week": "1W", "Month": "1M", "Year": "1Y", "All time": "ALL"}


def period_performance(history: pd.DataFrame, period: str) -> dict[str, float]:
    """Gain over a period, excluding money you added or withdrew.

    `period` is one of 1D, 1W, 1M, 3M, 1Y or ALL. The percentage is a simple
    approximation: gain / (starting value + net new money).
    """
    nan = math.nan
    empty = dict(start_value=nan, end_value=nan, net_flows=nan, gain=nan, gain_pct=nan)
    if history.empty:
        return empty
    end_date = history.index[-1]
    end = history.iloc[-1]
    if period == "ALL":
        start_value, start_invested = 0.0, 0.0
    else:
        if period == "1D":
            prior = history.iloc[:-1]
        else:
            prior = history[history.index <= end_date - _OFFSETS[period]]
        if prior.empty:
            start_value, start_invested = 0.0, 0.0  # portfolio is younger than the period
        else:
            start_value = float(prior["value"].iloc[-1])
            start_invested = float(prior["invested"].iloc[-1])
    net_flows = float(end["invested"]) - start_invested
    gain = float(end["value"]) - start_value - net_flows
    base = start_value + max(net_flows, 0.0)
    return dict(
        start_value=start_value,
        end_value=float(end["value"]),
        net_flows=net_flows,
        gain=gain,
        gain_pct=gain / base if base > EPS else nan,
    )


def current_values(valued: pd.DataFrame) -> dict[str, float]:
    """ticker -> market value, from the output of `value_holdings`."""
    if valued.empty:
        return {}
    return {r.ticker: float(r.market_value) for r in valued.itertuples() if not math.isnan(r.market_value)}
