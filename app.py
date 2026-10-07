"""InvestTrack: daily / weekly / monthly investing, with an Action center that tells you what to do now.

Run with:  streamlit run app.py   (or double-click start-windows.bat / start-mac.command)
"""

from __future__ import annotations

import math
from datetime import date, datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from investapp import updater
from investapp.actions import Task, build_tasks, complete_task, done_today, skip_missed, skip_task
from investapp.backtest import backtest_plan, compare_frequencies
from investapp.data import ARMENIA_STARTER, KNOWN_NAMES, fetch_prices, is_market, latest_prices
from investapp.fees import BROKER_PRESETS, GOOD_FEE_SHARE, MAX_FEE_SHARE, NOT_CHOSEN, Broker
from investapp.imports import FIELDS, guess_mapping, merge_trades, parse_trades, read_csv
from investapp.indicators import PERIODS, analyze, market_mood, rsi, sma, summary_table
from investapp.money import TRADING_CURRENCY, fmt, fmt_both, fx_rate, from_usd, to_usd
from investapp.planner import (
    PERIODS_PER_MONTH,
    PERIODS_PER_YEAR,
    PLAN_FREQUENCIES,
    TEMPLATES,
    Plan,
    next_dates,
    project_growth,
    rebalance_trades,
)
from investapp.portfolio import (
    PORTFOLIO_PERIODS,
    Transaction,
    compute_holdings,
    current_values,
    period_performance,
    realized_total,
    value_history,
    value_holdings,
)
from investapp.report import REPORT_KINDS, build_report, history_period
from investapp.storage import AppState, from_json, load_state, save_state, to_json

st.set_page_config(page_title="InvestTrack", page_icon="📈", layout="wide")

# Categorical series colors (fixed order) and status colors readable on light and dark.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
GOOD, BAD = "#0ca30c", "#d03b3b"
DISCLAIMER = (
    "Educational tool, not financial advice. Signals describe the past and do not "
    "predict the future. Every investment can lose money."
)
TASK_ICONS = {"setup": "⚙️", "buy": "🛒", "save": "💰", "extra": "✨", "review": "⚖️", "routine": "📅"}
TRACK_HELP = {
    "daily": "Small amounts every weekday. Brokers charge a minimum fee per purchase, so a daily plan usually "
             "works as **set aside every day, buy when it adds up**. The app does that for you.",
    "weekly": "A fixed amount once a week: a good balance between investing often and keeping fees low.",
    "monthly": "One purchase a month, for example right after payday. The lowest fees and the easiest habit to keep.",
}
HOME_CURRENCIES = ["AMD", "USD", "EUR", "RUB", "GEL"]
OTHER_BROKER = "Other broker (enter fees)"


# ---------------------------------------------------------------- state & data

def get_state() -> AppState:
    if "state" not in st.session_state:
        st.session_state.state = load_state()
    return st.session_state.state


def persist() -> None:
    save_state(get_state())


def transactions_changed() -> None:
    """Save, and reset the trades table editor so it shows the new list."""
    st.session_state.pop("tx_editor", None)
    persist()


def flash(message: str) -> None:
    """Show a short confirmation after the next rerun."""
    st.session_state["flash"] = message


@st.cache_data(ttl=900, show_spinner="Downloading prices...")
def get_prices(tickers: tuple[str, ...], period: str) -> pd.DataFrame:
    return fetch_prices(list(tickers), period)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def check_update() -> bool | None:
    return updater.update_available(timeout=3)


def fmt_num(x: float) -> str:
    return "n/a" if x is None or math.isnan(x) else f"{x:,.2f}"


def fmt_pct(x: float) -> str:
    return "n/a" if x is None or math.isnan(x) else f"{x:+.2%}"


def color_sign(v) -> str:
    if isinstance(v, (int, float)) and not math.isnan(v) and v != 0:
        return f"color: {GOOD if v > 0 else BAD}"
    return ""


# Percent columns are shown as numbers x 100 (see `as_pct`) so decimals stay consistent.
PCT = st.column_config.NumberColumn(format="%+.2f%%")
SHARE = st.column_config.NumberColumn(format="%.1f%%")
MONEY = st.column_config.NumberColumn(format="%,.2f")
SHARES = st.column_config.NumberColumn(format="%.4f")


def as_pct(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    out[cols] = out[cols] * 100
    return out


def line_chart(series: dict[str, pd.Series], title: str, y_title: str = "", height: int = 380) -> go.Figure:
    fig = go.Figure()
    for i, (name, s) in enumerate(series.items()):
        fig.add_trace(go.Scatter(x=s.index, y=s.values, name=name, mode="lines",
                                 line=dict(width=2, color=SERIES[i % len(SERIES)])))
    fig.update_layout(
        title=title, height=height, hovermode="x unified", margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0), yaxis_title=y_title,
        showlegend=len(series) > 1,
    )
    return fig


def signals_for(tickers: list[str]) -> list[tuple[str, str, str]]:
    out = []
    for t in tickers:
        if t in prices.columns and is_market(t) and not prices[t].dropna().empty:
            for s in analyze(prices[t], t).signals:
                if not s.message.startswith(("Uptrend", "Mixed")):
                    out.append((t, s.level, s.message))
    return out


def show_signals(items: list[tuple[str, str, str]]) -> None:
    if not items:
        st.success("Nothing unusual in your plans, holdings or watchlist.")
    icons = {"positive": "🟢", "caution": "🟠", "info": "🔵"}
    for t, level, msg in items:
        st.markdown(f"{icons.get(level, '•')} **{t}**: {msg}")


# ---------------------------------------------------------------- load

state = get_state()
all_tickers = tuple(sorted(set(state.all_tickers()) | set(state.market_overview)))
prices = get_prices(all_tickers, history_period(state))
if prices.empty:
    st.error("Could not download market prices. Check your internet connection and press Refresh.")
    st.stop()
latest = latest_prices(prices)
home = state.home_currency
rate = fx_rate(latest, home)  # home currency per USD
broker = state.broker_profile


def money(usd: float) -> str:
    """A USD amount, with the home-currency equivalent."""
    return fmt_both(usd, home, rate)


def metric_money(col, label: str, usd: float, delta: str | None = None) -> None:
    """A metric shown in the home currency (short enough to fit), with USD underneath."""
    if home != TRADING_CURRENCY and not math.isnan(rate):
        col.metric(label, fmt(from_usd(usd, home, rate), home), delta, border=True)
        col.caption(f"= {fmt(usd, TRADING_CURRENCY)}")
    else:
        col.metric(label, fmt(usd, TRADING_CURRENCY), delta, border=True)


