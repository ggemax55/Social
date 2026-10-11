"""InvestTrack: three sections of money (short term, monthly income, long term), with an Action
center that tells you what to do now, reminders, and sync between your PC and iPhone.

Run with:  streamlit run app.py   (or double-click start-windows.bat / start-mac.command)
"""

from __future__ import annotations

import hmac
import math
import os
import time
from datetime import date, datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from investapp import notify, updater
from investapp.actions import Task, build_tasks, complete_task, done_today, skip_missed, skip_task
from investapp.backtest import backtest_plan, compare_frequencies
from investapp.buckets import BUCKET_KEYS, BUCKETS, normalize_split
from investapp.buckets import label as bucket_label
from investapp.data import ARMENIA_STARTER, KNOWN_NAMES, fetch_prices, is_market, latest_prices
from investapp.fees import BROKER_PRESETS, GOOD_FEE_SHARE, MAX_FEE_SHARE, NOT_CHOSEN, Broker
from investapp.ics import plans_calendar
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
    holdings_by_bucket,
    period_performance,
    realized_total,
    value_history,
    value_holdings,
)
from investapp.report import REPORT_KINDS, build_report, history_period
from investapp.storage import ConflictError, from_json, make_store, to_json

st.set_page_config(page_title="InvestTrack", page_icon="📈", layout="wide")

# Categorical series colors (fixed order) and status colors readable on light and dark.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
GOOD, BAD = "#0ca30c", "#d03b3b"
DISCLAIMER = (
    "Educational tool, not financial advice. Signals describe the past and do not "
    "predict the future. Every investment can lose money."
)
TASK_ICONS = notify.TASK_ICONS
HOME_CURRENCIES = ["AMD", "USD", "EUR", "RUB", "GEL"]
OTHER_BROKER = "Other broker (enter fees)"
SYNC_SECONDS = 20  # how often to look for changes made on your other devices
SECTION_OPTIONS = ["", *BUCKET_KEYS]  # "" = not assigned
EDITOR_PREFIXES = ("tx_editor", "fill_", "targets_", "edit_targets_")


# ---------------------------------------------------------------- settings, login, data store

def secret(key: str, default=None):
    """A value from Streamlit secrets (cloud settings or .streamlit/secrets.toml), if any."""
    try:
        return st.secrets[key]
    except Exception:  # no secrets file, or key missing
        return default


def get_store():
    """Where this session reads and writes data (chosen from the secrets, once per session)."""
    if "store" not in st.session_state:
        config = secret("github_store")
        st.session_state.store = make_store(dict(config) if config else None)
    return st.session_state.store


def require_login() -> None:
    password = secret("APP_PASSWORD") or os.environ.get("INVESTAPP_PASSWORD", "")
    if not password or st.session_state.get("authed"):
        return
    st.title("📈 InvestTrack")
    with st.form("login"):
        entered = st.text_input("Password", type="password")
        if st.form_submit_button("Open", type="primary"):
            if hmac.compare_digest(entered.encode(), str(password).encode()):
                st.session_state.authed = True
                st.rerun()
            st.error("Wrong password.")
    st.stop()


def reset_editors() -> None:
    """Forget unsaved table edits so tables show the newest data."""
    for key in [k for k in st.session_state if str(k).startswith(EDITOR_PREFIXES)]:
        del st.session_state[key]


def flash(message: str, icon: str = "✅") -> None:
    """Show a short message after the next rerun."""
    st.session_state["flash"] = (message, icon)


def get_state():
    """This device's copy of the data, refreshed when another device saved changes."""
    ss, store = st.session_state, get_store()
    if "state" not in ss:
        ss.state, ss.version = store.load()
        ss.synced_at = time.time()
    elif store.kind == "github" and time.time() - ss.get("synced_at", 0) > SYNC_SECONDS:
        ss.synced_at = time.time()
        try:
            if store.remote_version() != ss.version:
                ss.state, ss.version = store.load()
                reset_editors()
                st.toast("Updated with changes from your other device.", icon="🔄")
        except OSError:
            pass  # offline: keep working with what we have
    return ss.state


def persist() -> None:
    ss, store = st.session_state, get_store()
    try:
        ss.version = store.save(ss.state, ss.get("version"))
        ss.synced_at = time.time()
        ss.pop("save_error", None)
    except ConflictError:
        ss.state, ss.version = store.load()
        reset_editors()
        flash("Your data was changed on another device, so this screen reloaded it. Please repeat your last step.",
              "⚠️")
    except OSError as e:
        ss["save_error"] = str(e)


def transactions_changed() -> None:
    st.session_state.pop("tx_editor", None)
    persist()


