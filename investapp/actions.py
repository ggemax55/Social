"""The Action center: concrete things to do right now.

Tasks come from your plans (buy or set money aside), market conditions (optional
extra purchases during dips), and routines (weekly and monthly check-ins). Each
task is marked done or skipped in `AppState.task_log` so it does not come back.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from .data import latest_prices
from .fees import MAX_FEE_SHARE, Broker
from .indicators import drawdown_from_high
from .money import TRADING_CURRENCY, fmt, from_usd, fx_rate, to_usd
from .planner import Plan, allocate_contribution, rebalance_trades, schedule
from .portfolio import Transaction, compute_holdings, current_values, value_holdings
from .storage import AppState

LOOKBACK_DAYS = 31  # missed contributions older than this are dropped
DIP_LEVEL = -0.10  # "in a dip" = 10%+ below the 1-year high


@dataclass
class Task:
    key: str
    kind: str  # setup | buy | save | extra | review | routine
    title: str
    detail: str
    priority: int = 1  # 0 = do now, 1 = today, 2 = optional
    plan_id: str = ""
    log_keys: list[str] = field(default_factory=list)
    new_money: float = 0.0  # contributions included, in the plan's currency
    total_usd: float = 0.0  # money available for this purchase, in USD
    rate: float = 1.0  # plan currency per USD when the task was built
    orders: pd.DataFrame | None = None  # ticker, shares, price, amount, fee
    leftover_usd: float = 0.0
    warnings: list[str] = field(default_factory=list)
    overdue: int = 0  # missed contributions from earlier days included in this task


def contribution_key(plan: Plan, day) -> str:
    return f"{plan.id}:{pd.Timestamp(day).date()}"


def pending_dates(plan: Plan, log: dict, today, lookback_days: int = LOOKBACK_DAYS) -> list[pd.Timestamp]:
    """Scheduled contributions up to today that are neither done nor skipped."""
    today = pd.Timestamp(today).normalize()
    if not plan.active:
        return []
    start = max(pd.Timestamp(plan.start_date), today - pd.Timedelta(days=lookback_days))
    if start > today:
        return []
    dates = schedule(plan.frequency, plan.start_date, today, from_date=start)
    return [d for d in dates if contribution_key(plan, d) not in log]


def plan_orders(
    plan: Plan, amount_usd: float, values: dict[str, float], latest: dict[str, float], broker: Broker
) -> tuple[pd.DataFrame, float]:
    """Orders for `amount_usd`, leaving room for the broker's fees. Returns (orders, leftover_usd)."""
    whole = plan.whole_shares or not broker.fractional
    current = {t: values.get(t, 0.0) for t in plan.targets}

    def build(amount: float) -> tuple[pd.DataFrame, float]:
        orders, left = allocate_contribution(amount, plan.targets, current, latest, whole, plan.one_order)
        orders = orders[(orders["shares"] > 0) & orders["price"].notna()].copy()
        orders["amount"] = orders["shares"] * orders["price"]
        orders["fee"] = [broker.order_fee(a, p) for a, p in zip(orders["amount"], orders["price"])]
        return orders, left

    orders, _ = build(amount_usd)
    if orders["fee"].sum() > 0:
        orders, _ = build(max(amount_usd - orders["fee"].sum(), 0.0))
    leftover = amount_usd - float(orders["amount"].sum() + orders["fee"].sum())
    cols = ["ticker", "shares", "price", "amount", "fee"]
    return orders[cols].reset_index(drop=True), max(leftover, 0.0)


def _describe_dates(dates: list[pd.Timestamp], today: pd.Timestamp) -> str:
    if len(dates) == 1:
        return "Today's contribution" if dates[0] == today else f"Contribution from {dates[0]:%a %b %d}"
    missed = sum(d < today for d in dates)
    text = f"{len(dates)} contributions ({dates[0]:%b %d} to {dates[-1]:%b %d})"
    return text + (f", {missed} of them missed earlier" if missed else "")


