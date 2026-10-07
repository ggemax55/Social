"""Market data fetching (Yahoo Finance via yfinance)."""

from __future__ import annotations

import pandas as pd

# A broad, beginner-friendly market overview. Users can change their own watchlist.
MARKET_OVERVIEW: dict[str, str] = {
    "SPY": "S&P 500 (US large caps)",
    "QQQ": "Nasdaq 100 (US tech-heavy)",
    "DIA": "Dow Jones 30",
    "IWM": "Russell 2000 (US small caps)",
    "VXUS": "International stocks (ex-US)",
    "VWO": "Emerging markets",
    "BND": "US total bond market",
    "GLD": "Gold",
    "BTC-USD": "Bitcoin",
    "^VIX": "VIX (fear index)",
}

KNOWN_NAMES: dict[str, str] = {
    **MARKET_OVERVIEW,
    "VTI": "US total stock market",
    "VOO": "S&P 500 (Vanguard)",
    "VT": "Total world stocks",
    "SCHD": "US dividend stocks",
    "AGG": "US aggregate bonds",
    "TLT": "Long-term US Treasuries",
    "SHY": "Short-term US Treasuries",
    "VNQ": "US real estate (REITs)",
    "ETH-USD": "Ethereum",
    "BNDX": "International bonds (USD-hedged)",
    "IEMG": "Emerging markets (iShares)",
    "AMD=X": "US dollar in Armenian dram",
}

# Broad, low-cost US-listed funds that international brokers serving Armenia (e.g. Interactive
# Brokers, Freedom Broker) generally offer. A starting point: check the list against your broker.
ARMENIA_STARTER = ["VT", "VOO", "VTI", "VXUS", "VWO", "QQQ", "SCHD", "BND", "BNDX", "SHY", "GLD"]


def is_market(ticker: str) -> bool:
    """True for investable assets; False for indexes (^VIX) and exchange rates (AMD=X)."""
    return not ticker.startswith("^") and not ticker.endswith("=X")


def normalize_ticker(ticker: str) -> str:
    return ticker.strip().upper()


def fetch_prices(tickers: list[str] | tuple[str, ...], period: str = "2y") -> pd.DataFrame:
    """Daily adjusted closing prices: one column per ticker, indexed by date.

    Tickers trading on different calendars (e.g. crypto on weekends) leave NaN
    gaps; callers that need aligned prices should forward-fill.
    """
    import yfinance as yf

    symbols = sorted({normalize_ticker(t) for t in tickers if t and t.strip()})
    if not symbols:
        return pd.DataFrame()
    raw = yf.download(
        symbols,
        period=period,
        interval="1d",
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    if raw is None or raw.empty:
        return pd.DataFrame()
    close = raw["Close"]
    if isinstance(close, pd.Series):
        close = close.to_frame(symbols[0])
    close = close.copy()
    close.index = pd.to_datetime(close.index)
    if close.index.tz is not None:
        close.index = close.index.tz_localize(None)
    close.index = close.index.normalize()
    close.columns = [str(c) for c in close.columns]
    return close.dropna(how="all").sort_index()


def latest_prices(prices: pd.DataFrame) -> dict[str, float]:
    """Last available (non-NaN) price for every column."""
    out: dict[str, float] = {}
    for col in prices.columns:
        s = prices[col].dropna()
        if not s.empty:
            out[col] = float(s.iloc[-1])
    return out
