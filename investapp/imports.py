"""Import trades from a broker's CSV export."""

from __future__ import annotations

import io
import re

import pandas as pd

from .portfolio import Transaction

FIELDS = ("date", "ticker", "side", "shares", "price", "fee")
REQUIRED = ("date", "ticker", "shares", "price")

# Common column names in broker exports (Interactive Brokers, Tradernet/Freedom, generic).
ALIASES: dict[str, list[str]] = {
    "date": ["date", "trade date", "tradedate", "date/time", "datetime", "time", "execution time", "settle date"],
    "ticker": ["ticker", "symbol", "instrument", "security", "code", "asset"],
    "side": ["side", "buy/sell", "buysell", "action", "operation", "direction", "transaction type"],
    "shares": ["shares", "quantity", "qty", "units", "volume", "amount of shares"],
    "price": ["price", "trade price", "tradeprice", "t. price", "execution price", "avg price", "price per share"],
    "fee": ["fee", "fees", "commission", "comm/fee", "ibcommission", "comm", "commission fee"],
}


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", str(name).strip().lower())


def read_csv(data: bytes | str) -> pd.DataFrame:
    text = data.decode("utf-8-sig", errors="replace") if isinstance(data, bytes) else data
    return pd.read_csv(io.StringIO(text), sep=None, engine="python")


def guess_mapping(columns) -> dict[str, str | None]:
    """Best guess of which CSV column holds each field (None if not found)."""
    by_norm = {_norm(c): c for c in columns}
    mapping: dict[str, str | None] = {}
    for f in FIELDS:
        mapping[f] = next((by_norm[a] for a in ALIASES[f] if a in by_norm), None)
    return mapping


def _number(value) -> float:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return float("nan")
    text = str(value).strip().replace("$", "").replace(" ", "").replace("\u00a0", "")
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    if "," in text and "." in text:
        # The last separator is the decimal one: 1,234.56 or 1.234,56
        text = text.replace(",", "") if text.rfind(".") > text.rfind(",") else text.replace(".", "").replace(",", ".")
    elif "," in text:
        # 1,234 / 12,345,678 are thousands; anything else (1,5 / 72,10) is a decimal comma.
        text = text.replace(",", "") if re.fullmatch(r"-?\d{1,3}(,\d{3})+", text) else text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return float("nan")


SELL_WORDS = {"sell", "s", "sld", "sold", "sale", "продажа"}
BUY_WORDS = {"buy", "b", "bot", "bought", "purchase", "покупка"}


def _date(value) -> pd.Timestamp:
    text = str(value).replace(",", " ").strip()
    day_first = bool(re.match(r"^\d{1,2}\.\d{1,2}\.\d{2,4}", text))  # 07.10.2026 = 7 October
    return pd.to_datetime(text, errors="coerce", dayfirst=day_first)


def _side(value, shares: float) -> str | None:
    if value is not None and not (isinstance(value, float) and pd.isna(value)):
        text = str(value).strip().lower()
        if text in SELL_WORDS:
            return "sell"
        if text in BUY_WORDS:
            return "buy"
    if shares < 0:
        return "sell"
    if shares > 0:
        return "buy"
    return None


def parse_trades(df: pd.DataFrame, mapping: dict[str, str | None]) -> tuple[list[Transaction], list[str]]:
    """Turn CSV rows into transactions. Rows that can't be read are reported, not imported.

    Without a side column, negative quantities are treated as sells.
    """
    missing = [f for f in REQUIRED if not mapping.get(f)]
    if missing:
        return [], [f"Choose a column for: {', '.join(missing)}"]
    trades, problems = [], []
    for i, row in df.iterrows():
        line = i + 2  # header is line 1
        try:
            date = _date(row[mapping["date"]])
            shares = _number(row[mapping["shares"]])
            price = abs(_number(row[mapping["price"]]))
            fee = abs(_number(row[mapping["fee"]])) if mapping.get("fee") else 0.0
            ticker = str(row[mapping["ticker"]]).strip().upper()
            side = _side(row[mapping["side"]] if mapping.get("side") else None, shares)
            if pd.isna(date) or not ticker or ticker == "NAN" or pd.isna(shares) or pd.isna(price) or side is None:
                problems.append(f"Line {line}: skipped (missing date, ticker, quantity or price)")
                continue
            trades.append(Transaction(str(date.date()), ticker, side, abs(shares), price, 0.0 if pd.isna(fee) else fee,
                                      "Imported"))
        except (ValueError, KeyError) as e:
            problems.append(f"Line {line}: {e}")
    return trades, problems


def _key(t: Transaction) -> tuple:
    return (t.date, t.ticker, t.side, round(t.shares, 6), round(t.price, 4))


def merge_trades(existing: list[Transaction], new: list[Transaction]) -> tuple[list[Transaction], int, int]:
    """Add trades that aren't already recorded. Returns (merged, added, duplicates)."""
    seen = {_key(t) for t in existing}
    merged, added, dupes = list(existing), 0, 0
    for t in new:
        if _key(t) in seen:
            dupes += 1
            continue
        seen.add(_key(t))
        merged.append(t)
        added += 1
    return merged, added, dupes
