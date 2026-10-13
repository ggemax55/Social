"""Practice trading: pretend money, simple intraday rules, and honest tests of those rules.

Nothing here predicts prices. The rules are mechanical on purpose: that way their
results can be measured on past data (after fees) before anyone trusts them.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .fees import Broker

MARKET_TZ = "America/New_York"
LOCAL_TZ = "Asia/Yerevan"
BAR = pd.Timedelta(minutes=5)
OPEN = pd.Timedelta(hours=9, minutes=30)
CLOSE = pd.Timedelta(hours=16)

RULES = {"orb": "Opening range breakout", "ema": "Moving-average crossover"}
RULE_HELP = {
    "orb": "Watch the highest and lowest price of the first minutes after the market opens (the *opening range*). "
           "If a 5-minute bar closes above the range, buy. Stop-loss at the bottom of the range; take profit at "
           "a multiple of the risk; sell anyway when the time limit is up.",
    "ema": "Follow two moving averages of the 5-minute price (9 and 21 bars). Buy when the fast one crosses above "
           "the slow one; sell when it crosses back below, at the stop-loss, at the profit target, or when the "
           "time limit is up.",
}
TICKERS = {"SPY": "S&P 500 fund", "QQQ": "Nasdaq 100 fund", "IWM": "US small companies fund", "AAPL": "Apple",
           "MSFT": "Microsoft", "NVDA": "Nvidia", "TSLA": "Tesla"}


def new_practice() -> dict:
    """Default practice settings and an empty pretend account."""
    return {
        "ticker": "SPY", "rule": "orb", "opening_minutes": 30, "window_minutes": 60, "max_hold_minutes": 60,
        "target_r": 2.0, "stop_pct": 0.5, "long_only": True,
        "start_cash": 1400.0,  # USD, about 500,000 AMD
        "risk_pct": 1.0,  # share of the account you may lose on one trade
        "daily_loss_limit": 10_000.0,  # in your home currency; no new trades after losing this much in a day
        "max_trades": 3,
        "trades": [], "open": None,
    }


# ---------------------------------------------------------------- data


def fetch_intraday(ticker: str, period: str = "60d", interval: str = "5m") -> pd.DataFrame:
    """5-minute bars (open, high, low, close, volume) in New York time, regular hours only."""
    import yfinance as yf

    raw = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=False, prepost=False)
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    if isinstance(raw.columns, pd.MultiIndex):
        raw = raw.xs(raw.columns.get_level_values(1)[0], axis=1, level=1)
    df = raw.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].dropna(subset=["close"])
    idx = pd.DatetimeIndex(df.index)
    df.index = (idx.tz_localize("UTC") if idx.tz is None else idx).tz_convert(MARKET_TZ)
    return df.sort_index()


def sessions(bars: pd.DataFrame) -> dict:
    """date -> that day's bars."""
    if bars.empty:
        return {}
    return {d: g for d, g in bars.groupby(bars.index.date)}


def complete_bars(bars: pd.DataFrame, now: pd.Timestamp | None) -> pd.DataFrame:
    """Drop the bar that is still forming (its 5 minutes haven't passed yet)."""
    if now is None or bars.empty:
        return bars
    return bars[bars.index + BAR <= pd.Timestamp(now).tz_convert(MARKET_TZ)]


def market_status(now: pd.Timestamp | None = None) -> tuple[bool, str]:
    """(open?, text) for the US stock market, with times in Yerevan. Holidays are not known."""
    now = pd.Timestamp(now or pd.Timestamp.now(tz="UTC")).tz_convert(MARKET_TZ)
    day = now.normalize()
    if now.weekday() < 5 and day + OPEN <= now < day + CLOSE:
        closes = (day + CLOSE).tz_convert(LOCAL_TZ)
        return True, f"The US market is open until {closes:%H:%M} Yerevan time."
    nxt = day + OPEN if (now.weekday() < 5 and now < day + OPEN) else day + pd.Timedelta(days=1) + OPEN
    while nxt.weekday() >= 5:
        nxt += pd.Timedelta(days=1)
    local = nxt.tz_convert(LOCAL_TZ)
    return False, f"The US market is closed. It opens {local:%A at %H:%M} Yerevan time."