def _plan_tasks(
    plan: Plan, state: AppState, prices: pd.DataFrame, latest: dict, values: dict, broker: Broker, today: pd.Timestamp
) -> list[Task]:
    dates = pending_dates(plan, state.task_log, today)
    if not dates:
        return []
    rate = fx_rate(latest, plan.currency)
    keys = [contribution_key(plan, d) for d in dates]
    if math.isnan(rate):
        return [Task(f"{plan.id}:norate", "setup", f"Exchange rate missing for {plan.currency}",
                     f"Could not get today's {plan.currency} rate, so the app can't size the purchase for "
                     f"“{plan.name}”. Press **Refresh prices** in the sidebar.", 0, plan.id)]

    new_money = len(dates) * plan.amount
    total = plan.pot + new_money
    total_usd = to_usd(total, plan.currency, rate)
    threshold_usd = to_usd(plan.buy_threshold, plan.currency, rate)
    when = _describe_dates(dates, today)
    overdue = sum(d < today for d in dates)
    approx = f" (about {fmt(total_usd, TRADING_CURRENCY)})" if plan.currency != TRADING_CURRENCY else ""
    saved = f" plus {fmt(plan.pot, plan.currency)} saved earlier" if plan.pot > 0 else ""

    orders, leftover = (None, 0.0)
    if total_usd + 1e-9 >= threshold_usd:
        orders, leftover = plan_orders(plan, total_usd, values, latest, broker)

    if orders is None or orders.empty:
        reason = (
            f"You'll buy once it reaches {fmt(plan.buy_threshold, plan.currency)}, so fees stay small."
            if orders is None
            else "It's not enough for one whole share yet, so keep saving."
        )
        return [Task(
            f"{plan.id}:save:{dates[-1].date()}", "save",
            f"Set aside {fmt(new_money, plan.currency)} for “{plan.name}”",
            f"{when}. Move the money to your broker account (or a separate savings account). "
            f"Saved so far: {fmt(plan.pot, plan.currency)}. {reason}",
            0, plan.id, keys, new_money, total_usd, rate, overdue=overdue,
        )]

    fees = float(orders["fee"].sum())
    lines = [f"{when}: {fmt(new_money, plan.currency)}{saved}."]
    if broker.chosen:
        lines.append(f"Estimated broker fees: {fmt(fees, TRADING_CURRENCY)} ({fees / total_usd:.1%} of this purchase).")
    if leftover > 0.01:
        lines.append(f"{fmt(leftover, TRADING_CURRENCY)} stays as cash and is added to your next purchase.")
    warnings = []
    not_allowed = [t for t in orders["ticker"] if state.allowed_tickers and t not in state.allowed_tickers]
    if not_allowed:
        warnings.append(f"{', '.join(not_allowed)} is not on your broker's list (Settings). Check your broker offers it.")
    if broker.chosen and fees / total_usd > MAX_FEE_SHARE:
        good = broker.min_good_order()
        tip = f" Fees stay under 0.5% from about {fmt(good, TRADING_CURRENCY)} per purchase." if math.isfinite(good) else ""
        warnings.append(f"Fees take {fees / total_usd:.1%} of this purchase. In the plan's settings, use "
                        f"“save, then buy” or a single order per purchase.{tip}")
    task = Task(
        f"{plan.id}:buy:{dates[-1].date()}", "buy",
        f"Buy for “{plan.name}”: {fmt(total, plan.currency)}{approx}",
        " ".join(lines), 0, plan.id, keys, new_money, total_usd, rate, orders, leftover, warnings, overdue,
    )
    tasks = [task]

    if plan.dip_boost > 0:
        iso = today.isocalendar()
        key = f"{plan.id}:extra:{iso.year}-W{iso.week:02d}"
        dips = {t: drawdown_from_high(prices[t]) for t in plan.targets if t in prices.columns}
        dips = {t: d for t, d in dips.items() if not math.isnan(d) and d <= DIP_LEVEL}
        if dips and key not in state.task_log:
            t = min(dips, key=dips.get)
            extra = plan.amount * plan.dip_boost
            extra_usd = to_usd(extra, plan.currency, rate)
            dip_plan = Plan(plan.name, extra, plan.frequency, {t: 1}, plan.start_date, plan.whole_shares)
            extra_orders, extra_left = plan_orders(dip_plan, extra_usd, {}, latest, broker)
            if not extra_orders.empty:
                tasks.append(Task(
                    key, "extra", f"Optional: extra {fmt(extra, plan.currency)} into {t}",
                    f"{t} is {dips[t]:.0%} below its 1-year high. Your plan allows a little extra during dips. "
                    "Only use money you won't need soon: prices can keep falling before they recover.",
                    2, plan.id, [key], 0.0, extra_usd, rate, extra_orders, extra_left,
                ))
    return tasks


