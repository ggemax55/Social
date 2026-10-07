import math

import numpy as np
import pandas as pd
import pytest

from investapp.backtest import backtest_lump_sum, backtest_plan, compare_frequencies, xirr
from investapp.indicators import analyze, classify_trend, period_return, rsi, summary_table
from investapp.planner import Plan, allocate_contribution, next_dates, project_growth, rebalance_trades, schedule
from investapp.portfolio import (
    Transaction,
    compute_holdings,
    period_performance,
    realized_total,
    value_history,
    value_holdings,
)
from investapp.report import build_report
from investapp.storage import AppState, from_json, load_state, save_state, to_json


def bdays(start="2024-01-01", periods=300):
    return pd.bdate_range(start, periods=periods)


# ---------- indicators ----------

def test_period_returns_use_last_close_on_or_before_start():
    idx = pd.to_datetime(["2025-12-30", "2025-12-31", "2026-01-02", "2026-01-09"])
    s = pd.Series([100.0, 110.0, 121.0, 132.0], index=idx)
    assert period_return(s, "1D") == pytest.approx(132 / 121 - 1)
    assert period_return(s, "YTD") == pytest.approx(132 / 110 - 1)
    assert period_return(s, "1W") == pytest.approx(132 / 121 - 1)
    assert math.isnan(period_return(s, "1Y"))


def test_rsi_extremes():
    up = pd.Series(np.arange(1.0, 40.0), index=bdays(periods=39))
    assert rsi(up).iloc[-1] == pytest.approx(100.0)
    down = pd.Series(np.arange(40.0, 1.0, -1), index=bdays(periods=39))
    assert rsi(down).iloc[-1] == pytest.approx(0.0)
    flat = pd.Series(5.0, index=bdays(periods=39))
    assert rsi(flat).iloc[-1] == pytest.approx(50.0)


def test_trend_classification_and_signals():
    assert classify_trend(110, 105, 100) == "Uptrend"
    assert classify_trend(90, 95, 100) == "Downtrend"
    assert classify_trend(105, 95, 100) == "Mixed"
    rising = pd.Series(np.linspace(100, 200, 300), index=bdays())
    a = analyze(rising, "UP")
    assert a.trend == "Uptrend"
    assert any("overbought" in s.message for s in a.signals)
    crash = pd.Series(np.r_[np.linspace(100, 200, 250), np.linspace(200, 120, 50)], index=bdays())
    b = analyze(crash, "DOWN")
    assert b.from_high == pytest.approx(-0.4)
    assert any("bear-market" in s.message for s in b.signals)


def test_summary_table_skips_empty_columns():
    px = pd.DataFrame({"A": np.linspace(10, 20, 300), "B": np.nan}, index=bdays())
    table = summary_table(px, {"A": "Alpha"})
    assert list(table["ticker"]) == ["A"]
    assert table.loc[0, "name"] == "Alpha"


# ---------- portfolio ----------

def test_average_cost_holdings_and_realized_pl():
    txs = [
        Transaction("2024-01-02", "abc", "buy", 10, 100, fee=10),
        Transaction("2024-02-01", "ABC", "buy", 10, 120),
        Transaction("2024-03-01", "ABC", "sell", 5, 150, fee=5),
    ]
    h = compute_holdings(txs)
    row = h.iloc[0]
    # cost 1010 + 1200 = 2210 for 20 shares; selling 5 removes 552.5
    assert row["shares"] == pytest.approx(15)
    assert row["cost_basis"] == pytest.approx(2210 * 15 / 20)
    assert row["realized_pl"] == pytest.approx((750 - 5) - 552.5)
    assert realized_total(txs) == pytest.approx(192.5)

    v = value_holdings(h, {"ABC": 200.0})
    assert v.loc[0, "market_value"] == pytest.approx(3000)
    assert v.loc[0, "weight"] == pytest.approx(1.0)


def test_overselling_is_rejected():
    with pytest.raises(ValueError, match="only 1 held"):
        compute_holdings([Transaction("2024-01-02", "X", "buy", 1, 10), Transaction("2024-01-03", "X", "sell", 2, 10)])