def to_local(ts: pd.Timestamp) -> str:
    return pd.Timestamp(ts).tz_convert(LOCAL_TZ).strftime("%H:%M")


# ---------------------------------------------------------------- rules


@dataclass
class SimTrade:
    day: object
    side: str  # "long" (buy first) or "short" (sell first)
    entry_time: pd.Timestamp
    entry: float
    stop: float
    target: float
    exit_time: pd.Timestamp | None = None
    exit: float = math.nan
    reason: str = ""

    @property
    def is_open(self) -> bool:
        return self.exit_time is None

    @property
    def move(self) -> float:
        """Price gain per share in the trade's direction."""
        return (self.exit - self.entry) * (1 if self.side == "long" else -1)


def _session_open(day: pd.DataFrame) -> pd.Timestamp:
    return day.index[0].normalize() + OPEN


def _day_complete(day: pd.DataFrame, is_last: bool) -> bool:
    return not is_last or day.index[-1] + BAR >= day.index[0].normalize() + CLOSE


def _walk_exit(trade: SimTrade, bars: pd.DataFrame, deadline: pd.Timestamp, exit_signal=None) -> None:
    """Move through bars after the entry until the stop, target, an exit signal or the deadline."""
    long = trade.side == "long"
    for ts, bar in bars.iterrows():
        end = ts + BAR
        hit_stop = bar.low <= trade.stop if long else bar.high >= trade.stop
        hit_target = (bar.high >= trade.target if long else bar.low <= trade.target) if not math.isnan(trade.target) else False
        if hit_stop:  # checked first: when both happen in one bar, assume the worse
            gap = bar.open < trade.stop if long else bar.open > trade.stop
            trade.exit, trade.reason = (bar.open if gap else trade.stop), "stop-loss"
        elif hit_target:
            gap = bar.open > trade.target if long else bar.open < trade.target
            trade.exit, trade.reason = (bar.open if gap else trade.target), "profit target"
        elif exit_signal is not None and exit_signal(ts):
            trade.exit, trade.reason = bar.close, "exit signal"
        elif end >= deadline:
            trade.exit, trade.reason = bar.close, "time limit"
        else:
            continue
        trade.exit_time = end
        return


def _deadline(entry_time: pd.Timestamp, p: dict, day: pd.DataFrame) -> pd.Timestamp:
    return min(entry_time + pd.Timedelta(minutes=p["max_hold_minutes"]), day.index[0].normalize() + CLOSE)


