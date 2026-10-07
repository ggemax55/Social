"""Daily / weekly / monthly / yearly investment reports (Markdown).

Run from the project folder:

    python -m investapp.report daily
    python -m investapp.report weekly --save
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import pandas as pd

from .data import KNOWN_NAMES, fetch_prices, latest_prices
from .data import is_market
from .indicators import analyze, market_mood
from .money import fmt, fmt_both, fx_rate, to_usd
from .planner import Plan, allocate_contribution, rebalance_trades, schedule
from .portfolio import compute_holdings, current_values, period_performance, value_history, value_holdings
from .storage import AppState, load_state

REPORT_KINDS = {"daily": "1D", "weekly": "1W", "monthly": "1M", "yearly": "1Y"}
_WINDOW = {
    "daily": pd.DateOffset(days=0),
    "weekly": pd.DateOffset(days=6),
    "monthly": pd.DateOffset(months=1, days=-1),
    "yearly": pd.DateOffset(years=1, days=-1),
}
_PERIOD_WORD = {"daily": "today", "weekly": "this week", "monthly": "this month", "yearly": "this year"}

DISCLAIMER = (
    "_Educational tool, not financial advice. Past performance does not predict future "
    "results; every investment can lose money._"
)


def pct(x: float) -> str:
    return "n/a" if x is None or math.isnan(x) else f"{x:+.2%}"


def money(x: float, currency: str = "USD") -> str:
    if x is None or math.isnan(x):
        return "n/a"
    sign = "-" if x < 0 else ""
    return f"{sign}{abs(x):,.2f} {currency}"


def history_period(state: AppState) -> str:
    """How much price history to download so all trades and 200-day averages are covered."""
    if not state.transactions:
        return "2y"
    first = pd.Timestamp(min(t.date for t in state.transactions))
    years = (pd.Timestamp.today() - first).days / 365 + 1
    for label, limit in (("2y", 2), ("5y", 5), ("10y", 10)):
        if years <= limit:
            return label
    return "max"


def plan_window(plan: Plan, kind: str, today: pd.Timestamp) -> list[pd.Timestamp]:
    return schedule(plan.frequency, plan.start_date, today + _WINDOW[kind], from_date=today)


def plan_buy_list(plan: Plan, holdings_values: dict[str, float], prices: dict[str, float]) -> tuple[pd.DataFrame, float]:
    """What one contribution (converted to USD) should buy, steering toward the plan's targets."""
    return allocate_contribution(
        to_usd(plan.amount, plan.currency, fx_rate(prices, plan.currency)),
        plan.targets,
        {t: holdings_values.get(t, 0.0) for t in plan.targets},
        prices,
        whole_shares=plan.whole_shares,
        single_order=plan.one_order,
    )