def test_closed_position_keeps_realized_pl():
    txs = [Transaction("2024-01-02", "X", "buy", 2, 10), Transaction("2024-01-03", "X", "sell", 2, 15)]
    assert compute_holdings(txs).empty
    assert realized_total(txs) == pytest.approx(10)


def test_value_history_and_period_performance_exclude_contributions():
    idx = bdays("2024-01-01", 30)
    px = pd.DataFrame({"X": np.full(30, 10.0)}, index=idx)
    px.iloc[20:, 0] = 12.0
    txs = [
        Transaction("2024-01-06", "X", "buy", 10, 10),  # Saturday -> executes Monday 8th
        Transaction("2024-01-15", "X", "buy", 10, 10),
    ]
    hist = value_history(txs, px)
    assert hist.index[0] == pd.Timestamp("2024-01-08")
    assert hist["invested"].iloc[-1] == pytest.approx(200)
    assert hist["value"].iloc[-1] == pytest.approx(240)
    all_time = period_performance(hist, "ALL")
    assert all_time["gain"] == pytest.approx(40)
    assert all_time["gain_pct"] == pytest.approx(0.2)
    day = period_performance(hist, "1D")
    assert day["gain"] == pytest.approx(0)


# ---------- planner ----------

def test_schedules():
    # Month-end is clamped; Sunday Mar 31 moves to Monday Apr 1.
    assert [str(d.date()) for d in schedule("monthly", "2024-01-31", "2024-04-30")] == [
        "2024-01-31", "2024-02-29", "2024-04-01", "2024-04-30"
    ]
    assert all(d.weekday() == 0 for d in schedule("weekly", "2024-01-06", "2024-02-01"))  # Saturday start
    weekly = schedule("weekly", "2024-01-03", "2024-02-01")
    assert all(d.weekday() == 2 for d in weekly) and len(weekly) == 5
    daily = schedule("daily", "2024-01-05", "2024-01-09")  # Fri..Tue
    assert [d.day for d in daily] == [5, 8, 9]
    assert schedule("yearly", "2020-02-28", "2023-03-01")[1] == pd.Timestamp("2021-03-01")  # Sun -> Mon
    assert schedule("yearly", "2020-02-29", "2023-03-01")[2] == pd.Timestamp("2022-02-28")


def test_next_dates_and_weekly_jump():
    plan = Plan("w", 50, "weekly", {"VOO": 1}, start_date="2020-01-06")  # a Monday
    nxt = next_dates(plan, today="2026-10-07", n=2)
    assert nxt == [pd.Timestamp("2026-10-12"), pd.Timestamp("2026-10-19")]


def test_allocation_empty_portfolio_follows_targets():
    orders, left = allocate_contribution(1000, {"A": 60, "B": 40}, {}, {"A": 10, "B": 20})
    assert dict(zip(orders.ticker, orders.amount)) == pytest.approx({"A": 600, "B": 400})
    assert dict(zip(orders.ticker, orders.shares)) == pytest.approx({"A": 60, "B": 20})
    assert left == 0


def test_allocation_steers_new_money_to_underweight_assets():
    orders, _ = allocate_contribution(100, {"A": 50, "B": 50}, {"A": 900, "B": 100}, {"A": 1, "B": 1})
    amounts = dict(zip(orders.ticker, orders.amount))
    assert amounts["A"] == pytest.approx(0)
    assert amounts["B"] == pytest.approx(100)
    assert sum(amounts.values()) == pytest.approx(100)


def test_whole_share_allocation_spends_leftover_greedily():
    orders, left = allocate_contribution(250, {"A": 50, "B": 50}, {}, {"A": 100, "B": 30}, whole_shares=True)
    shares = dict(zip(orders.ticker, orders.shares))
    spent = shares["A"] * 100 + shares["B"] * 30
    assert spent + left == pytest.approx(250)
    assert left < 30  # can't afford another share of anything
    assert shares["A"] >= 1 and shares["B"] >= 4