def orb_trades(day: pd.DataFrame, p: dict, history: pd.DataFrame | None = None) -> list[SimTrade]:
    """Opening range breakout: at most one trade a day."""
    start = _session_open(day)
    range_end = start + pd.Timedelta(minutes=p["opening_minutes"])
    ends = day.index + BAR
    opening = day[ends <= range_end]
    if opening.empty or ends[-1] < range_end:
        return []  # the range is still forming
    high, low = float(opening.high.max()), float(opening.low.min())
    window_end = range_end + pd.Timedelta(minutes=p["window_minutes"])
    after = day[ends > range_end]
    for i, (ts, bar) in enumerate(after.iterrows()):
        end = ts + BAR
        if end > window_end:
            break
        if bar.close > high:
            side, stop = "long", low
        elif not p.get("long_only", True) and bar.close < low:
            side, stop = "short", high
        else:
            continue
        entry = float(bar.close)
        risk = abs(entry - stop)
        if risk <= 0:
            continue
        target = entry + p["target_r"] * risk * (1 if side == "long" else -1)
        trade = SimTrade(ts.date(), side, end, entry, stop, target)
        _walk_exit(trade, after.iloc[i + 1:], _deadline(end, p, day))
        return [trade]
    return []


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def ema_trades(day: pd.DataFrame, p: dict, history: pd.DataFrame | None = None) -> list[SimTrade]:
    """Moving-average crossover (9/21 bars of 5 minutes), up to `max_trades` a day."""
    closes = day.close if history is None or history.empty else pd.concat([history.close.tail(40), day.close])
    fast, slow = _ema(closes, 9).loc[day.index], _ema(closes, 21).loc[day.index]
    above = fast > slow
    start = _session_open(day) + pd.Timedelta(minutes=p["opening_minutes"])
    window_end = start + pd.Timedelta(minutes=p["window_minutes"])
    trades: list[SimTrade] = []
    i, n = 1, len(day)
    while i < n and len(trades) < p["max_trades"]:
        ts = day.index[i]
        end = ts + BAR
        if end > window_end:
            break
        crossed_up = above.iloc[i] and not above.iloc[i - 1]
        crossed_down = not above.iloc[i] and above.iloc[i - 1]
        side = "long" if crossed_up else ("short" if crossed_down and not p.get("long_only", True) else None)
        if end <= start or side is None:
            i += 1
            continue
        entry = float(day.close.iloc[i])
        stop = entry * (1 - p["stop_pct"] / 100) if side == "long" else entry * (1 + p["stop_pct"] / 100)
        target = entry + p["target_r"] * (entry - stop)
        trade = SimTrade(ts.date(), side, end, entry, stop, target)

        def exit_signal(t, side=side):
            return (not above.loc[t]) if side == "long" else bool(above.loc[t])

        _walk_exit(trade, day.iloc[i + 1:], _deadline(end, p, day), exit_signal)
        trades.append(trade)
        if trade.is_open:
            break
        i = day.index.get_loc(trade.exit_time - BAR) + 1
    return trades


RULE_FUNCS = {"orb": orb_trades, "ema": ema_trades}


def rule_trades(day: pd.DataFrame, p: dict, history: pd.DataFrame | None = None, complete: bool = False) -> list[SimTrade]:
    trades = RULE_FUNCS[p["rule"]](day, p, history)
    if complete:  # e.g. a half-day session: close whatever is still open at the last price
        for t in trades:
            if t.is_open:
                t.exit, t.exit_time, t.reason = float(day.close.iloc[-1]), day.index[-1] + BAR, "market close"
    return trades


def opening_range(day: pd.DataFrame, minutes: int) -> tuple[float, float] | None:
    if day.empty:
        return None
    end = _session_open(day) + pd.Timedelta(minutes=minutes)
    opening = day[day.index + BAR <= end]
    return (float(opening.high.max()), float(opening.low.min())) if not opening.empty else None


# ---------------------------------------------------------------- live status