@st.cache_data(ttl=900, show_spinner="Downloading prices...")
def get_prices(tickers: tuple[str, ...], period: str) -> pd.DataFrame:
    return fetch_prices(list(tickers), period)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def check_update() -> bool | None:
    # Only the PC launcher installs updates; the online version updates itself.
    return updater.update_available(timeout=3) if os.environ.get("INVESTAPP_LAUNCHER") else None


# ---------------------------------------------------------------- formatting & charts

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


def now_vs_target_chart(rows: pd.DataFrame, label_col: str, title: str, key: str) -> None:
    """Horizontal grouped bars: current share vs target share."""
    fig = go.Figure()
    for j, (name, col) in enumerate([("Now", "now"), ("Target", "target")]):
        fig.add_trace(go.Bar(name=name, y=rows[label_col], x=rows[col], orientation="h", marker_color=SERIES[j],
                             hovertemplate="%{y} " + name.lower() + ": %{x:.1%}<extra></extra>"))
    fig.update_layout(barmode="group", height=90 + 56 * len(rows), xaxis=dict(tickformat=".0%"),
                      yaxis=dict(autorange="reversed"), margin=dict(l=10, r=10, t=40, b=10),
                      legend=dict(orientation="h", y=1.15, x=0), bargap=0.45, bargroupgap=0.1, title=title)
    st.plotly_chart(fig, width="stretch", key=key)


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

require_login()
try:
    state = get_state()
except OSError as e:
    st.error(f"Could not load your data from GitHub: {e}. Check the token and repository in the app's secrets "
             "(Settings → 'Use on PC and iPhone' explains them).")
    st.stop()
store = get_store()

all_tickers = tuple(sorted(set(state.all_tickers()) | set(state.market_overview)))
prices = get_prices(all_tickers, history_period(state))
if prices.empty:
    st.error("Could not download market prices. Check your internet connection and press Refresh.")
    st.stop()
latest = latest_prices(prices)
home = state.home_currency
rate = fx_rate(latest, home)  # home currency per USD
broker = state.broker_profile
today = pd.Timestamp.today().normalize()


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
try:
    section_holdings = {b: value_holdings(h, latest) for b, h in holdings_by_bucket(state.transactions).items()}
    section_error = None
except ValueError as e:
    section_holdings, section_error = {}, str(e)
section_values = {b: current_values(v) for b, v in section_holdings.items()}
tasks = build_tasks(state, prices, today)
tasks_now = [t for t in tasks if t.priority < 2]

if "flash" in st.session_state:
    message, icon = st.session_state.pop("flash")
    st.toast(message, icon=icon)
if st.session_state.get("save_error"):
    st.error(f"Could not save to GitHub ({st.session_state['save_error']}). Your last change is only on this "
             "screen for now; it will be saved with your next change once the connection works.")

# ---------------------------------------------------------------- sidebar

with st.sidebar:
    st.title("📈 InvestTrack")
    st.caption(("☁️ " if store.kind == "github" else "💻 ") + store.describe())
    st.caption(f"Prices refresh every 15 minutes. Loaded {datetime.now():%Y-%m-%d %H:%M}.")
    if st.button("Refresh prices now", width="stretch"):
        st.cache_data.clear()
        st.rerun()
    if home != TRADING_CURRENCY and not math.isnan(rate):
        st.metric(f"1 USD in {home}", f"{rate:,.2f}")
    st.caption("🔔 Telegram reminders: " + (f"on ({state.telegram.get('name') or 'connected'})"
                                            if state.telegram_ready else "off (Settings → Reminders)"))
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
            reset_editors()
            persist()
            flash("Backup restored.")
            st.rerun()
        except (ValueError, KeyError, TypeError) as e:
            st.error(f"That file could not be read: {e}")
    st.divider()
    st.caption(DISCLAIMER)

# ---------------------------------------------------------------- notification bar (every page)

