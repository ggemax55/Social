import math

import numpy as np
import pandas as pd
import pytest

from investapp.actions import build_tasks, complete_task, pending_dates, plan_orders, skip_missed, skip_task
from investapp.fees import BROKER_PRESETS, Broker
from investapp.money import fmt, fmt_both, fx_rate, to_usd
from investapp.planner import Plan, allocate_contribution
from investapp.portfolio import Transaction
from investapp.storage import AppState, from_json, to_json

TODAY = pd.Timestamp("2026-10-07")  # a Wednesday
IBKR = BROKER_PRESETS["Interactive Brokers (direct account)"]
ACBA = BROKER_PRESETS["Interactive Brokers via Acba bank"]
FREEDOM = BROKER_PRESETS["Freedom Broker Armenia"]


def prices(drop_last=0.0):
    idx = pd.bdate_range(end=TODAY, periods=300)
    vt = np.full(300, 100.0)
    vt[-1] = 100.0 * (1 + drop_last)
    return pd.DataFrame({"VT": vt, "BND": np.full(300, 50.0), "AMD=X": np.full(300, 400.0)}, index=idx)


def state_with(*plans, broker=IBKR):
    s = AppState(broker=broker.to_dict(), allowed_tickers=["VT", "BND"])
    for p in plans:
        s.add_plan(p)
    return s


# ---------- fees & money ----------

def test_broker_fees():
    assert IBKR.order_fee(10, 100) == pytest.approx(0.10)  # capped at 1%
    assert IBKR.order_fee(1000, 100) == pytest.approx(0.35)  # minimum
    assert ACBA.order_fee(100, 50) == pytest.approx(4.0)
    assert FREEDOM.order_fee(10_000, 100) == pytest.approx(12.0)
    assert FREEDOM.min_good_order() == 240  # 1.20 / 0.5%
    assert ACBA.min_good_order() == 800
    assert IBKR.min_good_order() == 70
    assert Broker(pct=0.02).min_good_order() == math.inf
    assert Broker().min_good_order() == 0.0


def test_money_helpers():
    assert fx_rate({"AMD=X": 390.0}, "AMD") == 390.0
    assert fx_rate({}, "USD") == 1.0
    assert math.isnan(fx_rate({}, "AMD"))
    assert to_usd(39_000, "AMD", 390) == pytest.approx(100)
    assert fmt(12345.6, "AMD") == "12,346 AMD"
    assert fmt_both(10, "AMD", 390) == "10.00 USD (3,900 AMD)"


def test_single_order_buys_only_the_most_underweight():
    orders, _ = allocate_contribution(100, {"A": 50, "B": 50}, {"A": 300, "B": 100}, {"A": 10, "B": 10}, single_order=True)
    amounts = dict(zip(orders.ticker, orders.amount))
    assert amounts == pytest.approx({"A": 0, "B": 100})


# ---------- tasks ----------

def test_amd_plan_creates_buy_task_with_fees_and_completes():
    plan = Plan("Weekly world", 40_000, "weekly", {"VT": 100}, start_date=TODAY, currency="AMD")
    s = state_with(plan)
    tasks = build_tasks(s, prices(), TODAY)
    buy = next(t for t in tasks if t.kind == "buy")
    assert buy.total_usd == pytest.approx(100)  # 40,000 AMD at 400 AMD/USD
    assert buy.orders["fee"].sum() == pytest.approx(0.35)
    assert buy.orders["amount"].sum() + buy.orders["fee"].sum() == pytest.approx(100)
    trades = [Transaction(str(TODAY.date()), "VT", "buy", 0.9915, 100.0, 0.35)]  # actual fill: 99.50 spent
    complete_task(s, buy, trades, TODAY)
    assert len(s.transactions) == 1
    assert s.plans[0].pot == pytest.approx(0.50 * 400)  # 50 cents left over, kept in AMD
    assert not [t for t in build_tasks(s, prices(), TODAY) if t.kind == "buy"]


def test_save_then_buy_threshold():
    plan = Plan("Daily", 4_000, "daily", {"VT": 100}, start_date=TODAY, currency="AMD", buy_threshold=10_000)
    s = state_with(plan)
    save = next(t for t in build_tasks(s, prices(), TODAY) if t.kind == "save")
    assert "Set aside 4,000 AMD" in save.title
    complete_task(s, save, today=TODAY)
    assert s.plans[0].pot == 4_000
    tomorrow = TODAY + pd.Timedelta(days=1)
    complete_task(s, next(t for t in build_tasks(s, prices(), tomorrow) if t.kind == "save"), today=tomorrow)
    friday = TODAY + pd.Timedelta(days=2)
    buy = next(t for t in build_tasks(s, prices(), friday) if t.kind == "buy")
    assert buy.total_usd == pytest.approx(12_000 / 400)  # 8,000 saved + 4,000 today