def live_status(day: pd.DataFrame, p: dict, history: pd.DataFrame | None = None) -> dict:
    """What the rule says right now, from today's finished bars."""
    if day.empty:
        return {"state": "waiting", "message": "No prices yet today.", "trades": []}
    last_end = day.index[-1] + BAR
    start = _session_open(day)
    range_end = start + pd.Timedelta(minutes=p["opening_minutes"])
    window_end = range_end + pd.Timedelta(minutes=p["window_minutes"])
    trades = rule_trades(day, p, history)
    rng = opening_range(day, p["opening_minutes"])
    if last_end < range_end:
        hi, lo = float(day.high.max()), float(day.low.min())
        label = "The opening range" if p["rule"] == "orb" else "The waiting period"
        return {"state": "waiting", "trades": trades,
                "message": f"{label} lasts until {to_local(range_end)} Yerevan time. "
                           f"So far: high {hi:,.2f}, low {lo:,.2f}. No trades yet."}
    if trades:
        t = trades[-1]
        if t.is_open and t.entry_time == last_end:
            verb = "BUY" if t.side == "long" else "SELL SHORT"
            return {"state": "buy", "trades": trades,
                    "message": f"Rule says {verb} now at about {t.entry:,.2f}. Stop-loss {t.stop:,.2f}, "
                               f"profit target {t.target:,.2f}; sell by {to_local(_deadline(t.entry_time, p, day))} at the latest."}
        if t.is_open:
            return {"state": "in_trade", "trades": trades,
                    "message": f"Rule is in a trade since {to_local(t.entry_time)} at {t.entry:,.2f}. Stop-loss "
                               f"{t.stop:,.2f}, target {t.target:,.2f}, time limit {to_local(_deadline(t.entry_time, p, day))}."}
        if t.exit_time == last_end:
            return {"state": "sell", "trades": trades,
                    "message": f"Rule says SELL now ({t.reason}) at about {t.exit:,.2f}: "
                               f"{t.move / t.entry:+.2%} on this trade."}
    if last_end < window_end and (not trades or p["rule"] == "ema"):
        hint = (f"It buys if a 5-minute bar closes above {rng[0]:,.2f}" if p["rule"] == "orb" and rng
                else "It buys if the fast average crosses above the slow one")
        return {"state": "watching", "trades": trades,
                "message": f"No signal right now. {hint} before {to_local(window_end)} Yerevan time."}
    if trades:
        total = sum(t.move / t.entry for t in trades if not t.is_open)
        return {"state": "done", "trades": trades,
                "message": f"Rule finished for this session: {len(trades)} trade(s), {total:+.2%} before fees."}
    return {"state": "done", "trades": trades,
            "message": "No trade this session: the rule's conditions didn't happen."}


# ---------------------------------------------------------------- testing a rule on past days


def position_size(equity: float, entry: float, stop: float, risk_pct: float, fractional: bool = True) -> float:
    """Shares so that hitting the stop loses about `risk_pct`% of the account, without borrowing
    (at most 99% of the account, leaving room for fees)."""
    per_share = abs(entry - stop)
    if per_share <= 0 or entry <= 0 or equity <= 0:
        return 0.0
    shares = min(equity * risk_pct / 100 / per_share, equity * 0.99 / entry)
    return float(math.floor(shares)) if not fractional else shares


@dataclass
class RuleTest:
    trades: pd.DataFrame
    daily: pd.Series  # net profit per trading day (0 on days without a trade)
    equity: pd.Series  # account value at the end of each day
    hold: pd.Series  # what the same money would be worth just holding the fund
    summary: dict