try:
    holdings = compute_holdings(state.transactions)
except ValueError as e:
    st.error(f"Your transactions don't add up: {e}. Fix them in the Portfolio tab.")
    holdings = compute_holdings([])
valued = value_holdings(holdings, latest)
values = current_values(valued)
history = value_history(state.transactions, prices)
today = pd.Timestamp.today().normalize()

if "flash" in st.session_state:
    st.toast(st.session_state.pop("flash"), icon="✅")

# ---------------------------------------------------------------- sidebar

with st.sidebar:
    st.title("📈 InvestTrack")
    st.caption(f"Prices refresh every 15 minutes. Loaded {datetime.now():%Y-%m-%d %H:%M}.")
    if st.button("Refresh prices now", width="stretch"):
        st.cache_data.clear()
        st.rerun()
    if home != TRADING_CURRENCY and not math.isnan(rate):
        st.metric(f"1 USD in {home}", f"{rate:,.2f}")
    if check_update():
        st.info("A new version of InvestTrack is available. Close the app window and start it again to install it.")

    st.divider()
    st.subheader("Backup")
    st.download_button(
        "Download my data (JSON)", to_json(state), file_name=f"investtrack-{date.today()}.json",
        mime="application/json", width="stretch",
    )
    uploaded = st.file_uploader("Restore from a backup", type="json")
    if uploaded is not None and st.button("Replace my data with this backup", width="stretch"):
        try:
            st.session_state.state = from_json(uploaded.getvalue().decode())
            transactions_changed()
            flash("Backup restored.")
            st.rerun()
        except (ValueError, KeyError, TypeError) as e:
            st.error(f"That file could not be read: {e}")
    st.divider()
    st.caption(DISCLAIMER)

(tab_action, tab_dash, tab_plans, tab_port, tab_markets, tab_analyze, tab_bt, tab_reports,
 tab_settings, tab_learn) = st.tabs(
    ["Action", "Dashboard", "Plans", "Portfolio", "Markets", "Analyze", "Backtest", "Reports", "Settings", "Learn"]
)

# ---------------------------------------------------------------- Action

def render_task(task: Task) -> None:
    plan = state.plan_by_id(task.plan_id)
    with st.container(border=True):
        st.markdown(f"#### {TASK_ICONS.get(task.kind, '•')} {task.title}")
        st.markdown(task.detail)
        for w in task.warnings:
            st.warning(w)

        if task.kind in ("buy", "extra") and task.orders is not None:
            whole = (plan.whole_shares if plan else False) or not broker.fractional
            st.markdown("**In your broker app, buy:**")
            for o in task.orders.itertuples():
                qty = f"{o.shares:,.0f}" if whole else f"{o.shares:,.4f}"
                st.markdown(f"- **{qty} {o.ticker}** at about {o.price:,.2f} USD each = {money(o.amount)}")
            st.caption("After buying, change the numbers below to what you actually paid (shares, price, fee), "
                       "then press Done. The app records the purchase in your portfolio.")
            edited = st.data_editor(
                task.orders[["ticker", "shares", "price", "fee"]], key=f"fill_{task.key}", hide_index=True,
                disabled=["ticker"],
                column_config={"shares": st.column_config.NumberColumn(format="%.4f", min_value=0.0),
                               "price": st.column_config.NumberColumn(format="%.2f", min_value=0.0),
                               "fee": st.column_config.NumberColumn(format="%.2f", min_value=0.0)},
            )
            c1, c2, c3 = st.columns([2, 1, 3])
            if c1.button("✅ Done: I bought these", key=f"done_{task.key}", type="primary"):
                note = f"Plan: {plan.name}" if plan else "Action"
                trades = [Transaction(str(today.date()), r.ticker, "buy", r.shares, r.price, r.fee or 0.0, note)
                          for r in edited.itertuples() if r.shares and r.shares > 0 and r.price and r.price > 0]
                complete_task(state, task, trades, today)
                transactions_changed()
                flash(f"Recorded {len(trades)} purchase(s).")
                st.rerun()
            if c2.button("Skip", key=f"skip_{task.key}"):
                skip_task(state, task, today)
                persist()
                st.rerun()
            if task.overdue and plan is not None and c3.button(
                f"Skip the {task.overdue} missed, keep today's", key=f"missed_{task.key}"
            ):
                skip_missed(state, plan, today)
                persist()
                st.rerun()

        elif task.kind == "save":
            c1, c2, c3 = st.columns([2, 1, 3])
            if c1.button("✅ Done: I set it aside", key=f"done_{task.key}", type="primary"):
                complete_task(state, task, today=today)
                persist()
                flash("Saved. The app will tell you when it's time to buy.")
                st.rerun()
            if c2.button("Skip", key=f"skip_{task.key}"):
                skip_task(state, task, today)
                persist()
                st.rerun()
            if task.overdue and plan is not None and c3.button(
                f"Skip the {task.overdue} missed, keep today's", key=f"missed_{task.key}"
            ):
                skip_missed(state, plan, today)
                persist()
                st.rerun()

        elif task.kind in ("review", "routine"):
            if st.button("✅ Done", key=f"done_{task.key}", type="primary"):
                complete_task(state, task, today=today)
                persist()
                st.rerun()
        else:
            st.caption("This disappears by itself once it's done.")


with tab_action:
    tasks = build_tasks(state, prices, today)
    now = [t for t in tasks if t.priority < 2]
    optional = [t for t in tasks if t.priority >= 2]
    st.header(f"Action: what to do now ({today:%A, %B %d})")
    c1, c2, c3 = st.columns(3)
    c1.metric("To do now", len(now), border=True)
    c2.metric("Optional", len(optional), border=True)
    c3.metric("Done today", done_today(state, today), border=True)
    if not tasks:
        st.success("🎉 You're all done for today. Come back tomorrow.")
    for task in now:
        render_task(task)
    if optional:
        st.subheader("Optional")
        for task in optional:
            render_task(task)

    st.subheader("Signals")
    st.caption("Plain-language notes about your plans' funds, your holdings and your watchlist. They explain what "
               "prices did; they are not reasons to abandon your plan.")
    plan_tickers = {t for p in state.plans if p.active for t in p.targets}
    show_signals(signals_for(sorted(plan_tickers | set(values) | set(state.watchlist))))

    upcoming = []
    for p in state.plans:
        if p.active:
            for d in next_dates(p, today + pd.Timedelta(days=1), 6):
                if d <= today + pd.Timedelta(days=7):
                    upcoming.append({"date": d.strftime("%a %b %d"), "plan": p.name, "amount": fmt(p.amount, p.currency),
                                     "_d": d})
    if upcoming:
        st.subheader("Coming up this week")
        st.dataframe(pd.DataFrame(upcoming).sort_values("_d").drop(columns="_d"), hide_index=True)