if tasks_now:
    items = " · ".join(
        f"{BUCKETS[t.bucket].icon + ' ' if t.bucket in BUCKETS else ''}{t.title}" for t in tasks_now[:4]
    ) + (" · …" if len(tasks_now) > 4 else "")
    st.warning(f"**{len(tasks_now)} thing(s) to do now**: {items}. Open the **Action** tab.", icon="🔔")

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
                name = KNOWN_NAMES.get(o.ticker, "")
                st.markdown(f"- **{qty} {o.ticker}**{f' ({name})' if name else ''} at about {o.price:,.2f} USD each "
                            f"= {money(o.amount)}")
            st.caption("After buying, change the numbers below to what you actually paid (shares, price, fee), "
                       "then press Done. The purchase is recorded in this section of your portfolio.")
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
                trades = [Transaction(str(today.date()), r.ticker, "buy", r.shares, r.price, r.fee or 0.0, note,
                                      task.bucket)
                          for r in edited.itertuples() if r.shares and r.shares > 0 and r.price and r.price > 0]
                complete_task(state, task, trades, today)
                transactions_changed()
                flash(f"Recorded {len(trades)} purchase(s).")
                st.rerun()
            if c2.button("Skip", key=f"skip_{task.key}"):
                skip_task(state, task, today)
                persist()
                st.rerun()
            if 0 < task.overdue < len(task.log_keys) and plan is not None and c3.button(
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
            if 0 < task.overdue < len(task.log_keys) and plan is not None and c3.button(
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


def section_overview() -> None:
    """Where each section's money goes, what's due, and what's next."""
    cols = st.columns(3)
    for col, key in zip(cols, BUCKET_KEYS):
        b = BUCKETS[key]
        plans = [p for p in state.plans if p.bucket == key and p.active]
        with col.container(border=True):
            st.markdown(f"**{b.label}**")
            st.caption(f"For money you need {b.horizon}.")
            if not plans:
                funds = ", ".join(f"{t} {w:g}%" for t, w in b.default_mix.items())
                st.markdown(f"Suggested: **{funds}**")
                st.caption("No plan yet: use Quick start in **Plans**.")
                continue
            for p in plans:
                funds = ", ".join(f"{t} {w:.0%}" for t, w in p.targets.items())
                due = [t for t in tasks_now if t.plan_id == p.id]
                if due:
                    status = "🔔 due now"
                else:
                    nd = next_dates(p, today + pd.Timedelta(days=1), 1)[0]
                    status = f"next {nd:%a %b %d}"
                st.markdown(f"Invest in **{funds}**  \n{fmt(p.amount, p.currency)} {p.frequency} · {status}")
            held = sum(section_values.get(key, {}).values())
            if held:
                st.caption(f"You hold {money(held)} here.")


with tab_action:
    st.header(f"Action: what to do now ({today:%A, %B %d})")
    optional = [t for t in tasks if t.priority >= 2]
    st.markdown(f"**{len(tasks_now)}** to do now · **{len(optional)}** optional · "
                f"**{done_today(state, today)}** done today")

    st.subheader("Where your money goes")
    section_overview()

    if not tasks:
        st.success("🎉 You're all done for today. Come back tomorrow.")
    for key in BUCKET_KEYS:
        mine = [t for t in tasks if t.bucket == key]
        if mine:
            st.subheader(BUCKETS[key].label)
            for task in sorted(mine, key=lambda t: t.priority):
                render_task(task)
    general = [t for t in tasks if t.bucket not in BUCKETS]
    if general:
        st.subheader("General")
        for task in general:
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
                    upcoming.append({"date": d.strftime("%a %b %d"), "section": bucket_label(p.bucket), "plan": p.name,
                                     "amount": fmt(p.amount, p.currency), "_d": d})
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
        for period_label, code in PORTFOLIO_PERIODS.items():
            perf = period_performance(history, code)
            row = {"period": period_label, "gain (USD)": perf["gain"], "return": perf["gain_pct"],
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


def targets_editor(base: dict[str, float], key: str) -> pd.DataFrame:
    return st.data_editor(
        pd.DataFrame({"ticker": list(base), "weight %": list(base.values())}),
        num_rows="dynamic", hide_index=True, key=key,
        column_config={"weight %": st.column_config.NumberColumn(min_value=0.0, max_value=100.0, step=1.0)},
    )


def targets_from(df: pd.DataFrame) -> dict[str, float]:
    return {str(r["ticker"]).strip().upper(): float(r["weight %"]) for r in df.to_dict("records")
            if r.get("ticker") and r.get("weight %")}


def suggested_threshold(per_buy_usd: float, n_orders: int, currency: str) -> float:
    """Amount (plan currency) to save before buying so fees stay at or under 1%; 0 if not needed."""
    good = broker.min_good_order(MAX_FEE_SHARE) * n_orders
    if not broker.chosen or per_buy_usd >= good or not math.isfinite(good):
        return 0.0
    step = 1000 if currency == "AMD" else 10
    return math.ceil(from_usd(good, currency, rate) / step) * step


def plan_card(p: Plan) -> None:
    title = f"**{p.name}**: {fmt(p.amount, p.currency)} {p.frequency}" + ("" if p.active else " (paused)")
    with st.expander(title, expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Each time", fmt(p.amount, p.currency))
        c2.metric("Per month", fmt(p.amount * PERIODS_PER_MONTH[p.frequency], p.currency))
        c3.metric("Saved, not yet invested", fmt(p.pot, p.currency))
        nd = next_dates(p, today, 1)[0]
        due_now = any(t.plan_id == p.id and t.priority < 2 for t in tasks)
        c4.metric("Next", "Due now" if due_now else ("Today" if nd == today else f"{nd:%a %b %d}"))
        mix = ", ".join(f"{t} {w:.0%}" for t, w in p.targets.items())
        how = (f"Saves until {fmt(p.buy_threshold, p.currency)}, then buys." if p.buy_threshold else "Buys every time.")
        st.markdown(f"**Invests in:** {mix}. {how} " + ("One order per purchase. " if p.one_order else "")
                    + (f"Extra +{p.dip_boost:.0%} during dips." if p.dip_boost else ""))
        st.markdown(plan_fee_line(p))
        outside = [t for t in p.targets if state.allowed_tickers and t not in state.allowed_tickers]
        if outside:
            st.warning(f"{', '.join(outside)} is not on your broker list (Settings).")

        with st.form(f"edit_{p.id}"):
            st.markdown("**Change this plan**")
            e1, e2, e3 = st.columns(3)
            name = e1.text_input("Name", value=p.name, key=f"name_{p.id}")
            section = e2.selectbox("Section", BUCKET_KEYS, index=BUCKET_KEYS.index(p.bucket),
                                   format_func=bucket_label, key=f"sec_{p.id}")
            freq_options = list(dict.fromkeys([*PLAN_FREQUENCIES, p.frequency]))
            freq = e3.selectbox("How often you add money", freq_options, index=freq_options.index(p.frequency),
                                key=f"freq_{p.id}")
            e4, e5, e6 = st.columns(3)
            amount = e4.number_input(f"Amount each time ({p.currency})", min_value=1.0, value=float(p.amount),
                                     step=100.0 if p.currency == "AMD" else 1.0, key=f"amt_{p.id}")
            threshold = e5.number_input(f"Save, then buy at ({p.currency}; 0 = buy every time)", min_value=0.0,
                                        value=float(p.buy_threshold), step=1000.0 if p.currency == "AMD" else 10.0,
                                        key=f"thr_{p.id}")
            boost_opts = {"Off": 0.0, "+25%": 0.25, "+50%": 0.5, "+100%": 1.0}
            boost = e6.selectbox("Extra during dips (optional)", list(boost_opts), key=f"boost_{p.id}",
                                 index=list(boost_opts.values()).index(p.dip_boost) if p.dip_boost in boost_opts.values() else 0)
            f1, f2 = st.columns(2)
            one = f1.checkbox("One order per purchase (fewer fees)", value=p.one_order, key=f"one_{p.id}")
            whole = f2.checkbox("Whole shares only", value=p.whole_shares, key=f"whole_{p.id}")
            st.caption("Funds and weights")
            tdf = targets_editor({t: round(w * 100, 2) for t, w in p.targets.items()}, f"edit_targets_{p.id}")
            if st.form_submit_button("Save changes"):
                try:
                    p.targets = Plan(p.name, 1, "monthly", targets_from(tdf)).targets  # validates the weights
                    p.name, p.bucket, p.frequency = name.strip() or p.name, section, freq
                    p.amount, p.buy_threshold, p.dip_boost, p.one_order, p.whole_shares = (
                        amount, threshold, boost_opts[boost], one, whole)
                    persist()
                    flash("Plan updated.")
                    st.rerun()
                except (ValueError, TypeError) as e:
                    st.error(str(e))

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

        held = section_values.get(p.bucket, {})
        rb = rebalance_trades(p.targets, {t: held.get(t, 0.0) for t in p.targets})
        if len(p.targets) > 1 and rb["current_value"].sum() > 0:
            rows = rb.rename(columns={"current_weight": "now", "target_weight": "target"})
            now_vs_target_chart(rows, "ticker", "Balance in this section: now vs target", f"rb_{p.id}")


def quick_start() -> None:
    st.markdown("Tell the app how much you can invest per month. It splits the money into the three sections and "
                "shows where each part goes. You can change everything afterwards.")
    c1, c2, c3 = st.columns(3)
    cur = c1.selectbox("Currency", list(dict.fromkeys([home, "USD"])), key="qs_cur")
    budget = c2.number_input(f"Monthly budget ({cur})", min_value=1.0,
                             value=50_000.0 if cur == "AMD" else 150.0, step=5_000.0 if cur == "AMD" else 10.0,
                             key=f"qs_budget_{cur}")
    freq = c3.selectbox("How often do you add money?", PLAN_FREQUENCIES, index=2, key="qs_freq",
                        help="Monthly (e.g. after payday) keeps fees lowest. This is separate from the sections: "
                             "any section can get money daily, weekly or monthly.")
    s1, s2, s3 = st.columns(3)
    split = {"short": s1.slider(f"{BUCKETS['short'].label} %", 0, 100, int(state.bucket_split.get("short", 20)), key="qs_s"),
             "income": s2.slider(f"{BUCKETS['income'].label} %", 0, 100, int(state.bucket_split.get("income", 30)), key="qs_i"),
             "long": s3.slider(f"{BUCKETS['long'].label} %", 0, 100, int(state.bucket_split.get("long", 50)), key="qs_l")}
    total = sum(split.values())
    if total == 0:
        st.error("Give at least one section a share of the budget.")
        return
    step = 100 if cur == "AMD" else 1
    drafts, rows = [], []
    for key, pct in split.items():
        if pct == 0:
            continue
        b = BUCKETS[key]
        targets = dict(b.default_mix)
        each = max(step, round(budget * pct / total / PERIODS_PER_MONTH[freq] / step) * step)
        each_usd = to_usd(each, cur, rate)
        one = len(targets) > 1 and freq in ("daily", "weekly")
        n_orders = 1 if one else len(targets)
        threshold = suggested_threshold(each_usd, n_orders, cur)
        buy_usd = max(each_usd, to_usd(threshold, cur, rate))
        fee = sum(broker.order_fee(buy_usd / n_orders, 100.0) for _ in range(n_orders))
        drafts.append(Plan(b.name, each, freq, targets, str(today.date()), currency=cur, one_order=one,
                           buy_threshold=threshold, bucket=key))
        row = {
            "section": b.label, "invest in": ", ".join(f"{t} {w:g}%" for t, w in targets.items()),
            f"each time ({cur})": each, "≈ USD": each_usd,
            "how it buys": (f"saves, buys every ~{math.ceil(threshold / each)} times" if threshold else "buys every time"),
        }
        if broker.chosen:
            row.update({"fee per purchase (USD)": fee, "fee %": fee / buy_usd * 100})
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), hide_index=True,
                 column_config={f"each time ({cur})": st.column_config.NumberColumn(format="%,.0f"), "≈ USD": MONEY,
                                "fee per purchase (USD)": MONEY, "fee %": st.column_config.NumberColumn(format="%.2f%%")})
    for key in split:
        if split[key]:
            st.caption(f"{BUCKETS[key].icon} {BUCKETS[key].why}")
    if not broker.chosen:
        st.info("Choose your broker in **Settings** first: then this table shows fees and the app plans around them.")
    if st.button("Create these plans", type="primary", key="qs_create"):
        for d in drafts:
            state.add_plan(d)
        state.bucket_split = {k: float(v) for k, v in split.items()}
        persist()
        flash(f"Created {len(drafts)} plans. Your first tasks are in the Action tab.")
        st.rerun()


def new_plan_form(key: str) -> None:
    b = BUCKETS[key]
    templates = {f"Suggested for this section ({', '.join(b.default_mix)})": dict(b.default_mix), **TEMPLATES}
    tpl = st.selectbox("Start from", list(templates) + ["Custom"], key=f"tpl_{key}")
    base = templates.get(tpl, {"VT": 100})
    with st.form(f"new_{key}"):
        n1, n2, n3, n4 = st.columns(4)
        name = n1.text_input("Plan name", value=b.name, key=f"name_new_{key}")
        cur = n2.selectbox("Currency", list(dict.fromkeys([home, "USD"])), key=f"cur_{key}")
        amount = n3.number_input("Amount each time", min_value=1.0, value=10_000.0 if home == "AMD" else 25.0,
                                 key=f"amount_{key}")
        freq = n4.selectbox("How often", PLAN_FREQUENCIES, index=2, key=f"freq_new_{key}")
        n5, n6 = st.columns(2)
        start = n5.date_input("First contribution", date.today(), key=f"start_{key}")
        one = n6.checkbox("One order per purchase (fewer fees)", value=len(base) > 1, key=f"one_new_{key}")
        tdf = targets_editor(base, f"targets_{key}_{tpl}")
        if st.form_submit_button("Create plan", type="primary"):
            try:
                targets = targets_from(tdf)
                n_orders = 1 if one else max(1, len(targets))
                threshold = suggested_threshold(to_usd(amount, cur, rate), n_orders, cur)
                state.add_plan(Plan(name, amount, freq, targets, str(start), currency=cur, one_order=one,
                                    buy_threshold=threshold, bucket=key))
                persist()
                flash("Plan created." + (f" It saves until {fmt(threshold, cur)} before buying, to keep fees low."
                                         if threshold else ""))
                st.rerun()
            except (ValueError, TypeError) as e:
                st.error(str(e))


with tab_plans:
    st.header("Investing plans")
    st.caption("Your money is split into three sections by when you may need it. Each plan adds a fixed amount to "
               "one section on a schedule. Every due purchase shows up in **Action**.")
    with st.expander("Quick start: set up all three sections", expanded=not state.plans):
        quick_start()

    for key, sub in zip(BUCKET_KEYS, st.tabs([BUCKETS[k].label for k in BUCKET_KEYS])):
        with sub:
            b = BUCKETS[key]
            st.markdown(f"**For money you need {b.horizon}.** {b.purpose}")
            st.caption(b.why)
            mine = [p for p in state.plans if p.bucket == key]
            if not mine:
                st.write("No plan in this section yet.")
            for p in mine:
                plan_card(p)
            with st.expander("Add a plan to this section"):
                new_plan_form(key)

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
        "roughly 7-10% a year in US dollars over long periods, with big swings along the way; Treasury bills and bonds "
        "earn less but move much less. The dram's exchange rate also moves. These lines are illustrations, not forecasts."
    )

# ---------------------------------------------------------------- Portfolio

def holdings_table(df: pd.DataFrame) -> None:
    show = df.sort_values("market_value", ascending=False)
    cols = ["ticker", "shares", "avg_cost", "price", "market_value", "unrealized_pl", "unrealized_pct", "weight"]
    st.dataframe(
        as_pct(show[cols], ["unrealized_pct", "weight"]).style.map(color_sign, subset=["unrealized_pl", "unrealized_pct"]),
        hide_index=True,
        column_config={"shares": SHARES, "avg_cost": MONEY, "price": MONEY, "market_value": MONEY,
                       "unrealized_pl": MONEY, "unrealized_pct": PCT, "weight": SHARE},
    )


with tab_port:
    st.header("My investments")
    if valued.empty:
        st.write("No holdings yet. Purchases you mark as done in **Action** appear here, sorted into their section.")
    else:
        total = valued["market_value"].sum()
        cost = valued["cost_basis"].sum()
        c1, c2, c3, c4 = st.columns(4)
        metric_money(c1, "Market value", total)
        metric_money(c2, "Cost basis", cost)
        metric_money(c3, "Unrealized gain", total - cost, fmt_pct((total - cost) / cost if cost else math.nan))
        metric_money(c4, "Realized gain (from sales)", realized_total(state.transactions))

        st.subheader("By section")
        if section_error:
            st.error(f"Some trades can't be sorted into sections: {section_error}. Fix the 'bucket' column in "
                     "**All trades** below.")
        target_split = normalize_split(state.bucket_split)
        split_rows = []
        cols = st.columns(3)
        for col, key in zip(cols, BUCKET_KEYS):
            v = section_holdings.get(key)
            sec_value = float(v["market_value"].sum()) if v is not None and not v.empty else 0.0
            sec_cost = float(v["cost_basis"].sum()) if v is not None and not v.empty else 0.0
            share = sec_value / total if total else 0.0
            split_rows.append({"section": BUCKETS[key].label, "now": share, "target": target_split[key]})
            gain = fmt_pct((sec_value - sec_cost) / sec_cost) if sec_cost else None
            with col:
                metric_money(st, BUCKETS[key].label, sec_value, gain)
                st.caption(f"{share:.0%} of your investments (target {target_split[key]:.0%})")
        now_vs_target_chart(pd.DataFrame(split_rows), "section", "Sections: share now vs target", "split_chart")
        for key in [*BUCKET_KEYS, ""]:
            v = section_holdings.get(key)
            if v is None or v.empty:
                continue
            with st.expander(f"{bucket_label(key)}: {money(float(v['market_value'].sum()))}", expanded=bool(key)):
                holdings_table(v)
                if not key:
                    st.caption("These trades aren't in a section yet (for example, imported ones). Set their "
                               "'bucket' in **All trades** below.")

        st.subheader("All holdings together")
        holdings_table(valued)
        st.caption("Amounts in USD, the currency your funds trade in.")
        left, right = st.columns([3, 2])
        with left:
            if not history.empty:
                st.plotly_chart(line_chart({"Portfolio value": history["value"], "Money invested": history["invested"]},
                                           "Value vs money invested (USD)"), width="stretch")
        with right:
            show = valued.sort_values("market_value", ascending=False)
            fig = go.Figure(go.Bar(
                x=show["weight"], y=show["ticker"], orientation="h", marker_color=SERIES[0],
                text=[f"{w:.1%}" for w in show["weight"]], textposition="outside", width=0.5,
                hovertemplate="%{y}: %{x:.1%}<extra></extra>",
            ))
            fig.update_layout(title="Allocation by fund", height=max(220, 80 + 40 * len(show)),
                              margin=dict(l=10, r=40, t=50, b=10),
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
                import_section = st.selectbox("Put these trades in section", SECTION_OPTIONS, format_func=bucket_label,
                                              key="import_section")
                trades, problems = parse_trades(raw, mapping)
                for t in trades:
                    t.bucket = import_section
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
        c1, c2, c3, c0 = st.columns(4)
        t_ticker = c1.text_input("Ticker", placeholder="VT")
        t_side = c2.selectbox("Buy or sell", ["buy", "sell"])
        t_date = c3.date_input("Date", date.today())
        t_section = c0.selectbox("Section", BUCKET_KEYS, index=2, format_func=bucket_label)
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
                trade = Transaction(str(t_date), tk, t_side, shares, price, t_fee, t_note, t_section)
                holdings_by_bucket(state.transactions + [trade])  # rejects selling more than the section holds
                state.transactions.append(trade)
                transactions_changed()
                flash(f"Saved: {t_side} {shares:.4f} {tk} at {price:,.2f}.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))

    st.subheader("All trades")
    st.caption("Edit cells (including the section in the 'bucket' column) or select rows and press Delete, then save.")
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
            "bucket": st.column_config.SelectboxColumn(
                "bucket", options=SECTION_OPTIONS, help="short = daily bread, income = monthly income, long = long term"),
        },
    )
    if st.button("Save changes to trades"):
        try:
            new_txs = [
                Transaction(str(r["date"]), r["ticker"], r["side"], r["shares"], r["price"], r.get("fee") or 0.0,
                            r.get("note") or "", r.get("bucket") or "")
                for r in edited_tx.to_dict("records") if r.get("ticker")
            ]
            holdings_by_bucket(new_txs)
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

SECRETS_TEMPLATE = '''APP_PASSWORD = "choose-a-password"

[github_store]
token = "github_pat_paste-your-token-here"
repo = "ggemax55/investtrack-data"
path = "portfolio.json"
'''

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
    st.caption("The app can't log in to a broker or place orders. It tells you what to buy; you buy it in your "
               "broker's app and press Done. Trades can also be imported from your broker's CSV export (Portfolio). "
               "With Interactive Brokers, a read-only automatic connection can be added once you have the account.")

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

    # ------------------------------------------------ reminders
    st.subheader("🔔 Reminders")
    st.markdown("The yellow bar at the top of every page always lists what's due. To be reminded when the app is "
                "closed, use Telegram (a message on your phone and PC) and/or your phone's calendar.")
    st.markdown("**Telegram**")
    st.markdown(
        "1. In Telegram, open **@BotFather**, send `/newbot`, and pick any name. It replies with a *token*.\n"
        "2. Paste the token below and press **Save**.\n"
        "3. Open your new bot in Telegram (BotFather gives you its link) and press **Start**.\n"
        "4. Press **Connect my Telegram**, then **Send test message**.\n"
        "5. For a message **every morning even when the app is closed**, also do step 6 of *Use on PC and iPhone* below."
    )
    with st.form("telegram"):
        token = st.text_input("Bot token", value=state.telegram.get("token", ""), type="password")
        app_url = st.text_input("Link to your app (sent with reminders)", value=state.app_url,
                                placeholder="https://your-app.streamlit.app")
        if st.form_submit_button("Save"):
            if token and not notify.valid_token(token):
                st.error("That doesn't look like a bot token. It looks like 123456789:AAH... (copy it from BotFather).")
            else:
                if token.strip() != state.telegram.get("token"):
                    state.telegram = {"token": token.strip(), "chat_id": "", "name": ""}
                state.app_url = app_url.strip()
                persist()
                flash("Saved.")
                st.rerun()
    t1, t2, t3 = st.columns(3)
    if t1.button("Connect my Telegram", disabled=not state.telegram.get("token")):
        try:
            found = notify.find_chat(state.telegram["token"])
            if found:
                state.telegram.update(chat_id=found[0], name=found[1])
                persist()
                flash(f"Connected to {found[1] or 'your Telegram'}.")
                st.rerun()
            else:
                st.warning("No message found yet. Open your bot in Telegram, press Start, then press this again.")
        except notify.NotifyError as e:
            st.error(f"Telegram said: {e}")
    if t2.button("Send test message", disabled=not state.telegram_ready):
        try:
            notify.send(state.telegram["token"], state.telegram["chat_id"], "✅ InvestTrack reminders are working.")
            st.success("Sent. Check Telegram.")
        except notify.NotifyError as e:
            st.error(f"Telegram said: {e}")
    if t3.button("Send today's to-do list now", disabled=not state.telegram_ready):
        try:
            text = notify.reminder_text(tasks, today, state.app_url) or "🎉 Nothing to do today in InvestTrack."
            notify.send(state.telegram["token"], state.telegram["chat_id"], text)
            st.success("Sent.")
        except notify.NotifyError as e:
            st.error(f"Telegram said: {e}")
    st.caption("Status: " + (f"connected to {state.telegram.get('name') or 'your Telegram'}." if state.telegram_ready
                             else "not connected."))

    st.markdown("**Phone calendar**")
    st.download_button(
        "📅 Add my plan dates to my calendar (.ics)", plans_calendar(state.plans, state.app_url),
        file_name="investtrack-reminders.ics", mime="text/calendar", disabled=not state.plans,
    )
    st.caption("On iPhone: open this file from Safari and choose **Add All**: your calendar then alerts you at 9:00 on "
               "every contribution day. Download it again after you change a plan's schedule.")

    # ------------------------------------------------ devices
    st.subheader("📱 Use on PC and iPhone")
    if store.kind == "github":
        st.success(f"This app is synced: {store.describe()}. Every device that opens it sees the same data.")
    else:
        st.info("Right now your data is only on this computer. Follow the steps below to open the app from your PC "
                "and your iPhone with the same data, free.")
    st.markdown(
        "1. **A private place for your data.** On GitHub, create a new repository named `investtrack-data`, choose "
        "**Private**, tick **Add a README file**, and create it.\n"
        "2. **A key that can only open that repository.** GitHub → your picture → **Settings** → **Developer settings** "
        "→ **Personal access tokens** → **Fine-grained tokens** → **Generate new token**. Repository access: **Only "
        "select repositories** → `investtrack-data`. Permissions → Repository permissions → **Contents: Read and "
        "write**. Generate and copy the token.\n"
        "3. **Put the app online.** Go to **share.streamlit.io**, sign in with GitHub, choose **Create app**: "
        "repository `ggemax55/Social`, branch `claude/investment-tracker-app`, file `app.py`. Open **Advanced "
        "settings** and paste the text below into **Secrets** (with your token and a password of your choice). "
        "Press **Deploy**. You get a link like `https://something.streamlit.app`.\n"
        "4. **Open it on both devices.** On your PC, bookmark the link. On your iPhone, open it in Safari → Share → "
        "**Add to Home Screen**: it gets an icon like an app. Both show the same data.\n"
        "5. **Bring your current data along.** Here, press **Download my data** (sidebar); in the online app press "
        "**Restore from a backup**. Then paste the online link into *Link to your app* under Reminders.\n"
        "6. **Morning reminders even when the app is closed.** On GitHub open `ggemax55/Social` → **Settings** → "
        "**Secrets and variables** → **Actions** → **New repository secret**: add `INVESTAPP_GITHUB_TOKEN` (the same "
        "token) and `INVESTAPP_GITHUB_REPO` (`ggemax55/investtrack-data`). Every day at 9:00 Yerevan time you get "
        "the to-do list in Telegram."
    )
    st.code(SECRETS_TEMPLATE, language="toml")
    st.caption("The free online version goes to sleep after about 12 hours without visits and wakes up when you open "
               "it (this takes a moment). Reminders keep working while it sleeps. To use the same data in this PC "
               "version too, save the text above as `.streamlit/secrets.toml` in the app folder.")

    st.subheader("App version")
    version = updater.local_version()
    status = check_update()
    st.write(f"Installed version: `{version[:7] if version else 'online / development copy'}`")
    if status is True:
        st.info("A new version is available. Close the app window and start it again: it updates itself.")
    elif status is False:
        st.success("You have the latest version.")
    else:
        st.caption("The PC version updates itself each time you start it with start-windows.bat or start-mac.command; "
                   "the online version updates automatically.")

# ---------------------------------------------------------------- Learn

with tab_learn:
    st.header("Getting started with investing")
    st.markdown(
        """
**Your three sections**
- 🍞 **Short term (daily bread)**: money you may need within about a year. Keep it safe and easy to sell:
  Treasury bills (SGOV) or an AMD bank deposit. It won't grow much, but it won't fall much either.
- 💵 **Medium term (monthly income)**: money for the next few years that pays you regularly: bonds (BND) and
  dividend-paying companies (SCHD). Some ups and downs.
- 🌳 **Long term (growth)**: money you won't touch for 5+ years: the whole world's stock market (VT). It can fall
  30-50% in a bad year, but over decades it has grown the most.

How often you add money (daily, weekly, monthly) is a separate choice: fees make monthly the cheapest.

**1. Build a safety net first.** Keep 3-6 months of expenses in savings and pay off high-interest debt
before investing in the long-term section.

**2. Diversify with low-cost index funds.** A fund like VT holds thousands of companies, so one bad company can't
sink you. Look for yearly fees (expense ratio) under 0.2%.

**3. Mind the fees.** With a minimum fee per order, many tiny purchases cost a lot. Check the fee table in
**Settings**; the app's "save, then buy" option keeps small plans cheap.

**4. Don't react to every headline.** Daily moves are mostly noise. Use the daily view to stay on plan,
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
- *Every day*: the yellow bar (and Telegram) tells you if something is due. Do it in your broker's app, then
  press Done in **Action**.
- *Every week*: the weekly check-in: read the weekly report.
- *Every month*: the monthly check-in: review the month, back up your data, and look at the balance check.

Tickers use Yahoo Finance symbols: US funds like `VT`, `VOO`, European listings with a suffix like `VWCE.DE`.
"""
    )
    st.caption(DISCLAIMER)