def backtest(bars: pd.DataFrame, p: dict, broker: Broker | None = None, start_cash: float | None = None) -> RuleTest:
    """Run the rule over every finished day in `bars`, with position sizing and fees."""
    broker = broker or Broker()
    cash = float(start_cash if start_cash is not None else p["start_cash"])
    days = sessions(bars)
    keys = list(days)
    rows, daily, prev = [], {}, None
    for k in keys:
        day = days[k]
        if not _day_complete(day, k == keys[-1]):
            continue
        day_net = 0.0
        for t in rule_trades(day, p, prev, complete=True):
            shares = position_size(cash, t.entry, t.stop, p["risk_pct"], broker.fractional)
            if shares <= 0:
                continue
            gross = t.move * shares
            fees = broker.order_fee(shares * t.entry, t.entry) + broker.order_fee(shares * t.exit, t.exit)
            net = gross - fees
            cash += net
            day_net += net
            rows.append({"day": k, "side": t.side, "in": to_local(t.entry_time), "entry": t.entry,
                         "out": to_local(t.exit_time), "exit": t.exit, "shares": shares, "why out": t.reason,
                         "gross": gross, "fees": fees, "net": net})
        daily[pd.Timestamp(k)] = day_net
        prev = day
    trades = pd.DataFrame(rows, columns=["day", "side", "in", "entry", "out", "exit", "shares", "why out",
                                         "gross", "fees", "net"])
    daily_s = pd.Series(daily, dtype=float).sort_index()
    start = float(start_cash if start_cash is not None else p["start_cash"])
    equity = start + daily_s.cumsum()
    wins, losses = trades[trades.net > 0], trades[trades.net <= 0]
    peak = equity.cummax() if not equity.empty else equity
    complete = {k: days[k] for k in keys if _day_complete(days[k], k == keys[-1])}
    first_open = float(next(iter(complete.values())).open.iloc[0]) if complete else math.nan
    hold_curve = pd.Series({pd.Timestamp(k): start * float(d.close.iloc[-1]) / first_open for k, d in complete.items()},
                           dtype=float)
    hold = float(hold_curve.iloc[-1] / start - 1) if len(hold_curve) else math.nan
    summary = {
        "days": len(daily_s),
        "trades": len(trades),
        "win_rate": len(wins) / len(trades) if len(trades) else math.nan,
        "avg_win": float(wins.net.mean()) if len(wins) else 0.0,
        "avg_loss": float(losses.net.mean()) if len(losses) else 0.0,
        "net": float(trades.net.sum()) if len(trades) else 0.0,
        "fees": float(trades.fees.sum()) if len(trades) else 0.0,
        "return": float(trades.net.sum()) / start if len(trades) else 0.0,
        "per_day": float(daily_s.mean()) if len(daily_s) else 0.0,
        "best_day": float(daily_s.max()) if len(daily_s) else 0.0,
        "worst_day": float(daily_s.min()) if len(daily_s) else 0.0,
        "days_traded": int((daily_s != 0).sum()),
        "green_days": float((daily_s[daily_s != 0] > 0).mean()) if (daily_s != 0).any() else math.nan,
        "max_drawdown": float((equity / peak - 1).min()) if len(equity) else 0.0,
        "buy_and_hold": hold,
        "start_cash": start,
    }
    return RuleTest(trades, daily_s, equity, hold_curve, summary)


def verdict(s: dict) -> str:
    """A plain-language reading of a rule test."""
    if s["trades"] < 10:
        return "Too few trades to judge. Test a longer period or a different setting."
    hold = f" Simply holding the fund for the same days would have given {s['buy_and_hold']:+.1%}." \
        if not math.isnan(s["buy_and_hold"]) else ""
    if s["net"] <= 0:
        return (f"This rule lost money over these {s['days']} days after fees ({s['return']:+.1%} of the account)."
                f"{hold} Don't trade it with real money.")
    return (f"This rule made {s['return']:+.1%} over these {s['days']} days after fees, winning "
            f"{s['win_rate']:.0%} of trades.{hold} About 60 days is a short test, and luck can look like skill: "
            "practice with pretend money for at least a month and see whether your own results match.")


# ---------------------------------------------------------------- pretend-money account


@dataclass
class PaperTrade:
    ticker: str
    side: str  # "long" or "short"
    shares: float
    entry_time: str  # Yerevan time, "YYYY-MM-DD HH:MM"
    entry_price: float
    entry_fee: float = 0.0
    exit_time: str = ""
    exit_price: float = 0.0
    exit_fee: float = 0.0
    followed_rule: bool = True
    note: str = ""

    @property
    def closed(self) -> bool:
        return bool(self.exit_time)

    @property
    def sign(self) -> int:
        return 1 if self.side == "long" else -1

    def value_change(self, price: float) -> float:
        return self.sign * (price - self.entry_price) * self.shares

    @property
    def net(self) -> float:
        if not self.closed:
            return math.nan
        return self.value_change(self.exit_price) - self.entry_fee - self.exit_fee

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PaperTrade":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


def now_local() -> str:
    return pd.Timestamp.now(tz=LOCAL_TZ).strftime("%Y-%m-%d %H:%M")


