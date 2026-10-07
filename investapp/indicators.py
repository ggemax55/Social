"""Technical indicators and plain-language market signals.

These describe what prices *have done*. They do not predict what prices will do.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

PERIODS = ("1D", "1W", "1M", "3M", "YTD", "1Y")

_OFFSETS = {
    "1W": pd.DateOffset(weeks=1),
    "1M": pd.DateOffset(months=1),
    "3M": pd.DateOffset(months=3),
    "1Y": pd.DateOffset(years=1),
}


def period_return(series: pd.Series, period: str) -> float:
    """Simple return over a period ending at the last observation.

    The base price is the last close on or before the period's start date, so
    weekends and holidays are handled naturally.
    """
    s = series.dropna()
    if len(s) < 2:
        return math.nan
    last = float(s.iloc[-1])
    last_date = s.index[-1]
    if period == "1D":
        base = float(s.iloc[-2])
    elif period == "YTD":
        prior = s[s.index < pd.Timestamp(year=last_date.year, month=1, day=1)]
        if prior.empty:
            return math.nan
        base = float(prior.iloc[-1])
    elif period in _OFFSETS:
        prior = s[s.index <= last_date - _OFFSETS[period]]
        if prior.empty:
            return math.nan
        base = float(prior.iloc[-1])
    else:
        raise ValueError(f"Unknown period {period!r}; expected one of {PERIODS}")
    if base == 0:
        return math.nan
    return last / base - 1


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=window).mean()


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder's smoothing), 0-100."""
    delta = series.dropna().diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss
        out = 100 - 100 / (1 + rs)
    # No losses at all -> RSI 100; flat prices -> neutral 50.
    out = out.where(avg_loss != 0, 100.0)
    out = out.where(~((avg_gain == 0) & (avg_loss == 0)), 50.0)
    return out.where(avg_gain.notna())


def annualized_volatility(series: pd.Series, window: int = 63, periods_per_year: int = 252) -> float:
    rets = series.dropna().pct_change().dropna().tail(window)
    if len(rets) < 2:
        return math.nan
    return float(rets.std() * math.sqrt(periods_per_year))


def drawdown_from_high(series: pd.Series, lookback: pd.DateOffset = pd.DateOffset(years=1)) -> float:
    """How far the last price sits below the highest price in the lookback window."""
    s = series.dropna()
    if s.empty:
        return math.nan
    window = s[s.index >= s.index[-1] - lookback]
    high = float(window.max())
    return float(s.iloc[-1]) / high - 1 if high else math.nan


def max_drawdown(series: pd.Series) -> float:
    s = series.dropna()
    if s.empty:
        return math.nan
    return float((s / s.cummax() - 1).min())


@dataclass
class Signal:
    level: str  # "positive" | "caution" | "info"
    message: str


@dataclass
class TickerAnalysis:
    ticker: str
    price: float
    returns: dict[str, float]
    sma50: float
    sma200: float
    rsi14: float
    volatility: float
    from_high: float
    trend: str
    signals: list[Signal] = field(default_factory=list)


def _last(series: pd.Series) -> float:
    s = series.dropna()
    return float(s.iloc[-1]) if not s.empty else math.nan


def classify_trend(price: float, sma50_v: float, sma200_v: float) -> str:
    if math.isnan(sma200_v):
        if math.isnan(sma50_v):
            return "Not enough data"
        return "Uptrend" if price > sma50_v else "Downtrend"
    if price > sma200_v and sma50_v > sma200_v:
        return "Uptrend"
    if price < sma200_v and sma50_v < sma200_v:
        return "Downtrend"
    return "Mixed"


def _recent_cross(fast: pd.Series, slow: pd.Series, lookback: int = 20) -> int:
    """+1 if fast crossed above slow in the last `lookback` bars, -1 if below, else 0."""
    diff = (fast - slow).dropna()
    if len(diff) < 2:
        return 0
    sign = np.sign(diff).tail(lookback + 1)
    changes = sign.diff().dropna()
    changes = changes[changes != 0]
    if changes.empty:
        return 0
    return 1 if changes.iloc[-1] > 0 else -1