# ---------------------------------------------------------------- Dashboard

with tab_dash:
    st.header("Dashboard")
    analyses = [analyze(prices[t], t) for t in state.market_overview
                if t in prices.columns and is_market(t) and not prices[t].dropna().empty]
    st.info(market_mood(analyses, latest.get("^VIX")))
    c1, c2, c3 = st.columns(3)
    if not history.empty:
        day = period_performance(history, "1D")
        allt = period_performance(history, "ALL")
        metric_money(c1, "Portfolio value", day["end_value"], fmt_pct(day["gain_pct"]))
        metric_money(c2, "Gain today", day["gain"])
        metric_money(c3, "All-time gain", allt["gain"], fmt_pct(allt["gain_pct"]))
        st.subheader("How you're doing")
        rows = []
        for label, code in PORTFOLIO_PERIODS.items():
            perf = period_performance(history, code)
            row = {"period": label, "gain (USD)": perf["gain"], "return": perf["gain_pct"],
                   "money added (USD)": perf["net_flows"]}
            if home != TRADING_CURRENCY:
                row[f"≈ gain ({home})"] = from_usd(perf["gain"], home, rate)
            rows.append(row)
        perf_df = as_pct(pd.DataFrame(rows), ["return"])
        signed = [c for c in perf_df.columns if c.startswith(("gain", "≈")) or c == "return"]
        st.dataframe(
            perf_df.style.map(color_sign, subset=signed), hide_index=True,
            column_config={"gain (USD)": MONEY, "return": PCT, f"≈ gain ({home})": st.column_config.NumberColumn(format="%,.0f"),
                           "money added (USD)": MONEY},
        )
    else:
        st.write("No investments recorded yet. Your first one will appear in the **Action** tab once you have a plan.")

# ---------------------------------------------------------------- Plans

def plan_fee_line(p: Plan) -> str:
    if not broker.chosen:
        return "Choose your broker in **Settings** to see fees."
    per_buy_usd = max(to_usd(p.amount, p.currency, rate), to_usd(p.buy_threshold, p.currency, rate))
    orders = 1 if p.one_order else len(p.targets)
    fee = sum(broker.order_fee(per_buy_usd / orders, latest.get(t, 100.0)) for t in list(p.targets)[:orders])
    share = fee / per_buy_usd if per_buy_usd else math.nan
    icon = "✅" if share <= GOOD_FEE_SHARE else ("🟠" if share <= MAX_FEE_SHARE else "🔴")
    return f"{icon} Estimated fee per purchase: {fmt(fee, 'USD')} ({share:.1%}) with {broker.name}."


