import math

import numpy as np
import pandas as pd
import pytest

from investapp import practice as pr
from investapp.fees import Broker

NY = pr.MARKET_TZ


def make_day(date: str, closes, highs=None, lows=None, opens=None) -> pd.DataFrame:
    closes = np.asarray(closes, dtype=float)
    idx = pd.date_range(f"{date} 09:30", periods=len(closes), freq="5min", tz=NY)
    highs = np.asarray(highs if highs is not None else closes + 0.05, dtype=float)
    lows = np.asarray(lows if lows is not None else closes - 0.05, dtype=float)
    opens = np.asarray(opens if opens is not None else closes, dtype=float)
    return pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes, "volume": 1000}, index=idx)


def orb_day(date="2026-10-13", after=(101.6,), after_high=None, after_low=None, after_open=None, n=78):
    """Opening range 100-101 for 30 minutes, a breakout bar closing at 101.5, then `after` bars."""
    closes = [100.5] * 6 + [101.5]
    highs = [101.0] * 6 + [101.6]
    lows = [100.0] * 6 + [100.9]
    opens = [100.5] * 6 + [100.9]
    rest = list(after) + [after[-1]] * (n - 7 - len(after))
    closes += rest
    highs += list(after_high or []) + [c + 0.05 for c in rest[len(after_high or []):]]
    lows += list(after_low or []) + [c - 0.05 for c in rest[len(after_low or []):]]
    opens += list(after_open or []) + rest[len(after_open or []):]
    return make_day(date, closes, highs, lows, opens)


P = {**pr.new_practice(), "rule": "orb"}


# ---------------------------------------------------------------- rules

def test_orb_profit_target():
    day = orb_day(after=(102, 103, 104.2), after_high=(102.1, 103.1, 104.6))
    (t,) = pr.orb_trades(day, P)
    assert (t.side, t.entry, t.stop, t.target) == ("long", 101.5, 100.0, pytest.approx(104.5))
    assert t.entry_time == pd.Timestamp("2026-10-13 10:05", tz=NY)
    assert (t.exit, t.reason) == (pytest.approx(104.5), "profit target")
    assert t.exit_time == pd.Timestamp("2026-10-13 10:20", tz=NY)


def test_orb_stop_loss_and_gap():
    day = orb_day(after=(101.0,), after_low=(99.8,), after_open=(101.2,))
    (t,) = pr.orb_trades(day, P)
    assert (t.exit, t.reason) == (100.0, "stop-loss")
    gap = orb_day(after=(99.6,), after_low=(99.4,), after_open=(99.5,))
    (g,) = pr.orb_trades(gap, P)
    assert g.exit == 99.5  # opened below the stop: sold at the open, a bigger loss


def test_orb_time_limit_and_no_breakout():
    (t,) = pr.orb_trades(orb_day(after=(101.6,)), P)
    assert t.reason == "time limit"
    assert t.exit_time == pd.Timestamp("2026-10-13 11:05", tz=NY)  # 60 minutes after entry
    flat = make_day("2026-10-13", [100.5] * 78, [101.0] * 78, [100.0] * 78)
    assert pr.orb_trades(flat, P) == []


def test_orb_short_side_only_when_allowed():
    closes = [100.5] * 6 + [99.5] + [99.5] * 71
    day = make_day("2026-10-13", closes, [101.0] * 6 + [100.4] + [99.6] * 71, [100.0] * 6 + [99.4] + [99.4] * 71)
    assert pr.orb_trades(day, P) == []
    (t,) = pr.orb_trades(day, {**P, "long_only": False})
    assert t.side == "short" and t.stop == 101.0


def test_ema_crossover_trades_in_window():
    # Falls during the first half hour, then climbs: the averages cross upward around 10:30.
    closes = [100] * 2 + list(np.linspace(100, 99, 4)) + list(np.linspace(99.1, 101.5, 12)) + [101.5] * 60
    day = make_day("2026-10-13", closes)
    trades = pr.ema_trades(day, {**P, "rule": "ema"})
    assert trades and all(t.side == "long" for t in trades)
    window_start = pd.Timestamp("2026-10-13 10:00", tz=NY)
    assert all(window_start < t.entry_time <= window_start + pd.Timedelta(minutes=60) for t in trades)
    assert all(not t.is_open for t in trades)


# ---------------------------------------------------------------- live status

def test_live_status_through_the_day():
    full = orb_day(after=(102, 103, 104.2), after_high=(102.1, 103.1, 104.6))
    status = lambda n: pr.live_status(full.iloc[:n], P)["state"]
    assert status(3) == "waiting"
    assert status(7) == "buy"
    assert status(8) == "in_trade"
    assert status(10) == "sell"
    assert status(78) == "done"
    no_break = make_day("2026-10-13", [100.5] * 8, [101.0] * 8, [100.0] * 8)
    s = pr.live_status(no_break, P)
    assert s["state"] == "watching" and "101.00" in s["message"]
    assert pr.live_status(no_break.iloc[:0], P)["state"] == "waiting"


def test_complete_bars_and_market_status():
    day = orb_day()
    now = pd.Timestamp("2026-10-13 10:07", tz=NY)
    assert pr.complete_bars(day, now).index[-1] == pd.Timestamp("2026-10-13 10:00", tz=NY)
    is_open, text = pr.market_status(pd.Timestamp("2026-10-13 14:00", tz="UTC"))
    assert is_open and "00:00 Yerevan" in text
    is_open, text = pr.market_status(pd.Timestamp("2026-10-17 12:00", tz="UTC"))  # Saturday
    assert not is_open and "Monday at 17:30" in text
    _, text = pr.market_status(pd.Timestamp("2026-11-07 12:00", tz="UTC"))  # after US clocks change
    assert "Monday at 18:30" in text