def analyze(series: pd.Series, ticker: str = "") -> TickerAnalysis:
    s = series.dropna()
    if s.empty:
        raise ValueError(f"No price data for {ticker or 'series'}")
    price = float(s.iloc[-1])
    sma50_s, sma200_s = sma(s, 50), sma(s, 200)
    sma50_v, sma200_v = _last(sma50_s), _last(sma200_s)
    rsi_v = _last(rsi(s))
    a = TickerAnalysis(
        ticker=ticker or str(series.name or ""),
        price=price,
        returns={p: period_return(s, p) for p in PERIODS},
        sma50=sma50_v,
        sma200=sma200_v,
        rsi14=rsi_v,
        volatility=annualized_volatility(s),
        from_high=drawdown_from_high(s),
        trend=classify_trend(price, sma50_v, sma200_v),
    )
    a.signals = build_signals(a, _recent_cross(sma50_s, sma200_s))
    return a


def build_signals(a: TickerAnalysis, cross: int = 0) -> list[Signal]:
    sig: list[Signal] = []
    if a.trend == "Uptrend":
        sig.append(Signal("positive", "Uptrend: price is above its 200-day average and the 50-day is above the 200-day."))
    elif a.trend == "Downtrend":
        sig.append(Signal("caution", "Downtrend: price is below its 200-day average and the 50-day is below the 200-day."))
    elif a.trend == "Mixed":
        sig.append(Signal("info", "Mixed trend: short- and long-term averages disagree."))

    if cross > 0:
        sig.append(Signal("positive", "Golden cross in the last month: the 50-day average moved above the 200-day."))
    elif cross < 0:
        sig.append(Signal("caution", "Death cross in the last month: the 50-day average fell below the 200-day."))

    if not math.isnan(a.rsi14):
        if a.rsi14 >= 70:
            sig.append(Signal("caution", f"RSI {a.rsi14:.0f} (overbought): price rose fast recently; chasing it adds risk of a pullback."))
        elif a.rsi14 <= 30:
            sig.append(Signal("info", f"RSI {a.rsi14:.0f} (oversold): price fell fast recently; it can keep falling, but long-term buyers get lower prices."))

    if not math.isnan(a.from_high):
        if a.from_high <= -0.20:
            sig.append(Signal("caution", f"{a.from_high:.0%} from its 1-year high: bear-market territory (a 20%+ fall)."))
        elif a.from_high <= -0.10:
            sig.append(Signal("info", f"{a.from_high:.0%} from its 1-year high: a correction (a 10-20% fall)."))
        elif a.from_high >= -0.01:
            sig.append(Signal("info", "Trading at or near its 1-year high."))
    return sig


def market_mood(analyses: list[TickerAnalysis], vix: float | None = None) -> str:
    """One-paragraph, plain-language summary of a set of markets."""
    usable = [a for a in analyses if a.trend in ("Uptrend", "Downtrend", "Mixed")]
    if not usable:
        return "Not enough data to judge the market's mood."
    up = sum(a.trend == "Uptrend" for a in usable)
    down = sum(a.trend == "Downtrend" for a in usable)
    n = len(usable)
    if up / n >= 0.7:
        mood = "Broadly positive: most markets are in long-term uptrends."
    elif down / n >= 0.5:
        mood = "Defensive: many markets are in long-term downtrends."
    else:
        mood = "Mixed: some markets are rising while others lag."
    parts = [f"{mood} ({up} of {n} in uptrend, {down} in downtrend.)"]
    if vix is not None and not math.isnan(vix):
        if vix < 15:
            parts.append(f"VIX {vix:.1f}: investors are calm.")
        elif vix < 25:
            parts.append(f"VIX {vix:.1f}: normal levels of worry.")
        elif vix < 35:
            parts.append(f"VIX {vix:.1f}: elevated fear; expect bigger daily swings.")
        else:
            parts.append(f"VIX {vix:.1f}: high fear; markets are very volatile.")
    return " ".join(parts)


def summary_table(prices: pd.DataFrame, names: dict[str, str] | None = None) -> pd.DataFrame:
    """One row per ticker: price, returns per period, trend, RSI, distance from high."""
    rows = []
    for col in prices.columns:
        s = prices[col].dropna()
        if s.empty:
            continue
        a = analyze(s, col)
        rows.append(
            {
                "ticker": col,
                "name": (names or {}).get(col, ""),
                "price": a.price,
                **a.returns,
                "trend": a.trend,
                "rsi": a.rsi14,
                "from_high": a.from_high,
                "volatility": a.volatility,
            }
        )
    return pd.DataFrame(rows)
