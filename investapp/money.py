"""Currencies: trading happens in USD; amounts can also be entered and shown in a home currency (e.g. AMD)."""

from __future__ import annotations

import math

TRADING_CURRENCY = "USD"


def fx_ticker(currency: str) -> str | None:
    """Yahoo Finance symbol for 'units of `currency` per 1 USD' (e.g. AMD=X), None for USD."""
    currency = currency.upper()
    return None if currency == TRADING_CURRENCY else f"{currency}=X"


def fx_rate(latest: dict[str, float], currency: str) -> float:
    """Units of `currency` per 1 USD from latest prices; NaN if unknown."""
    sym = fx_ticker(currency)
    if sym is None:
        return 1.0
    rate = latest.get(sym)
    return float(rate) if rate and rate > 0 else math.nan


def to_usd(amount: float, currency: str, rate: float) -> float:
    return amount if currency.upper() == TRADING_CURRENCY else amount / rate


def from_usd(amount: float, currency: str, rate: float) -> float:
    return amount if currency.upper() == TRADING_CURRENCY else amount * rate


def fmt(amount: float, currency: str) -> str:
    if amount is None or (isinstance(amount, float) and math.isnan(amount)):
        return "n/a"
    decimals = 0 if currency.upper() in ("AMD", "RUB", "JPY") else 2
    sign = "-" if amount < 0 else ""
    return f"{sign}{abs(amount):,.{decimals}f} {currency.upper()}"


def fmt_both(amount_usd: float, home: str, rate: float) -> str:
    """'25.00 USD (9,046 AMD)'; just USD when home currency is USD or the rate is unknown."""
    text = fmt(amount_usd, TRADING_CURRENCY)
    if home.upper() != TRADING_CURRENCY and not math.isnan(rate):
        text += f" ({fmt(amount_usd * rate, home)})"
    return text