def test_missed_days_are_combined_and_can_be_skipped():
    plan = Plan("Daily", 10, "daily", {"VT": 100}, start_date="2026-10-01")
    s = state_with(plan, broker=Broker())
    assert len(pending_dates(plan, s.task_log, TODAY)) == 5  # Thu, Fri, Mon, Tue, Wed
    buy = next(t for t in build_tasks(s, prices(), TODAY) if t.kind == "buy")
    assert buy.overdue == 4 and buy.total_usd == pytest.approx(50)
    assert skip_missed(s, plan, TODAY) == 4
    buy = next(t for t in build_tasks(s, prices(), TODAY) if t.kind == "buy")
    assert buy.total_usd == pytest.approx(10)
    skip_task(s, buy, TODAY)
    assert not [t for t in build_tasks(s, prices(), TODAY) if t.kind == "buy"]


def test_whole_shares_broker_turns_small_amount_into_saving():
    plan = Plan("Daily", 20, "daily", {"VT": 100}, start_date=TODAY)
    s = state_with(plan, broker=FREEDOM)  # no fractional shares; VT costs 100
    task = next(t for t in build_tasks(s, prices(), TODAY) if t.plan_id == plan.id)
    assert task.kind == "save" and "whole share" in task.detail


def test_expensive_fee_and_allowed_list_warnings():
    plan = Plan("Mix", 50, "weekly", {"VT": 50, "QQQ": 50}, start_date=TODAY)
    px = prices().assign(QQQ=100.0)
    s = state_with(plan, broker=ACBA)
    buy = next(t for t in build_tasks(s, px, TODAY) if t.kind in ("buy", "save"))
    assert buy.kind == "save"  # $50 can't buy a whole $100 share after fees
    s.plans[0].amount = 500
    buy = next(t for t in build_tasks(s, px, TODAY) if t.kind == "buy")
    text = " ".join(buy.warnings)
    assert "QQQ is not on your broker's list" in text
    assert "Fees take" in text


def test_dip_extra_is_optional_and_weekly():
    plan = Plan("Dip", 100, "monthly", {"VT": 100}, start_date=TODAY, dip_boost=0.5)
    s = state_with(plan, broker=Broker())
    tasks = build_tasks(s, prices(drop_last=-0.15), TODAY)
    extra = next(t for t in tasks if t.kind == "extra")
    assert extra.priority == 2 and extra.total_usd == pytest.approx(50)
    skip_task(s, extra, TODAY)
    assert not [t for t in build_tasks(s, prices(drop_last=-0.15), TODAY) if t.kind == "extra"]


def test_setup_routine_and_review_tasks():
    s = AppState()
    kinds = [t.key for t in build_tasks(s, prices(), TODAY)]
    assert kinds == ["setup:broker", "setup:plans"]

    plan = Plan("Mix", 100, "monthly", {"VT": 50, "BND": 50}, start_date="2026-09-07")
    s = state_with(plan)
    s.transactions = [Transaction("2026-09-08", "VT", "buy", 9, 100), Transaction("2026-09-08", "BND", "buy", 2, 50)]
    s.add_plan(Plan("Mix 2", 50, "weekly", {"VT": 50, "BND": 50}, start_date="2026-09-07"))
    tasks = build_tasks(s, prices(), TODAY)
    keys = [t.key for t in tasks]
    assert "review:2026-10" in keys and "routine:week:2026-W41" in keys and "routine:month:2026-10" in keys
    review = next(t for t in tasks if t.kind == "review")
    assert review.detail.count("- VT is 90%") == 1 and "in Mix, Mix 2" in review.detail


def test_new_state_round_trip_and_ids():
    s = state_with(Plan("A", 10, "daily", {"VT": 1}, start_date=TODAY), Plan("A", 10, "daily", {"VT": 1}, start_date=TODAY))
    assert s.plans[0].id != s.plans[1].id
    s.task_log["x"] = {"status": "done", "date": "2026-10-07"}
    back = from_json(to_json(s))
    assert [p.id for p in back.plans] == [p.id for p in s.plans]
    assert back.task_log == s.task_log and back.broker_profile.name == IBKR.name
    assert "AMD=X" in back.all_tickers()


def test_plan_orders_respects_fees():
    plan = Plan("x", 1, "weekly", {"VT": 100})
    orders, left = plan_orders(plan, 100, {}, {"VT": 100.0}, FREEDOM)
    assert orders.empty and left == pytest.approx(100)  # whole shares only: $100 can't cover share + fee
    orders, left = plan_orders(plan, 250, {}, {"VT": 100.0}, FREEDOM)
    assert list(orders["shares"]) == [2]
    assert left == pytest.approx(250 - 200 - 1.2)