# ---------------------------------------------------------------- testing on past days

def test_backtest_sizing_fees_and_summary():
    win = orb_day("2026-10-12", after=(102, 103, 104.2), after_high=(102.1, 103.1, 104.6))
    loss = orb_day("2026-10-13", after=(101.0,), after_low=(99.8,), after_open=(101.2,))
    bars = pd.concat([win, loss])
    res = pr.backtest(bars, P, Broker(), start_cash=1000)
    assert list(res.trades.net.round(4)) == [pytest.approx(20.0), pytest.approx(-10.2)]  # 1% risk, compounding
    s = res.summary
    assert (s["trades"], s["win_rate"], s["days"]) == (2, 0.5, 2)
    assert s["net"] == pytest.approx(9.8) and res.equity.iloc[-1] == pytest.approx(1009.8)
    assert s["buy_and_hold"] == pytest.approx(101.0 / 100.5 - 1, abs=1e-3)
    with_fees = pr.backtest(bars, P, Broker("x", min_fee=1.0), start_cash=1000)
    assert with_fees.summary["fees"] == pytest.approx(4.0)
    whole = pr.backtest(bars, P, Broker("x", fractional=False), start_cash=1000)
    assert list(whole.trades.shares) == [6.0, 6.0]
    assert "Too few trades" in pr.verdict(s)


def test_backtest_skips_unfinished_today_and_verdicts():
    days = [orb_day(f"2026-09-{d:02d}", after=(101.0,), after_low=(99.8,), after_open=(101.2,)) for d in range(1, 13)]
    partial = orb_day("2026-09-14").iloc[:20]
    res = pr.backtest(pd.concat(days + [partial]), P, Broker(), start_cash=1000)
    assert res.summary["days"] == 12 and res.summary["net"] < 0
    assert "lost money" in pr.verdict(res.summary)
    good = {**res.summary, "net": 50.0, "return": 0.05, "win_rate": 0.6}
    assert "luck can look like skill" in pr.verdict(good)


def test_position_size():
    assert pr.position_size(1000, 100, 98, 1.0) == pytest.approx(5)  # lose $10 = 1% if the stop is hit
    assert pr.position_size(1000, 100, 99.9, 1.0) == pytest.approx(9.9)  # capped: no borrowing, room for fees
    assert pr.position_size(1000, 101.5, 100, 1.0, fractional=False) == 6
    assert pr.position_size(1000, 100, 100, 1.0) == 0


# ---------------------------------------------------------------- pretend account

def test_paper_account_flow_limits_and_scorecard():
    data = {**pr.new_practice(), "start_cash": 1000.0, "max_trades": 3}
    acct = pr.PaperAccount(data)
    acct.open_trade("spy", "long", 2, 100, fee=0.5, when="2026-10-13 17:40")
    assert acct.equity(105) == pytest.approx(1000 + 10 - 0.5)
    with pytest.raises(ValueError, match="Close your open trade"):
        acct.open_trade("SPY", "long", 1, 100, when="2026-10-13 17:45")
    acct.close_trade(90, fee=0.5, when="2026-10-13 18:00")
    assert acct.realized() == pytest.approx(-21)
    assert acct.can_open("2026-10-13", loss_limit_usd=20).startswith("Daily loss limit")
    assert acct.can_open("2026-10-14", loss_limit_usd=20) is None  # a new day
    with pytest.raises(ValueError, match="more than your pretend account"):
        acct.open_trade("SPY", "long", 100, 100, when="2026-10-14 17:40")
    acct.open_trade("SPY", "short", 1, 100, followed_rule=False, when="2026-10-14 17:40")
    acct.close_trade(95, when="2026-10-14 17:50")
    card = acct.scorecard()
    assert card["trades"] == 2 and card["win_rate"] == 0.5 and card["total"] == pytest.approx(-16)
    assert card["followed_rule"] == 0.5 and list(card["by_day"].round(2)) == [-21, 5]
    acct.reset()
    assert acct.trades == [] and acct.open is None and acct.equity() == 1000


def test_max_trades_per_day():
    acct = pr.PaperAccount({**pr.new_practice(), "max_trades": 1})
    acct.open_trade("SPY", "long", 1, 100, when="2026-10-13 17:40")
    acct.close_trade(101, when="2026-10-13 17:45")
    assert "maximum number of trades" in acct.can_open("2026-10-13", 0)


def test_fetch_intraday_shapes_yahoo_data(monkeypatch):
    import yfinance

    idx = pd.date_range("2026-10-13 13:30", periods=3, freq="5min", tz="UTC")
    cols = pd.MultiIndex.from_product([["Adj Close", "Close", "High", "Low", "Open", "Volume"], ["SPY"]],
                                      names=["Price", "Ticker"])
    raw = pd.DataFrame(np.arange(18, dtype=float).reshape(3, 6), index=idx, columns=cols)
    monkeypatch.setattr(yfinance, "download", lambda *a, **k: raw)
    df = pr.fetch_intraday("SPY")
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert str(df.index.tz) == NY and df.index[0].hour == 9
    monkeypatch.setattr(yfinance, "download", lambda *a, **k: pd.DataFrame())
    assert pr.fetch_intraday("SPY").empty
    assert not math.isnan(1.0)