def test_rebalance_and_projection():
    rb = rebalance_trades({"A": 50, "B": 50}, {"A": 700, "B": 300})
    trades = dict(zip(rb.ticker, rb.trade_value))
    assert trades == pytest.approx({"A": -200, "B": 200})
    assert rb["needs_rebalance"].all()

    zero = project_growth(100, "monthly", 2, 0.0)
    assert zero["value"].iloc[-1] == pytest.approx(2400)
    grow = project_growth(1000, "yearly", 2, 0.10)
    assert grow["value"].iloc[-1] == pytest.approx(1000 * 1.1 ** 2 + 1000 * 1.1)


def test_plan_validation():
    with pytest.raises(ValueError):
        Plan("bad", 100, "hourly", {"A": 1})
    with pytest.raises(ValueError):
        Plan("bad", 100, "weekly", {"A": 0})


# ---------- backtest ----------

def test_xirr_simple():
    flows = [(pd.Timestamp("2020-01-01"), -100.0), (pd.Timestamp("2021-01-01"), 110.0)]
    assert xirr(flows) == pytest.approx(0.10, abs=1e-3)


def test_backtest_flat_prices_returns_nothing():
    px = pd.DataFrame({"A": 50.0}, index=bdays("2023-01-02", 260))
    res = backtest_plan(px, {"A": 1}, 100, "monthly", "2023-01-02")
    assert res.contributions == 12
    assert res.total_invested == pytest.approx(1200)
    assert res.final_value == pytest.approx(1200)


def test_backtest_two_assets_keeps_targets_and_compare():
    idx = bdays("2022-01-03", 520)
    px = pd.DataFrame({"A": np.linspace(10, 20, 520), "B": np.full(520, 10.0)}, index=idx)
    res = backtest_plan(px, {"A": 50, "B": 50}, 100, "weekly", idx[0])
    assert res.final_value > res.total_invested
    assert res.annualized > 0
    lump = backtest_lump_sum(px, {"A": 1}, 1000, idx[0])
    assert lump.final_value == pytest.approx(2000)
    table = compare_frequencies(px, {"A": 1}, 1200, idx[0])
    assert len(table) == 5
    assert table["invested"].iloc[2] == pytest.approx(table["invested"].iloc[4])


# ---------- storage & report ----------

def test_state_round_trip(tmp_path):
    state = AppState(
        transactions=[Transaction("2024-01-02", "VOO", "buy", 1, 400)],
        plans=[Plan("Core", 100, "monthly", {"VOO": 70, "BND": 30}, start_date="2024-01-01")],
    )
    path = tmp_path / "p.json"
    save_state(state, path)
    loaded = load_state(path)
    assert to_json(loaded) == to_json(state)
    assert from_json(to_json(state)).plans[0].targets["VOO"] == pytest.approx(0.7)
    assert load_state(tmp_path / "missing.json").transactions == []


@pytest.mark.parametrize("kind", ["daily", "weekly", "monthly", "yearly"])
def test_build_report(kind):
    idx = bdays("2024-06-03", 400)
    px = pd.DataFrame(
        {
            "SPY": np.linspace(400, 500, 400),
            "BND": np.linspace(70, 72, 400),
            "VOO": np.linspace(380, 470, 400),
            "^VIX": np.full(400, 16.0),
        },
        index=idx,
    )
    state = AppState(
        watchlist=["SPY"],
        market_overview=["SPY", "BND", "^VIX", "MISSING"],
        transactions=[Transaction("2024-07-01", "VOO", "buy", 2, 390)],
        plans=[Plan("Core", 100, "monthly", {"VOO": 70, "BND": 30}, start_date="2024-06-07", whole_shares=True)],
    )
    text = build_report(kind, state, px, today=idx[-1])
    assert f"# {kind.capitalize()} investment report" in text
    assert "S&P 500" in text and "VIX 16.0" in text
    assert "| VOO |" in text
    assert "Core" in text
    if kind == "yearly":
        assert "Yearly check-up" in text