def build_report(kind: str, state: AppState, prices: pd.DataFrame, today=None) -> str:
    if kind not in REPORT_KINDS:
        raise ValueError(f"kind must be one of {list(REPORT_KINDS)}")
    period = REPORT_KINDS[kind]
    today = pd.Timestamp(today or pd.Timestamp.today()).normalize()
    cur = state.currency
    latest = latest_prices(prices)
    lines = [f"# {kind.capitalize()} investment report: {today.date()}", ""]

    # Markets
    lines += ["## Markets", "", "| Market | Price | Change | Trend | RSI |", "|---|---:|---:|---|---:|"]
    analyses = []
    for t in state.market_overview:
        if t not in prices.columns or prices[t].dropna().empty:
            continue
        a = analyze(prices[t], t)
        if is_market(t):
            analyses.append(a)
        name = KNOWN_NAMES.get(t, t)
        lines.append(f"| {name} ({t}) | {a.price:,.2f} | {pct(a.returns[period])} | {a.trend} | {a.rsi14:.0f} |")
    vix = latest.get("^VIX")
    lines += ["", market_mood(analyses, vix), ""]

    # Portfolio
    rate = fx_rate(latest, state.home_currency)
    lines += ["## Your portfolio", ""]
    valued = pd.DataFrame()
    if state.transactions:
        holdings = compute_holdings(state.transactions)
        valued = value_holdings(holdings, latest)
        hist = value_history(state.transactions, prices)
        perf = period_performance(hist, period)
        all_time = period_performance(hist, "ALL")
        lines += [
            f"- Value: **{fmt_both(perf['end_value'], state.home_currency, rate)}**",
            f"- Gain {_PERIOD_WORD[kind]}: {money(perf['gain'], cur)} ({pct(perf['gain_pct'])})"
            + (f", plus {money(perf['net_flows'], cur)} you added" if perf["net_flows"] > 0.005 else ""),
            f"- All-time gain: {money(all_time['gain'], cur)} ({pct(all_time['gain_pct'])}) on {money(all_time['net_flows'], cur)} invested",
            "",
        ]
        if not valued.empty:
            lines += ["| Holding | Shares | Value | Weight | Change | Unrealized P/L |", "|---|---:|---:|---:|---:|---:|"]
            for r in valued.sort_values("market_value", ascending=False).itertuples():
                chg = analyze(prices[r.ticker], r.ticker).returns[period] if r.ticker in prices else math.nan
                lines.append(
                    f"| {r.ticker} | {r.shares:,.4f} | {money(r.market_value, cur)} | {r.weight:.1%} "
                    f"| {pct(chg)} | {money(r.unrealized_pl, cur)} ({pct(r.unrealized_pct)}) |"
                )
            lines.append("")
    else:
        lines += ["No transactions recorded yet. Add your first buy in the app's Portfolio tab.", ""]

    # Plans
    values = current_values(valued)
    active = [p for p in state.plans if p.active]
    lines += ["## Investing plans", ""]
    if not active:
        lines += ["No active plans. Create one in the app's Plans tab.", ""]
    for p in active:
        due = plan_window(p, kind, today)
        lines.append(f"### {p.name}: {fmt(p.amount, p.currency)} {p.frequency}")
        if due:
            lines.append(
                f"{len(due)} contribution(s) due {_PERIOD_WORD[kind]}, "
                f"{fmt(len(due) * p.amount, p.currency)} in total. Next: {due[0].date()}."
            )
        else:
            nxt = schedule(p.frequency, p.start_date, today + pd.DateOffset(years=2), from_date=today)
            lines.append(f"Nothing due {_PERIOD_WORD[kind]}. Next: {nxt[0].date() if nxt else 'n/a'}.")
        orders, leftover = plan_buy_list(p, values, latest)
        lines += ["", "Next contribution buys:", "", "| Ticker | Target | Amount | Price | Shares |", "|---|---:|---:|---:|---:|"]
        for o in orders.itertuples():
            lines.append(f"| {o.ticker} | {o.target_weight:.0%} | {money(o.amount, cur)} | {o.price:,.2f} | {o.shares:,.4f} |")
        if leftover > 0.005:
            lines.append(f"\nLeft over (not enough for a whole share): {money(leftover, cur)}")
        if kind == "yearly" and values:
            rb = rebalance_trades(p.targets, {t: values.get(t, 0.0) for t in p.targets})
            flagged = rb[rb["needs_rebalance"]]
            if flagged.empty:
                lines.append("\nYearly check-up: weights are within 5 points of target; no rebalancing needed.")
            else:
                lines.append("\nYearly check-up: these drifted 5+ points from target:")
                for r in flagged.itertuples():
                    action = "buy" if r.trade_value > 0 else "sell"
                    lines.append(
                        f"- {r.ticker}: {r.current_weight:.0%} vs target {r.target_weight:.0%}; "
                        f"{action} about {money(abs(r.trade_value), cur)}"
                    )
        lines.append("")

    # Signals
    watch = sorted(set(state.watchlist) | set(values))
    notes = []
    for t in watch:
        if t not in prices.columns or prices[t].dropna().empty:
            continue
        for s in analyze(prices[t], t).signals:
            if not s.message.startswith(("Uptrend", "Mixed")):
                notes.append(f"- **{t}**: {s.message}")
    lines += ["## Things to notice", ""] + (notes or ["- Nothing unusual in your watchlist."]) + ["", DISCLAIMER, ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Print an investment report.")
    parser.add_argument("kind", choices=list(REPORT_KINDS), help="report period")
    parser.add_argument("--data", help="path to your portfolio JSON file")
    parser.add_argument("--save", action="store_true", help="also save to reports/<date>-<kind>.md")
    args = parser.parse_args(argv)

    state = load_state(args.data)
    prices = fetch_prices(sorted(set(state.all_tickers()) | set(state.market_overview)), history_period(state))
    if prices.empty:
        raise SystemExit("Could not download any prices. Check your internet connection.")
    text = build_report(args.kind, state, prices)
    print(text)
    if args.save:
        out = Path("reports") / f"{pd.Timestamp.today().date()}-{args.kind}.md"
        out.parent.mkdir(exist_ok=True)
        out.write_text(text)
        print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()