def plan_card(p: Plan) -> None:
    title = f"**{p.name}**: {fmt(p.amount, p.currency)} {p.frequency}" + ("" if p.active else " (paused)")
    with st.expander(title, expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Each time", fmt(p.amount, p.currency))
        c2.metric("Per month", fmt(p.amount * PERIODS_PER_MONTH[p.frequency], p.currency))
        c3.metric("Saved, not yet invested", fmt(p.pot, p.currency))
        nd = next_dates(p, today, 1)[0]
        c4.metric("Next", "Today" if nd == today else f"{nd:%a %b %d}")
        mix = ", ".join(f"{t} {w:.0%}" for t, w in p.targets.items())
        how = (f"Saves until {fmt(p.buy_threshold, p.currency)}, then buys." if p.buy_threshold else "Buys every time.")
        st.markdown(f"**Mix:** {mix}. {how} " + ("One order per purchase. " if p.one_order else "")
                    + (f"Extra +{p.dip_boost:.0%} during dips." if p.dip_boost else ""))
        st.markdown(plan_fee_line(p))
        outside = [t for t in p.targets if state.allowed_tickers and t not in state.allowed_tickers]
        if outside:
            st.warning(f"{', '.join(outside)} is not on your broker list (Settings).")

        with st.form(f"edit_{p.id}"):
            st.markdown("**Change this plan**")
            e1, e2, e3 = st.columns(3)
            amount = e1.number_input(f"Amount each time ({p.currency})", min_value=1.0, value=float(p.amount),
                                     step=100.0 if p.currency == "AMD" else 1.0, key=f"amt_{p.id}")
            threshold = e2.number_input(f"Save, then buy at ({p.currency}; 0 = buy every time)", min_value=0.0,
                                        value=float(p.buy_threshold), step=1000.0 if p.currency == "AMD" else 10.0,
                                        key=f"thr_{p.id}")
            boost_opts = {"Off": 0.0, "+25%": 0.25, "+50%": 0.5, "+100%": 1.0}
            boost = e3.selectbox("Extra during dips (optional)", list(boost_opts), key=f"boost_{p.id}",
                                 index=list(boost_opts.values()).index(p.dip_boost) if p.dip_boost in boost_opts.values() else 0)
            f1, f2 = st.columns(2)
            one = f1.checkbox("One order per purchase (fewer fees)", value=p.one_order, key=f"one_{p.id}")
            whole = f2.checkbox("Whole shares only", value=p.whole_shares, key=f"whole_{p.id}")
            if st.form_submit_button("Save changes"):
                p.amount, p.buy_threshold, p.dip_boost, p.one_order, p.whole_shares = (
                    amount, threshold, boost_opts[boost], one, whole)
                persist()
                flash("Plan updated.")
                st.rerun()

        b1, b2 = st.columns(2)
        if b1.button("Resume" if not p.active else "Pause", key=f"pause_{p.id}"):
            p.active = not p.active
            if p.active:
                skip_missed(state, p, today)  # don't ask to catch up on the paused days
            persist()
            st.rerun()
        if b2.button("Delete plan", key=f"del_{p.id}"):
            state.plans = [x for x in state.plans if x.id != p.id]
            persist()
            st.rerun()

        rb = rebalance_trades(p.targets, {t: values.get(t, 0.0) for t in p.targets})
        if len(p.targets) > 1 and rb["current_value"].sum() > 0:
            fig = go.Figure()
            for j, (label, col) in enumerate([("Now", "current_weight"), ("Target", "target_weight")]):
                fig.add_trace(go.Bar(name=label, y=rb["ticker"], x=rb[col], orientation="h", marker_color=SERIES[j],
                                     hovertemplate="%{y} " + label.lower() + ": %{x:.1%}<extra></extra>"))
            fig.update_layout(barmode="group", height=90 + 56 * len(rb), xaxis=dict(tickformat=".0%"),
                              yaxis=dict(autorange="reversed"), margin=dict(l=10, r=10, t=40, b=10),
                              legend=dict(orientation="h", y=1.15, x=0), bargap=0.45, bargroupgap=0.1,
                              title="Balance: now vs target")
            st.plotly_chart(fig, width="stretch", key=f"rb_{p.id}")


def targets_editor(base: dict[str, float], key: str) -> pd.DataFrame:
    return st.data_editor(
        pd.DataFrame({"ticker": list(base), "weight %": list(base.values())}),
        num_rows="dynamic", hide_index=True, key=key,
        column_config={"weight %": st.column_config.NumberColumn(min_value=0.0, max_value=100.0, step=1.0)},
    )


def targets_from(df: pd.DataFrame) -> dict[str, float]:
    return {str(r["ticker"]).upper(): float(r["weight %"]) for r in df.to_dict("records")
            if r.get("ticker") and r.get("weight %")}


def suggested_threshold(per_buy_usd: float, n_orders: int, currency: str) -> float:
    """Amount (plan currency) to save before buying so fees stay at or under 1%; 0 if not needed."""
    good = broker.min_good_order(MAX_FEE_SHARE) * n_orders
    if not broker.chosen or per_buy_usd >= good or not math.isfinite(good):
        return 0.0
    step = 1000 if currency == "AMD" else 10
    return math.ceil(from_usd(good, currency, rate) / step) * step


def quick_start() -> None:
    st.markdown("Tell the app your monthly budget and it creates three plans, one per track. "
                "You can change everything afterwards.")
    c1, c2 = st.columns(2)
    cur = c1.selectbox("Currency", list(dict.fromkeys([home, "USD"])), key="qs_cur")
    budget = c2.number_input(f"Monthly budget ({cur})", min_value=1.0,
                             value=50_000.0 if cur == "AMD" else 150.0, step=5_000.0 if cur == "AMD" else 10.0,
                             key=f"qs_budget_{cur}")
    s1, s2, s3 = st.columns(3)
    split = {"daily": s1.slider("Daily %", 0, 100, 20, key="qs_d"),
             "weekly": s2.slider("Weekly %", 0, 100, 30, key="qs_w"),
             "monthly": s3.slider("Monthly %", 0, 100, 50, key="qs_m")}
    mix_name = st.selectbox("What to buy (same mix for all three)", list(TEMPLATES), index=1, key="qs_mix")
    targets = TEMPLATES[mix_name]
    total = sum(split.values())
    if total == 0:
        st.error("Give at least one track a share of the budget.")
        return
    step = 100 if cur == "AMD" else 1
    drafts, rows = [], []
    for freq, pct in split.items():
        if pct == 0:
            continue
        each = max(step, round(budget * pct / total / PERIODS_PER_MONTH[freq] / step) * step)
        each_usd = to_usd(each, cur, rate)
        one = len(targets) > 1 and freq in ("daily", "weekly")
        n_orders = 1 if one else len(targets)
        threshold = suggested_threshold(each_usd, n_orders, cur)
        buy_usd = max(each_usd, to_usd(threshold, cur, rate))
        fee = sum(broker.order_fee(buy_usd / n_orders, 100.0) for _ in range(n_orders))
        drafts.append(Plan(f"{freq.capitalize()} plan", each, freq, targets, str(today.date()), currency=cur,
                           one_order=one, buy_threshold=threshold))
        row = {
            "track": freq, f"each time ({cur})": each, "≈ USD": each_usd,
            "how it buys": (f"saves, buys every ~{math.ceil(threshold / each)} contributions" if threshold else "buys every time"),
        }
        if broker.chosen:
            row.update({"fee per purchase (USD)": fee, "fee %": fee / buy_usd * 100})
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), hide_index=True,
                 column_config={f"each time ({cur})": st.column_config.NumberColumn(format="%,.0f"), "≈ USD": MONEY,
                                "fee per purchase (USD)": MONEY, "fee %": st.column_config.NumberColumn(format="%.2f%%")})
    if not broker.chosen:
        st.info("Choose your broker in **Settings** first: then this table shows fees and the app plans around them.")
    if st.button("Create these plans", type="primary", key="qs_create"):
        for d in drafts:
            state.add_plan(d)
        persist()
        flash(f"Created {len(drafts)} plans. Your first tasks are in the Action tab.")
        st.rerun()


with tab_plans:
    st.header("Investing plans")
    st.caption("Each plan invests a fixed amount on a schedule into a mix you choose. New money goes to whatever is "
               "below its target, so you stay balanced without selling. Every due purchase shows up in **Action**.")
    with st.expander("Quick start: set up daily, weekly and monthly plans", expanded=not state.plans):
        quick_start()

    for freq, sub in zip(PLAN_FREQUENCIES, st.tabs([f.capitalize() for f in PLAN_FREQUENCIES])):
        with sub:
            st.markdown(TRACK_HELP[freq])
            mine = [p for p in state.plans if p.frequency == freq]
            if not mine:
                st.write(f"No {freq} plan yet.")
            for p in mine:
                plan_card(p)
            with st.expander(f"Add a {freq} plan"):
                tpl = st.selectbox("Start from a template (examples, not recommendations)", ["Custom"] + list(TEMPLATES),
                                   key=f"tpl_{freq}")
                base = TEMPLATES.get(tpl, {"VT": 100})
                with st.form(f"new_{freq}"):
                    n1, n2, n3 = st.columns(3)
                    name = n1.text_input("Plan name", value=f"{freq.capitalize()}: {tpl}" if tpl != "Custom" else f"My {freq} plan",
                                         key=f"name_{freq}_{tpl}")
                    cur = n2.selectbox("Currency", list(dict.fromkeys([home, "USD"])), key=f"cur_{freq}")
                    amount = n3.number_input("Amount each time", min_value=1.0, value=10_000.0 if home == "AMD" else 25.0,
                                             key=f"amount_{freq}")
                    n4, n5 = st.columns(2)
                    start = n4.date_input("First contribution", date.today(), key=f"start_{freq}")
                    one = n5.checkbox("One order per purchase (fewer fees)", value=freq != "monthly", key=f"one_{freq}")
                    tdf = targets_editor(base, f"targets_{freq}_{tpl}")
                    if st.form_submit_button("Create plan", type="primary"):
                        try:
                            targets = targets_from(tdf)
                            n_orders = 1 if one else max(1, len(targets))
                            threshold = suggested_threshold(to_usd(amount, cur, rate), n_orders, cur)
                            state.add_plan(Plan(name, amount, freq, targets, str(start), currency=cur, one_order=one,
                                                buy_threshold=threshold))
                            persist()
                            flash("Plan created." + (f" It saves until {fmt(threshold, cur)} before buying, to keep fees low."
                                                     if threshold else ""))
                            st.rerun()
                        except (ValueError, TypeError) as e:
                            st.error(str(e))

    others = [p for p in state.plans if p.frequency not in PLAN_FREQUENCIES]
    if others:
        st.subheader("Other plans")
        for p in others:
            plan_card(p)

    st.subheader("What could regular investing grow to?")
    c1, c2, c3 = st.columns(3)
    g_amount = c1.number_input(f"Amount each time ({home})", min_value=1.0, value=20_000.0 if home == "AMD" else 100.0,
                               step=1000.0 if home == "AMD" else 10.0, key="g_amt")
    g_freq = c2.selectbox("How often", PLAN_FREQUENCIES, index=2, key="g_freq")
    g_years = c3.slider("Years", 1, 40, 20)
    proj = {}
    for r in (0.04, 0.07, 0.10):
        df = project_growth(g_amount, g_freq, g_years, r).set_index("year")
        proj[f"{r:.0%} a year"] = df["value"]
    proj["Money you put in"] = df["invested"]
    st.plotly_chart(line_chart(proj, f"{fmt(g_amount, home)} {g_freq} for {g_years} years", home), width="stretch")
    st.caption(
        f"After {g_years} years you'd have put in {fmt(df['invested'].iloc[-1], home)}. Stocks have historically averaged "
        "roughly 7-10% a year in US dollars over long periods, with big swings along the way. The dram's exchange rate "
        "also moves. These smooth lines are illustrations, not forecasts."
    )