def build_tasks(state: AppState, prices: pd.DataFrame, today=None) -> list[Task]:
    """Everything to do now, most urgent first."""
    today = pd.Timestamp(today or pd.Timestamp.today()).normalize()
    latest = latest_prices(prices)
    broker = state.broker_profile
    try:
        values = current_values(value_holdings(compute_holdings(state.transactions), latest))
    except ValueError:
        values = {}

    tasks: list[Task] = []
    if not broker.chosen:
        tasks.append(Task("setup:broker", "setup", "Choose your broker",
                          "Open **Settings** and pick the broker you use or plan to use. The app then sizes "
                          "every purchase around its fees and whether it sells fractional shares.", 1))
    if not state.plans:
        tasks.append(Task("setup:plans", "setup", "Create your daily, weekly and monthly plans",
                          "Open **Plans** and use **Quick start** to split a monthly budget into the three tracks.", 1))

    for plan in state.plans:
        if plan.active:
            tasks += _plan_tasks(plan, state, prices, latest, values, broker, today)

    month_key = f"review:{today:%Y-%m}"
    if values and month_key not in state.task_log:
        drifted: dict[tuple, list[str]] = {}  # (ticker, now, target) -> plan names; plans can share funds
        for plan in state.plans:
            if not plan.active:
                continue
            rb = rebalance_trades(plan.targets, {t: values.get(t, 0.0) for t in plan.targets})
            if rb["current_value"].sum() > 0:
                for r in rb[rb["needs_rebalance"]].itertuples():
                    key = (r.ticker, round(r.current_weight, 2), round(r.target_weight, 2))
                    drifted.setdefault(key, []).append(plan.name)
        lines = [f"- {t} is {now:.0%} (target {target:.0%}) in {', '.join(names)}"
                 for (t, now, target), names in drifted.items()]
        if lines:
            tasks.append(Task(month_key, "review", "Monthly balance check",
                              "These drifted 5+ points from their targets:\n" + "\n".join(lines) +
                              "\n\nNo need to sell: new contributions automatically go to what is below target.",
                              2, log_keys=[month_key]))

    if state.plans:
        iso = today.isocalendar()
        week_key = f"routine:week:{iso.year}-W{iso.week:02d}"
        if week_key not in state.task_log:
            tasks.append(Task(week_key, "routine", "Weekly check-in",
                              "Read this week's report (**Reports** tab, weekly) and look at the signals below. "
                              "Don't change your plan because of one week's news.", 2, log_keys=[week_key]))
        routine_month = f"routine:month:{today:%Y-%m}"
        if routine_month not in state.task_log:
            tasks.append(Task(routine_month, "routine", "Monthly check-in",
                              "Read the monthly report, check your deposits to the broker match your plans, and "
                              "press **Download my data** in the sidebar to keep a backup.", 2,
                              log_keys=[routine_month]))
    return sorted(tasks, key=lambda t: t.priority)


def _mark(state: AppState, keys: list[str], status: str, today) -> None:
    day = str(pd.Timestamp(today or pd.Timestamp.today()).date())
    for k in keys:
        state.task_log[k] = {"status": status, "date": day}


def complete_task(state: AppState, task: Task, trades: list[Transaction] | None = None, today=None) -> None:
    """Record a task as done. For purchases, `trades` are what you actually bought."""
    plan = state.plan_by_id(task.plan_id)
    if task.kind in ("buy", "extra"):
        trades = trades or []
        state.transactions.extend(trades)
        if task.kind == "buy" and plan is not None:
            spent = sum(t.shares * t.price + t.fee for t in trades)
            plan.pot = round(from_usd(max(task.total_usd - spent, 0.0), plan.currency, task.rate), 2)
    elif task.kind == "save" and plan is not None:
        plan.pot = round(plan.pot + task.new_money, 2)
    _mark(state, task.log_keys, "done", today)


def skip_task(state: AppState, task: Task, today=None) -> None:
    _mark(state, task.log_keys, "skipped", today)


def skip_missed(state: AppState, plan: Plan, today=None) -> int:
    """Skip contributions from earlier days (e.g. after a pause); returns how many."""
    today = pd.Timestamp(today or pd.Timestamp.today()).normalize()
    missed = [contribution_key(plan, d) for d in pending_dates(plan, state.task_log, today) if d < today]
    _mark(state, missed, "skipped", today)
    return len(missed)


def done_today(state: AppState, today=None) -> int:
    day = str(pd.Timestamp(today or pd.Timestamp.today()).date())
    return sum(1 for v in state.task_log.values() if v.get("date") == day and v.get("status") == "done")