class PaperAccount:
    """Pretend-money account stored in `AppState.practice` (changes are made in place)."""

    def __init__(self, data: dict):
        self.data = data

    @property
    def trades(self) -> list[PaperTrade]:
        return [PaperTrade.from_dict(t) for t in self.data.get("trades", [])]

    @property
    def open(self) -> PaperTrade | None:
        return PaperTrade.from_dict(self.data["open"]) if self.data.get("open") else None

    def realized(self) -> float:
        return sum(t.net for t in self.trades)

    def equity(self, price: float | None = None) -> float:
        """Start money + closed results + the open trade valued at `price` (after its entry fee)."""
        value = float(self.data["start_cash"]) + self.realized()
        o = self.open
        if o is not None:
            value += (o.value_change(price) if price else 0.0) - o.entry_fee
        return value

    def day_result(self, day: str) -> float:
        return sum(t.net for t in self.trades if t.exit_time[:10] == day)

    def trades_on(self, day: str) -> int:
        n = sum(1 for t in self.trades if t.entry_time[:10] == day)
        return n + (1 if self.open and self.open.entry_time[:10] == day else 0)

    def can_open(self, day: str, loss_limit_usd: float) -> str | None:
        """None if a new trade is allowed, otherwise the reason it isn't."""
        if self.open is not None:
            return "Close your open trade first."
        if loss_limit_usd > 0 and self.day_result(day) <= -loss_limit_usd:
            return "Daily loss limit reached: stop trading for today. This rule protects you from chasing losses."
        if self.trades_on(day) >= int(self.data.get("max_trades", 3)):
            return "You've reached your maximum number of trades for today."
        return None

    def open_trade(self, ticker: str, side: str, shares: float, price: float, fee: float = 0.0,
                   followed_rule: bool = True, note: str = "", when: str | None = None, loss_limit_usd: float = 0.0) -> None:
        when = when or now_local()
        problem = self.can_open(when[:10], loss_limit_usd)
        if problem:
            raise ValueError(problem)
        if shares <= 0 or price <= 0:
            raise ValueError("Shares and price must be positive.")
        if shares * price + fee > self.equity() + 1e-9:
            raise ValueError("That's more than your pretend account holds. Practice without borrowing.")
        self.data["open"] = PaperTrade(ticker.upper(), side, float(shares), when, float(price), float(fee),
                                       followed_rule=followed_rule, note=note).to_dict()

    def close_trade(self, price: float, fee: float = 0.0, when: str | None = None) -> PaperTrade:
        o = self.open
        if o is None:
            raise ValueError("There is no open trade.")
        if price <= 0:
            raise ValueError("Price must be positive.")
        o.exit_time, o.exit_price, o.exit_fee = when or now_local(), float(price), float(fee)
        self.data.setdefault("trades", []).append(o.to_dict())
        self.data["open"] = None
        return o

    def reset(self) -> None:
        self.data["trades"], self.data["open"] = [], None

    def scorecard(self) -> dict:
        trades = self.trades
        nets = [t.net for t in trades]
        wins = [n for n in nets if n > 0]
        losses = [n for n in nets if n <= 0]
        by_day: dict[str, float] = {}
        for t in trades:
            by_day[t.exit_time[:10]] = by_day.get(t.exit_time[:10], 0.0) + t.net
        days = pd.Series(by_day, dtype=float).sort_index()
        return {
            "trades": len(trades),
            "win_rate": len(wins) / len(trades) if trades else math.nan,
            "avg_win": float(np.mean(wins)) if wins else 0.0,
            "avg_loss": float(np.mean(losses)) if losses else 0.0,
            "total": float(sum(nets)),
            "followed_rule": sum(t.followed_rule for t in trades) / len(trades) if trades else math.nan,
            "by_day": days,
            "green_days": float((days > 0).mean()) if len(days) else math.nan,
        }