# ---------------------------------------------------------------- Portfolio

with tab_port:
    st.header("My portfolio")
    if valued.empty:
        st.write("No holdings yet. Purchases you mark as done in **Action** appear here, or record one below.")
    else:
        total = valued["market_value"].sum()
        cost = valued["cost_basis"].sum()
        c1, c2, c3, c4 = st.columns(4)
        metric_money(c1, "Market value", total)
        metric_money(c2, "Cost basis", cost)
        metric_money(c3, "Unrealized gain", total - cost, fmt_pct((total - cost) / cost if cost else math.nan))
        metric_money(c4, "Realized gain (from sales)", realized_total(state.transactions))
        show = valued.sort_values("market_value", ascending=False)
        cols = ["ticker", "shares", "avg_cost", "price", "market_value", "unrealized_pl", "unrealized_pct", "weight"]
        st.dataframe(
            as_pct(show[cols], ["unrealized_pct", "weight"]).style.map(color_sign, subset=["unrealized_pl", "unrealized_pct"]),
            hide_index=True,
            column_config={"shares": SHARES, "avg_cost": MONEY, "price": MONEY, "market_value": MONEY,
                           "unrealized_pl": MONEY, "unrealized_pct": PCT, "weight": SHARE},
        )
        st.caption("Amounts in USD, the currency your funds trade in.")
        left, right = st.columns([3, 2])
        with left:
            if not history.empty:
                st.plotly_chart(line_chart({"Portfolio value": history["value"], "Money invested": history["invested"]},
                                           "Value vs money invested (USD)"), width="stretch")
        with right:
            fig = go.Figure(go.Bar(
                x=show["weight"], y=show["ticker"], orientation="h", marker_color=SERIES[0],
                text=[f"{w:.1%}" for w in show["weight"]], textposition="outside", width=0.5,
                hovertemplate="%{y}: %{x:.1%}<extra></extra>",
            ))
            fig.update_layout(title="Allocation", height=max(220, 80 + 40 * len(show)), margin=dict(l=10, r=40, t=50, b=10),
                              xaxis=dict(tickformat=".0%", range=[0, float(show["weight"].max()) * 1.25]),
                              yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig, width="stretch")

    with st.expander("Import trades from your broker (CSV file)"):
        st.caption("Most brokers let you export your trade history as a CSV file (Interactive Brokers: Performance & "
                   "Reports → Flex Queries; Freedom Broker / Tradernet: Reports → trades). Upload it here: the app "
                   "matches the columns and skips trades you already have.")
        csv_file = st.file_uploader("CSV file", type=["csv", "txt"], key="csv_upload")
        if csv_file is not None:
            try:
                raw = read_csv(csv_file.getvalue())
            except Exception as e:  # pandas raises many parser error types
                st.error(f"Could not read that file: {e}")
                raw = None
            if raw is not None:
                guess = guess_mapping(raw.columns)
                options = ["(none)"] + [str(c) for c in raw.columns]
                cols = st.columns(len(FIELDS))
                mapping = {}
                for col, f in zip(cols, FIELDS):
                    choice = col.selectbox(f, options, index=options.index(guess[f]) if guess[f] in options else 0,
                                           key=f"map_{f}")
                    mapping[f] = None if choice == "(none)" else choice
                trades, problems = parse_trades(raw, mapping)
                if trades:
                    st.dataframe(pd.DataFrame([t.to_dict() for t in trades]).head(50), hide_index=True)
                for p in problems[:10]:
                    st.caption(f"⚠️ {p}")
                if trades and st.button(f"Import {len(trades)} trades", type="primary"):
                    merged, added, dupes = merge_trades(state.transactions, trades)
                    try:
                        compute_holdings(merged)
                        state.transactions = merged
                        transactions_changed()
                        flash(f"Imported {added} trades ({dupes} were already recorded).")
                        st.rerun()
                    except ValueError as e:
                        st.error(f"Not imported: {e}")

    st.subheader("Record a trade by hand")
    with st.form("add_trade", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        t_ticker = c1.text_input("Ticker", placeholder="VT")
        t_side = c2.selectbox("Buy or sell", ["buy", "sell"])
        t_date = c3.date_input("Date", date.today())
        c4, c5, c6, c7 = st.columns(4)
        t_mode = c4.radio("I know the...", ["USD amount", "number of shares"])
        t_qty = c5.number_input("Amount / shares", min_value=0.0, step=1.0, format="%.4f")
        t_price = c6.number_input("Price per share in USD (0 = latest price)", min_value=0.0, step=0.01, format="%.4f")
        t_fee = c7.number_input("Fee (USD)", min_value=0.0, step=0.01)
        t_note = st.text_input("Note (optional)")
        submitted = st.form_submit_button("Save trade", type="primary")
    if submitted:
        tk = t_ticker.strip().upper()
        price = t_price
        if tk and price == 0:
            px = get_prices((tk,), "5d")
            price = latest_prices(px).get(tk, 0.0) if not px.empty else 0.0
        if not tk or t_qty <= 0:
            st.error("Enter a ticker and a positive amount.")
        elif price <= 0:
            st.error(f"Could not find a price for {tk}. Check the symbol or enter the price yourself.")
        else:
            shares = t_qty / price if t_mode == "USD amount" else t_qty
            try:
                trade = Transaction(str(t_date), tk, t_side, shares, price, t_fee, t_note)
                compute_holdings(state.transactions + [trade])  # rejects selling more than you own
                state.transactions.append(trade)
                transactions_changed()
                flash(f"Saved: {t_side} {shares:.4f} {tk} at {price:,.2f}.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))

    st.subheader("All trades")
    st.caption("Edit cells or select rows and press Delete, then save.")
    tx_df = pd.DataFrame([t.to_dict() for t in state.transactions], columns=list(Transaction.__dataclass_fields__))
    tx_df["date"] = pd.to_datetime(tx_df["date"]).dt.date
    edited_tx = st.data_editor(
        tx_df, num_rows="dynamic", hide_index=True, key="tx_editor",
        column_config={
            "date": st.column_config.DateColumn(required=True),
            "ticker": st.column_config.TextColumn(required=True),
            "side": st.column_config.SelectboxColumn(options=["buy", "sell"], required=True),
            "shares": st.column_config.NumberColumn(format="%.4f", min_value=0.0, required=True),
            "price": st.column_config.NumberColumn(format="%.4f", min_value=0.0, required=True),
            "fee": st.column_config.NumberColumn(format="%.2f", min_value=0.0, default=0.0),
        },
    )
    if st.button("Save changes to trades"):
        try:
            new_txs = [
                Transaction(str(r["date"]), r["ticker"], r["side"], r["shares"], r["price"], r.get("fee") or 0.0,
                            r.get("note") or "")
                for r in edited_tx.to_dict("records") if r.get("ticker")
            ]
            compute_holdings(new_txs)
            state.transactions = new_txs
            transactions_changed()
            flash("Trades saved.")
            st.rerun()
        except (ValueError, TypeError) as e:
            st.error(f"Not saved: {e}")

# ---------------------------------------------------------------- Markets

def market_table(tickers: list[str]) -> None:
    cols = [t for t in tickers if t in prices.columns]
    table = summary_table(prices[cols], KNOWN_NAMES) if cols else pd.DataFrame()
    if table.empty:
        st.write("No data.")
        return
    table = as_pct(table, [*PERIODS, "from_high", "volatility"])
    st.dataframe(
        table.style.map(color_sign, subset=list(PERIODS)), hide_index=True,
        column_config={
            "price": MONEY, **{p: PCT for p in PERIODS},
            "from_high": st.column_config.NumberColumn("from 1y high", format="%.1f%%"),
            "volatility": st.column_config.NumberColumn("volatility (yr)", format="%.0f%%"),
            "rsi": st.column_config.NumberColumn("RSI", format="%.0f"),
        },
    )


with tab_markets:
    st.header("Market overview")
    st.caption("Returns over each period, long-term trend (50/200-day averages), RSI and distance from the 1-year high.")
    market_table(state.market_overview)

    st.subheader("Funds your broker offers")
    st.caption("Your broker list from Settings.")
    market_table(state.allowed_tickers)

    st.subheader("My watchlist")
    wl_text = st.text_input("Tickers (comma separated, Yahoo Finance symbols, e.g. AAPL, VOO, BTC-USD)",
                            ", ".join(state.watchlist))
    new_wl = [t.strip().upper() for t in wl_text.split(",") if t.strip()]
    if new_wl != state.watchlist:
        state.watchlist = new_wl
        persist()
        st.rerun()
    market_table(state.watchlist)

    st.subheader("Compare performance")
    choices = [t for t in prices.columns if is_market(t)]
    default = [t for t in ["VT", "SPY", "VXUS", "BND"] if t in choices] or choices[:3]
    picked = st.multiselect("Tickers (up to 8)", choices, default=default, max_selections=8)
    rng = st.segmented_control("Range", ["1M", "3M", "6M", "YTD", "1Y", "2Y"], default="1Y")
    if picked:
        end = prices.index[-1]
        offsets = {"1M": 1, "3M": 3, "6M": 6, "1Y": 12, "2Y": 24}
        start = (pd.Timestamp(year=end.year, month=1, day=1) if rng == "YTD"
                 else end - pd.DateOffset(months=offsets.get(rng or "1Y", 12)))
        series = {}
        for t in picked:
            s = prices[t].dropna()
            s = s[s.index >= start]
            if not s.empty:
                series[t] = s / s.iloc[0] * 100
        st.plotly_chart(line_chart(series, "Growth of 100 invested at the start of the range", "Value"), width="stretch")

# ---------------------------------------------------------------- Analyze

with tab_analyze:
    st.header("Analyze a ticker")
    c1, c2 = st.columns([2, 1])
    a_ticker = c1.text_input("Ticker", "VT").strip().upper()
    a_range = c2.segmented_control("Show", ["6M", "1Y", "2Y", "5Y"], default="1Y", key="a_range")
    if a_ticker:
        apx = get_prices((a_ticker,), "5y")
        if apx.empty or a_ticker not in apx.columns:
            st.error(f"No data for {a_ticker}. Use Yahoo Finance symbols, e.g. AAPL, VOO, BTC-USD, VWCE.DE.")
        else:
            if state.allowed_tickers and a_ticker not in state.allowed_tickers:
                st.caption(f"ℹ️ {a_ticker} is not on your broker list (Settings).")
            s = apx[a_ticker].dropna()
            a = analyze(s, a_ticker)
            c = st.columns(5)
            c[0].metric("Price (USD)", f"{a.price:,.2f}", fmt_pct(a.returns["1D"]), help="Change vs the previous close")
            c[1].metric("1 year", fmt_pct(a.returns["1Y"]))
            c[2].metric("Trend", a.trend)
            c[3].metric("RSI (14)", f"{a.rsi14:.0f}")
            c[4].metric("From 1y high", fmt_pct(a.from_high))
            show_signals([(a_ticker, x.level, x.message) for x in a.signals])
            months = {"6M": 6, "1Y": 12, "2Y": 24, "5Y": 60}[a_range or "1Y"]
            cut = s.index[-1] - pd.DateOffset(months=months)
            view = {"Price": s, "50-day average": sma(s, 50), "200-day average": sma(s, 200)}
            st.plotly_chart(line_chart({k: v[v.index >= cut] for k, v in view.items()}, f"{a_ticker} price"), width="stretch")
            r = rsi(s)
            fig = line_chart({"RSI": r[r.index >= cut]}, "RSI (14): above 70 = overbought, below 30 = oversold", height=240)
            fig.add_hline(y=70, line_width=1, line_color=BAD)
            fig.add_hline(y=30, line_width=1, line_color=GOOD)
            fig.update_yaxes(range=[0, 100])
            st.plotly_chart(fig, width="stretch")
            with st.expander("What do these numbers mean?"):
                st.markdown(
                    "- **50/200-day average**: the average price over the last 50 or 200 trading days. Price above a "
                    "rising 200-day average is the classic sign of a long-term uptrend.\n"
                    "- **Golden / death cross**: the 50-day average crossing above / below the 200-day.\n"
                    "- **RSI**: how fast price moved recently, 0-100. Above 70 it rose unusually fast; below 30 it fell "
                    "unusually fast.\n"
                    "- **From 1y high**: -10% is called a correction, -20% a bear market.\n"
                    "- **Volatility**: how much the price typically swings in a year. Higher = bumpier ride.\n\n"
                    "None of these predict the future. For long-term investors in diversified funds, a steady plan "
                    "usually matters more than any signal."
                )

# ---------------------------------------------------------------- Backtest

with tab_bt:
    st.header("Backtest: what if I had invested regularly?")
    st.caption("Replays history: buys at the closing price on each scheduled date. Past results don't guarantee future ones.")
    plan_names = [p.name for p in state.plans]
    source = st.radio("Mix to test", ["Custom"] + plan_names, horizontal=True)
    single = False
    if source == "Custom":
        mix_text = st.text_input("Tickers and weights", "VT:100", help="e.g. VTI:60, VXUS:30, BND:10")
        try:
            mix = {k.strip().upper(): float(v) for k, v in (part.split(":") for part in mix_text.split(",") if part.strip())}
        except ValueError:
            st.error("Write it like VTI:60, BND:40")
            mix = {}
        default_amount, default_freq = 100.0, "monthly"
    else:
        plan = state.plans[plan_names.index(source)]
        mix = {t: w * 100 for t, w in plan.targets.items()}
        default_amount = round(to_usd(plan.amount, plan.currency, rate), 2)
        default_freq = plan.frequency if plan.frequency in PLAN_FREQUENCIES else "monthly"
        single = plan.one_order
    c1, c2, c3 = st.columns(3)
    bt_amount = c1.number_input("Amount each time (USD)", min_value=1.0, value=float(default_amount), step=10.0, key="bt_amt")
    bt_freq = c2.selectbox("How often", PLAN_FREQUENCIES, index=PLAN_FREQUENCIES.index(default_freq), key="bt_freq")
    bt_start = c3.date_input("Start investing on", date.today().replace(year=date.today().year - 10), key="bt_start")
    fee_names = [n for n in BROKER_PRESETS if n not in (NOT_CHOSEN, OTHER_BROKER)]
    fee_options = ["No fees"] + ([broker.name] if broker.chosen and broker.name not in fee_names else []) + fee_names
    fee_choice = st.selectbox("Include fees of", fee_options,
                              index=fee_options.index(broker.name) if broker.chosen else 0)
    bt_broker = None if fee_choice == "No fees" else (broker if fee_choice == broker.name else BROKER_PRESETS[fee_choice])
    if mix and st.button("Run backtest", type="primary"):
        bpx = get_prices(tuple(sorted(mix)), "max")
        try:
            res = backtest_plan(bpx, mix, bt_amount, bt_freq, bt_start, broker=bt_broker, single_order=single)
            c = st.columns(5)
            c[0].metric("Money put in (USD)", fmt_num(res.total_invested))
            c[1].metric("Would be worth (USD)", fmt_num(res.final_value), fmt_pct(res.total_return))
            c[2].metric("Profit (USD)", fmt_num(res.profit))
            c[3].metric("Fees paid (USD)", fmt_num(res.fees))
            c[4].metric("Yearly return", fmt_pct(res.annualized), help="Money-weighted, in USD")
            first = res.history.index[0]
            if first.date() > bt_start:
                st.caption(f"Price history for this mix starts {first:%Y-%m-%d}, so the test starts there.")
            st.plotly_chart(line_chart({"Value": res.history["value"], "Money put in": res.history["invested"]},
                                       "Backtest (USD)"), width="stretch")
            st.markdown("**Daily vs weekly vs monthly:** the same yearly budget on each schedule"
                        + (f", including {bt_broker.name} fees" if bt_broker else "") + ":")
            cmp = compare_frequencies(bpx, mix, bt_amount * PERIODS_PER_YEAR[bt_freq], bt_start, broker=bt_broker,
                                      single_order=single)
            st.dataframe(
                as_pct(cmp, ["total_return", "annualized"]).style.map(color_sign, subset=["profit", "total_return", "annualized"]),
                hide_index=True,
                column_config={"invested": MONEY, "final_value": MONEY, "profit": MONEY, "total_return": PCT,
                               "annualized": PCT, "fees": MONEY},
            )
            st.caption("Without fees the schedule barely matters. With a minimum fee per order, frequent small purchases "
                       "cost much more, which is why daily plans save first and buy later.")
        except ValueError as e:
            st.error(str(e))

# ---------------------------------------------------------------- Reports

with tab_reports:
    st.header("Reports")
    kind = st.segmented_control("Report", list(REPORT_KINDS), default="daily", key="report_kind") or "daily"
    try:
        text = build_report(kind, state, prices)
        st.download_button("Download report (Markdown)", text, file_name=f"{date.today()}-{kind}.md")
        st.markdown(text)
    except ValueError as e:
        st.error(str(e))

# ---------------------------------------------------------------- Settings

with tab_settings:
    st.header("Settings")

    st.subheader("Where you invest from")
    c1, c2 = st.columns(2)
    countries = ["Armenia", "Other"]
    country = c1.selectbox("Country", countries, index=countries.index(state.country) if state.country in countries else 1)
    home_choice = c2.selectbox("Show amounts also in", HOME_CURRENCIES,
                               index=HOME_CURRENCIES.index(home) if home in HOME_CURRENCIES else 0)
    if country != state.country or home_choice != home:
        state.country, state.home_currency = country, home_choice
        persist()
        st.rerun()
    if home != TRADING_CURRENCY:
        st.caption(f"Today 1 USD = {rate:,.2f} {home}. Funds trade in US dollars, so the dram value of your "
                   "investments also moves with the exchange rate.")

    st.subheader("Your broker")
    names = list(BROKER_PRESETS)
    current = broker.name if broker.name in names else OTHER_BROKER
    choice = st.selectbox("Broker you use (or plan to use)", names, index=names.index(current))
    if choice != current:
        state.broker = BROKER_PRESETS[choice].to_dict()
        persist()
        st.rerun()
    if broker.note:
        st.caption(broker.note)
    if broker.chosen:
        with st.form("broker_fees"):
            st.markdown("**Fees per order (USD)**: adjust if your broker's prices differ")
            f1, f2, f3, f4 = st.columns(4)
            per_share = f1.number_input("Per share", min_value=0.0, value=float(broker.per_share), format="%.4f")
            pct = f2.number_input("Percent of order", min_value=0.0, value=float(broker.pct * 100), format="%.3f")
            min_fee = f3.number_input("Minimum per order", min_value=0.0, value=float(broker.min_fee), format="%.2f")
            max_pct = f4.number_input("Maximum, % of order (0 = none)", min_value=0.0, value=float(broker.max_pct * 100),
                                      format="%.2f")
            fractional = st.checkbox("My broker sells fractional shares (e.g. 0.25 of a share)", value=broker.fractional)
            if st.form_submit_button("Save fees"):
                state.broker = Broker(broker.name, per_share, pct / 100, min_fee, max_pct / 100, fractional,
                                      broker.note).to_dict()
                persist()
                flash("Broker fees saved.")
                st.rerun()
        good = broker.min_good_order()
        examples = [{"purchase (USD)": a, "fee (USD)": broker.order_fee(a, 100.0), "fee %": broker.fee_share(a) * 100}
                    for a in (10, 25, 50, 100, 250, 500, 1000)]
        st.dataframe(pd.DataFrame(examples), hide_index=True,
                     column_config={"fee (USD)": MONEY, "fee %": st.column_config.NumberColumn(format="%.2f%%")})
        if math.isfinite(good):
            st.caption(f"Purchases of at least {money(good)} keep the fee at or under 0.5%.")

    with st.expander("Compare brokers available in Armenia", expanded=not broker.chosen):
        rows = []
        for n, b in BROKER_PRESETS.items():
            if n in (NOT_CHOSEN, OTHER_BROKER):
                continue
            rows.append({"broker": n, "fee on $25": b.order_fee(25, 100), "fee on $100": b.order_fee(100, 100),
                         "fee on $500": b.order_fee(500, 100), "fractional shares": "yes" if b.fractional else "check",
                         "fee ≤0.5% from": b.min_good_order()})
        st.dataframe(pd.DataFrame(rows), hide_index=True,
                     column_config={c: MONEY for c in ("fee on $25", "fee on $100", "fee on $500", "fee ≤0.5% from")})
        st.caption("Published fees as found in 2026. Brokers change prices: confirm on their websites before opening an "
                   "account. Banks such as Ameriabank and Unibank and companies like Apricot Capital also offer access to "
                   "international markets; ask them for their fee per US-stock order and choose 'Other broker'. Avoid "
                   "platforms that sell CFDs instead of real shares.")

    st.subheader("Funds you can buy")
    st.caption("The app warns you when a plan uses something not on this list. Check it against what your broker offers.")
    allowed_text = st.text_area("Tickers (comma or new line separated)", ", ".join(state.allowed_tickers), height=80)
    a1, a2 = st.columns(2)
    if a1.button("Save list"):
        state.allowed_tickers = sorted({t.strip().upper() for t in allowed_text.replace("\n", ",").split(",") if t.strip()})
        persist()
        flash("Broker list saved.")
        st.rerun()
    if a2.button("Reset to the Armenia starter list"):
        state.allowed_tickers = list(ARMENIA_STARTER)
        persist()
        st.rerun()
    st.dataframe(pd.DataFrame([{"ticker": t, "what it is": KNOWN_NAMES.get(t, "")} for t in state.allowed_tickers]),
                 hide_index=True)

    st.subheader("App version")
    version = updater.local_version()
    status = check_update()
    st.write(f"Installed version: `{version[:7] if version else 'development copy'}`")
    if status is True:
        st.info("A new version is available. Close the app window and start it again: it updates itself.")
    elif status is False:
        st.success("You have the latest version.")
    else:
        st.caption("Updates install automatically each time you start the app with start-windows.bat or start-mac.command.")

# ---------------------------------------------------------------- Learn

with tab_learn:
    st.header("Getting started with investing")
    st.markdown(
        """
**1. Build a safety net first.** Keep 3-6 months of expenses in savings and pay off high-interest debt
before investing. Only invest money you won't need for at least 5 years.

**2. Diversify with low-cost index funds.** A fund like VT (whole world) or VOO (S&P 500) holds hundreds or
thousands of companies, so one bad company can't sink you. Look for yearly fees (expense ratio) under 0.2%.

**3. Invest on a schedule.** A fixed amount every week or month means you buy more shares when prices are low
and fewer when high, and you never have to guess the "right" day.

**4. Mind the fees.** With a minimum fee per order, many tiny purchases cost a lot. Check the fee table in
**Settings**; the app's "save, then buy" option keeps daily plans cheap.

**5. Choose a mix you can stick with.** More stocks = higher long-term growth but deeper drops (-30% to -50%
happens). More bonds = smoother ride, lower growth.

**6. Don't react to every headline.** Daily moves are mostly noise. Use the daily view to stay on plan,
not to trade more.

---

**Investing from Armenia**
- Ways to reach US and international markets include Interactive Brokers (directly, or through Acba bank's
  app), Freedom Broker Armenia, and the brokerage services of banks such as Ameriabank and Unibank. Compare
  their fees in **Settings**, and check that a firm is licensed by the Central Bank of Armenia (or, for a
  foreign broker, by its home regulator).
- Buy real shares and ETFs, not CFDs: CFDs are bets on price moves and most retail CFD accounts lose money.
- You'll convert drams to US dollars. Ask your bank or broker what the conversion and transfer cost.
- Taxes: rules for residents' foreign dividends and gains are not clear-cut. Ask an Armenian tax adviser
  before you start, and keep your yearly broker statements.

**Your routine with this app**
- *Every day*: open **Action** and do what it lists (buy, or set money aside), then press Done.
- *Every week*: the weekly check-in task: read the weekly report.
- *Every month*: the monthly check-in: review the month, back up your data, and look at the balance check.

Tickers use Yahoo Finance symbols: US funds like `VT`, `VOO`, European listings with a suffix like `VWCE.DE`.
"""
    )
    st.caption(DISCLAIMER)
