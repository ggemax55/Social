"""InvestTrack: daily / weekly / monthly / yearly investment tracker.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import math
from datetime import date, datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from investapp.backtest import backtest_plan, compare_frequencies
from investapp.data import KNOWN_NAMES, MARKET_OVERVIEW, fetch_prices, latest_prices
from investapp.indicators import PERIODS, analyze, market_mood, rsi, sma, summary_table
from investapp.planner import (
    FREQUENCIES,
    PERIODS_PER_YEAR,
    TEMPLATES,
    Plan,
    is_due,
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
from investapp.report import REPORT_KINDS, build_report, history_period, plan_buy_list
from investapp.storage import AppState, from_json, load_state, save_state, to_json

st.set_page_config(page_title="InvestTrack", page_icon="📈", layout="wide")

# Categorical series colors (fixed order) and status colors readable on light and dark.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
GOOD, BAD = "#0ca30c", "#d03b3b"
DISCLAIMER = (
    "Educational tool, not financial advice. Signals describe the past and do not "
    "predict the future. Every investment can lose money."
)


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


def record_plan_buys(plan: Plan, orders: pd.DataFrame, key: str) -> None:
    """Button that saves a plan's suggested buys as today's trades."""
    buyable = orders[(orders["shares"] > 0) & orders["price"].notna()]
    if st.button("I bought these: record them", key=key, type="primary", disabled=buyable.empty):
        for o in buyable.itertuples():
            state.transactions.append(
                Transaction(str(date.today()), o.ticker, "buy", o.shares, o.price, 0.0, f"Plan: {plan.name}")
            )
        plan.last_done = str(date.today())
        transactions_changed()
        st.rerun()


@st.cache_data(ttl=900, show_spinner="Downloading prices...")
def get_prices(tickers: tuple[str, ...], period: str) -> pd.DataFrame:
    return fetch_prices(list(tickers), period)


def fmt_money(x: float) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/a"
    return f"{'-' if x < 0 else ''}{abs(x):,.2f} {get_state().currency}"


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


def as_pct(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    out[cols] = out[cols] * 100
    return out


def line_chart(series: dict[str, pd.Series], title: str, y_title: str = "", height: int = 380) -> go.Figure:
    fig = go.Figure()
    for i, (name, s) in enumerate(series.items()):
        fig.add_trace(
            go.Scatter(
                x=s.index, y=s.values, name=name, mode="lines",
                line=dict(width=2, color=SERIES[i % len(SERIES)]),
            )
        )
    fig.update_layout(
        title=title, height=height, hovermode="x unified", margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0), yaxis_title=y_title,
        showlegend=len(series) > 1,
    )
    return fig


def signals_for(prices: pd.DataFrame, tickers: list[str]) -> list[tuple[str, str, str]]:
    out = []
    for t in tickers:
        if t in prices.columns and not prices[t].dropna().empty:
            for s in analyze(prices[t], t).signals:
                if not s.message.startswith(("Uptrend", "Mixed")):
                    out.append((t, s.level, s.message))
    return out


def show_signals(items: list[tuple[str, str, str]]) -> None:
    if not items:
        st.success("Nothing unusual in your watchlist or holdings.")
    icons = {"positive": "🟢", "caution": "🟠", "info": "🔵"}
    for t, level, msg in items:
        st.markdown(f"{icons.get(level, '•')} **{t}**: {msg}")


# ---------------------------------------------------------------- sidebar

state = get_state()
with st.sidebar:
    st.title("📈 InvestTrack")
    st.caption(f"Prices refresh every 15 minutes. Loaded {datetime.now():%Y-%m-%d %H:%M}.")
    if st.button("Refresh prices now", width="stretch"):
        st.cache_data.clear()
        st.rerun()
    cur = st.text_input("Currency label", state.currency, max_chars=5)
    if cur and cur.upper() != state.currency:
        state.currency = cur.upper()
        persist()

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
            st.success("Backup restored.")
            st.rerun()
        except (ValueError, KeyError, TypeError) as e:
            st.error(f"That file could not be read: {e}")
    st.divider()
    st.caption(DISCLAIMER)

all_tickers = tuple(sorted(set(state.all_tickers()) | set(state.market_overview)))
prices = get_prices(all_tickers, history_period(state))
if prices.empty:
    st.error("Could not download market prices. Check your internet connection and press Refresh.")
    st.stop()
latest = latest_prices(prices)

try:
    holdings = compute_holdings(state.transactions)
except ValueError as e:
    st.error(f"Your transactions don't add up: {e}. Fix them in the Portfolio tab.")
    holdings = compute_holdings([])
valued = value_holdings(holdings, latest)
values = current_values(valued)
history = value_history(state.transactions, prices)

tab_today, tab_markets, tab_port, tab_plans, tab_analyze, tab_bt, tab_reports, tab_learn = st.tabs(
    ["Today", "Markets", "Portfolio", "Plans", "Analyze", "Backtest", "Reports", "Learn"]
)

# ---------------------------------------------------------------- Today

with tab_today:
    today = pd.Timestamp.today().normalize()
    st.header(f"Today: {today:%A, %B %d, %Y}")
    overview = [t for t in state.market_overview if t in prices.columns and t != "^VIX"]
    analyses = [analyze(prices[t], t) for t in overview if not prices[t].dropna().empty]
    st.info(market_mood(analyses, latest.get("^VIX")))

    c1, c2, c3, c4 = st.columns(4)
    cur = state.currency
    if not history.empty:
        day = period_performance(history, "1D")
        allt = period_performance(history, "ALL")
        c1.metric(f"Portfolio value ({cur})", fmt_num(day["end_value"]), fmt_pct(day["gain_pct"]), border=True)
        c2.metric(f"Gain today ({cur})", fmt_num(day["gain"]), border=True)
        c3.metric(f"All-time gain ({cur})", fmt_num(allt["gain"]), fmt_pct(allt["gain_pct"]), border=True)
    else:
        c1.metric(f"Portfolio value ({cur})", fmt_num(0.0), border=True)
        c2.metric(f"Gain today ({cur})", "n/a", border=True)
        c3.metric(f"All-time gain ({cur})", "n/a", border=True)
    due_today = [p for p in state.plans if is_due(p, today) and p.last_done != str(today.date())]
    c4.metric("Contributions still due today", len(due_today), border=True)

    st.subheader("Your investing plans")
    if not state.plans:
        st.write("You have no plans yet. Create one in the **Plans** tab, e.g. 100 every month into an index fund.")
    for i, p in enumerate(state.plans):
        if not p.active:
            continue
        nxt = next_dates(p, today, 1)[0]
        if is_due(p, today) and p.last_done == str(today.date()):
            st.markdown(f"**✅ {p.name}**: today's {fmt_money(p.amount)} is recorded. Next: {next_dates(p, today + pd.Timedelta(days=1), 1)[0]:%a %b %d}.")
        elif is_due(p, today):
            st.markdown(f"**🔔 {p.name}: invest {fmt_money(p.amount)} today.** Suggested buys:")
            orders, left = plan_buy_list(p, values, latest)
            st.dataframe(
                as_pct(orders[["ticker", "target_weight", "amount", "price", "shares"]], ["target_weight"]),
                hide_index=True,
                column_config={"target_weight": SHARE, "amount": MONEY, "price": MONEY,
                               "shares": st.column_config.NumberColumn(format="%.4f")},
            )
            if left > 0.005:
                st.caption(f"Cash left over (less than one share): {fmt_money(left)}")
            record_plan_buys(p, orders, f"today_rec{i}")
        else:
            st.markdown(f"**{p.name}**: next {fmt_money(p.amount)} on **{nxt:%a %b %d}** ({(nxt - today).days} days).")

    if not history.empty:
        st.subheader("How you're doing")
        rows = []
        for label, code in PORTFOLIO_PERIODS.items():
            perf = period_performance(history, code)
            rows.append({"period": label, "gain": perf["gain"], "return": perf["gain_pct"], "money added": perf["net_flows"]})
        perf_df = as_pct(pd.DataFrame(rows), ["return"])
        st.dataframe(
            perf_df.style.map(color_sign, subset=["gain", "return"]),
            hide_index=True,
            column_config={"gain": MONEY, "return": PCT, "money added": MONEY},
        )

    st.subheader("Signals to notice")
    show_signals(signals_for(prices, sorted(set(state.watchlist) | set(values))))

# ---------------------------------------------------------------- Markets

def market_table(tickers: list[str]) -> None:
    cols = [t for t in tickers if t in prices.columns]
    table = summary_table(prices[cols], KNOWN_NAMES) if cols else pd.DataFrame()
    if table.empty:
        st.write("No data.")
        return
    table = as_pct(table, [*PERIODS, "from_high", "volatility"])
    st.dataframe(
        table.style.map(color_sign, subset=list(PERIODS)),
        hide_index=True,
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

    st.subheader("My watchlist")
    wl_text = st.text_input("Tickers (comma separated, Yahoo Finance symbols, e.g. AAPL, VOO, BTC-USD)", ", ".join(state.watchlist))
    new_wl = [t.strip().upper() for t in wl_text.split(",") if t.strip()]
    if new_wl != state.watchlist:
        state.watchlist = new_wl
        persist()
        st.rerun()
    market_table(state.watchlist)

    st.subheader("Compare performance")
    choices = [t for t in prices.columns if t != "^VIX"]
    default = [t for t in ["SPY", "QQQ", "VXUS", "BND"] if t in choices] or choices[:3]
    picked = st.multiselect("Tickers (up to 8)", choices, default=default, max_selections=8)
    rng = st.segmented_control("Range", ["1M", "3M", "6M", "YTD", "1Y", "2Y"], default="1Y")
    if picked:
        end = prices.index[-1]
        offsets = {"1M": 1, "3M": 3, "6M": 6, "1Y": 12, "2Y": 24}
        start = (
            pd.Timestamp(year=end.year, month=1, day=1)
            if rng == "YTD"
            else end - pd.DateOffset(months=offsets.get(rng or "1Y", 12))
        )
        series = {}
        for t in picked:
            s = prices[t].dropna()
            s = s[s.index >= start]
            if not s.empty:
                series[t] = s / s.iloc[0] * 100
        st.plotly_chart(line_chart(series, "Growth of 100 invested at the start of the range", "Value"), width="stretch")

# ---------------------------------------------------------------- Portfolio

with tab_port:
    st.header("My portfolio")
    if valued.empty:
        st.write("No holdings yet. Record your first purchase below.")
    else:
        total = valued["market_value"].sum()
        cost = valued["cost_basis"].sum()
        cur = state.currency
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(f"Market value ({cur})", fmt_num(total), border=True)
        c2.metric(f"Cost basis ({cur})", fmt_num(cost), border=True)
        c3.metric(f"Unrealized gain ({cur})", fmt_num(total - cost), fmt_pct((total - cost) / cost if cost else math.nan), border=True)
        c4.metric(f"Realized gain ({cur})", fmt_num(realized_total(state.transactions)), border=True, help="Profit or loss locked in by selling")

        show = valued.sort_values("market_value", ascending=False)
        cols = ["ticker", "shares", "avg_cost", "price", "market_value", "unrealized_pl", "unrealized_pct", "weight"]
        st.dataframe(
            as_pct(show[cols], ["unrealized_pct", "weight"]).style.map(color_sign, subset=["unrealized_pl", "unrealized_pct"]),
            hide_index=True,
            column_config={
                "shares": st.column_config.NumberColumn(format="%.4f"), "avg_cost": MONEY, "price": MONEY,
                "market_value": MONEY, "unrealized_pl": MONEY, "unrealized_pct": PCT, "weight": SHARE,
            },
        )
        left, right = st.columns([3, 2])
        with left:
            if not history.empty:
                st.plotly_chart(
                    line_chart({"Portfolio value": history["value"], "Money invested": history["invested"]}, "Value vs money invested"),
                    width="stretch",
                )
        with right:
            fig = go.Figure(
                go.Bar(
                    x=show["weight"], y=show["ticker"], orientation="h", marker_color=SERIES[0],
                    text=[f"{w:.1%}" for w in show["weight"]], textposition="outside", width=0.5,
                    hovertemplate="%{y}: %{x:.1%}<extra></extra>",
                )
            )
            fig.update_layout(
                title="Allocation", height=max(220, 80 + 40 * len(show)), margin=dict(l=10, r=40, t=50, b=10),
                xaxis=dict(tickformat=".0%", range=[0, float(show["weight"].max()) * 1.25]), yaxis=dict(autorange="reversed"),
            )
            st.plotly_chart(fig, width="stretch")

    st.subheader("Record a trade")
    with st.form("add_trade", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        t_ticker = c1.text_input("Ticker", placeholder="VOO")
        t_side = c2.selectbox("Buy or sell", ["buy", "sell"])
        t_date = c3.date_input("Date", date.today())
        c4, c5, c6, c7 = st.columns(4)
        t_mode = c4.radio("I know the...", ["money amount", "number of shares"], horizontal=False)
        t_qty = c5.number_input("Amount / shares", min_value=0.0, step=1.0, format="%.4f")
        t_price = c6.number_input("Price per share (0 = latest price)", min_value=0.0, step=0.01, format="%.4f")
        t_fee = c7.number_input("Fee", min_value=0.0, step=0.01)
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
            shares = t_qty / price if t_mode == "money amount" else t_qty
            try:
                trade = Transaction(str(t_date), tk, t_side, shares, price, t_fee, t_note)
                compute_holdings(state.transactions + [trade])  # rejects selling more than you own
                state.transactions.append(trade)
                transactions_changed()
                st.success(f"Saved: {t_side} {shares:.4f} {tk} at {price:,.2f}.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))

    st.subheader("All trades")
    st.caption("Edit cells or select rows and press Delete, then save.")
    tx_df = pd.DataFrame([t.to_dict() for t in state.transactions], columns=list(Transaction.__dataclass_fields__))
    tx_df["date"] = pd.to_datetime(tx_df["date"]).dt.date
    edited = st.data_editor(
        tx_df,
        num_rows="dynamic",
        hide_index=True,
        key="tx_editor",
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
                Transaction(str(r["date"]), r["ticker"], r["side"], r["shares"], r["price"], r.get("fee") or 0.0, r.get("note") or "")
                for r in edited.to_dict("records")
                if r.get("ticker")
            ]
            compute_holdings(new_txs)
            state.transactions = new_txs
            transactions_changed()
            st.success("Trades saved.")
            st.rerun()
        except (ValueError, TypeError) as e:
            st.error(f"Not saved: {e}")

# ---------------------------------------------------------------- Plans

with tab_plans:
    st.header("Investing plans")
    st.caption(
        "A plan invests a fixed amount on a schedule (daily, weekly, monthly or yearly) into a mix you choose. "
        "Each time, new money goes to whatever is below its target weight, so you stay balanced without selling."
    )
    for i, p in enumerate(state.plans):
        status = "" if p.active else " (paused)"
        with st.expander(f"**{p.name}**: {fmt_money(p.amount)} {p.frequency}{status}", expanded=i == 0):
            c1, c2, c3 = st.columns(3)
            c1.metric(f"Per contribution ({state.currency})", fmt_num(p.amount))
            c2.metric(f"Per year ({state.currency})", fmt_num(p.yearly_amount))
            nd = next_dates(p, pd.Timestamp.today(), 5)
            c3.metric("Next contribution", f"{nd[0]:%b %d, %Y}")
            st.caption("Upcoming: " + ", ".join(f"{d:%a %b %d}" for d in nd))

            orders, left = plan_buy_list(p, values, latest)
            st.markdown("**What the next contribution should buy**")
            st.dataframe(
                as_pct(orders[["ticker", "target_weight", "current_value", "amount", "price", "shares"]], ["target_weight"]),
                hide_index=True,
                column_config={"target_weight": SHARE, "current_value": MONEY, "amount": MONEY, "price": MONEY,
                               "shares": st.column_config.NumberColumn(format="%.4f")},
            )
            if left > 0.005:
                st.caption(f"Cash left over (less than one share): {fmt_money(left)}")
            if p.whole_shares and left >= p.amount - 0.005:
                st.warning(
                    "This amount can't buy a single whole share. Use a broker with fractional shares, "
                    "or invest a larger amount less often (e.g. monthly instead of daily)."
                )
            b1, b2, b3 = st.columns(3)
            with b1:
                record_plan_buys(p, orders, f"rec{i}")
            if b2.button("Resume" if not p.active else "Pause", key=f"pause{i}"):
                p.active = not p.active
                persist()
                st.rerun()
            if b3.button("Delete plan", key=f"del{i}"):
                state.plans.pop(i)
                persist()
                st.rerun()

            st.markdown("**Balance check** (do this about once a year)")
            rb = rebalance_trades(p.targets, {t: values.get(t, 0.0) for t in p.targets})
            if rb["current_value"].sum() <= 0:
                st.caption("Nothing invested in this plan's tickers yet.")
            else:
                fig = go.Figure()
                for j, (label, col) in enumerate([("Now", "current_weight"), ("Target", "target_weight")]):
                    fig.add_trace(go.Bar(
                        name=label, y=rb["ticker"], x=rb[col], orientation="h", marker_color=SERIES[j],
                        hovertemplate="%{y} " + label.lower() + ": %{x:.1%}<extra></extra>",
                    ))
                fig.update_layout(
                    barmode="group", height=90 + 56 * len(rb), xaxis=dict(tickformat=".0%"),
                    yaxis=dict(autorange="reversed"), margin=dict(l=10, r=10, t=30, b=10),
                    legend=dict(orientation="h", y=1.15, x=0), bargap=0.45, bargroupgap=0.1,
                )
                st.plotly_chart(fig, width="stretch", key=f"rb{i}")
                flagged = rb[rb["needs_rebalance"]]
                if flagged.empty:
                    st.success("All weights are within 5 points of target. No action needed.")
                else:
                    for r in flagged.itertuples():
                        verb = "Buy" if r.trade_value > 0 else "Sell"
                        st.warning(f"{r.ticker} is {r.current_weight:.0%} vs target {r.target_weight:.0%}: {verb} about {fmt_money(abs(r.trade_value))}, or simply steer new contributions.")

    st.subheader("Create a plan")
    template = st.selectbox("Start from a template (examples, not recommendations)", ["Custom"] + list(TEMPLATES))
    base = TEMPLATES.get(template, {"VOO": 100})
    with st.form("new_plan"):
        c1, c2, c3, c4 = st.columns(4)
        p_name = c1.text_input("Plan name", value=template if template != "Custom" else "My plan")
        p_amount = c2.number_input("Amount each time", min_value=1.0, value=100.0, step=10.0)
        p_freq = c3.selectbox("How often", FREQUENCIES, index=2)
        p_start = c4.date_input("First contribution", date.today())
        p_whole = st.checkbox("My broker only sells whole shares")
        targets_df = st.data_editor(
            pd.DataFrame({"ticker": list(base), "weight %": list(base.values())}),
            num_rows="dynamic", hide_index=True, key=f"targets_{template}",
            column_config={"weight %": st.column_config.NumberColumn(min_value=0.0, max_value=100.0, step=1.0)},
        )
        if st.form_submit_button("Create plan", type="primary"):
            try:
                targets = {str(r["ticker"]): float(r["weight %"]) for r in targets_df.to_dict("records") if r.get("ticker") and r.get("weight %")}
                state.plans.append(Plan(p_name, p_amount, p_freq, targets, str(p_start), p_whole))
                persist()
                st.rerun()
            except (ValueError, TypeError) as e:
                st.error(str(e))

    st.subheader("What could regular investing grow to?")
    c1, c2, c3 = st.columns(3)
    g_amount = c1.number_input("Amount", min_value=1.0, value=state.plans[0].amount if state.plans else 100.0, step=10.0, key="g_amt")
    g_freq = c2.selectbox("How often", FREQUENCIES, index=2, key="g_freq")
    g_years = c3.slider("Years", 1, 40, 20)
    proj = {}
    for r in (0.04, 0.07, 0.10):
        df = project_growth(g_amount, g_freq, g_years, r).set_index("year")
        proj[f"{r:.0%} a year"] = df["value"]
    proj["Money you put in"] = df["invested"]
    st.plotly_chart(line_chart(proj, f"{g_amount:,.0f} {g_freq} for {g_years} years", "Value"), width="stretch")
    st.caption(
        f"After {g_years} years you'd have put in {fmt_money(df['invested'].iloc[-1])}. "
        "Stocks have historically averaged roughly 7-10% a year over long periods, with big swings along the way; "
        "these smooth lines are illustrations, not forecasts."
    )

# ---------------------------------------------------------------- Analyze

with tab_analyze:
    st.header("Analyze a ticker")
    c1, c2 = st.columns([2, 1])
    a_ticker = c1.text_input("Ticker", "SPY").strip().upper()
    a_range = c2.segmented_control("Show", ["6M", "1Y", "2Y", "5Y"], default="1Y", key="a_range")
    if a_ticker:
        apx = get_prices((a_ticker,), "5y")
        if apx.empty or a_ticker not in apx.columns:
            st.error(f"No data for {a_ticker}. Use Yahoo Finance symbols, e.g. AAPL, VOO, BTC-USD, VWCE.DE.")
        else:
            s = apx[a_ticker].dropna()
            a = analyze(s, a_ticker)
            c = st.columns(5)
            c[0].metric("Price", f"{a.price:,.2f}", fmt_pct(a.returns["1D"]), help="Change vs the previous close")
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
                    "- **RSI**: measures how fast price moved recently, 0-100. Above 70 it rose unusually fast; below 30 "
                    "it fell unusually fast.\n"
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
    if source == "Custom":
        mix_text = st.text_input("Tickers and weights", "VOO:100", help="e.g. VTI:60, VXUS:30, BND:10")
        try:
            mix = {k.strip().upper(): float(v) for k, v in (part.split(":") for part in mix_text.split(",") if part.strip())}
        except ValueError:
            st.error("Write it like VTI:60, BND:40")
            mix = {}
        default_amount, default_freq = 100.0, "monthly"
    else:
        plan = state.plans[plan_names.index(source)]
        mix = {t: w * 100 for t, w in plan.targets.items()}
        default_amount, default_freq = plan.amount, plan.frequency
    c1, c2, c3 = st.columns(3)
    bt_amount = c1.number_input("Amount each time", min_value=1.0, value=float(default_amount), step=10.0, key="bt_amt")
    bt_freq = c2.selectbox("How often", FREQUENCIES, index=FREQUENCIES.index(default_freq), key="bt_freq")
    bt_start = c3.date_input("Start investing on", date.today().replace(year=date.today().year - 10), key="bt_start")
    if mix and st.button("Run backtest", type="primary"):
        bpx = get_prices(tuple(sorted(mix)), "max")
        try:
            res = backtest_plan(bpx, mix, bt_amount, bt_freq, bt_start)
            cur = state.currency
            c = st.columns(4)
            c[0].metric(f"Money put in ({cur})", fmt_num(res.total_invested))
            c[1].metric(f"Would be worth ({cur})", fmt_num(res.final_value), fmt_pct(res.total_return))
            c[2].metric(f"Profit ({cur})", fmt_num(res.profit))
            c[3].metric("Yearly return (money-weighted)", fmt_pct(res.annualized))
            first = res.history.index[0]
            if first.date() > bt_start:
                st.caption(f"Price history for this mix starts {first:%Y-%m-%d}, so the test starts there.")
            st.plotly_chart(
                line_chart({"Value": res.history["value"], "Money put in": res.history["invested"]}, "Backtest"),
                width="stretch",
            )
            st.markdown("**Does the schedule matter?** Same yearly budget, different frequencies:")
            cmp = compare_frequencies(bpx, mix, bt_amount * PERIODS_PER_YEAR[bt_freq], bt_start)
            st.dataframe(
                as_pct(cmp, ["total_return", "annualized"]).style.map(color_sign, subset=["profit", "total_return", "annualized"]),
                hide_index=True,
                column_config={"invested": MONEY, "final_value": MONEY, "profit": MONEY, "total_return": PCT, "annualized": PCT},
            )
            st.caption(
                "Typically the frequency barely matters; lump sums often win in rising markets because the money is "
                "invested longer, while regular investing reduces the regret of buying everything right before a fall."
            )
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

# ---------------------------------------------------------------- Learn

with tab_learn:
    st.header("Getting started with investing")
    st.markdown(
        """
**1. Build a safety net first.** Keep 3-6 months of expenses in savings and pay off high-interest debt
before investing. Only invest money you won't need for at least 5 years.

**2. Diversify with low-cost index funds.** A fund like a total-market or S&P 500 ETF holds hundreds or
thousands of companies, so one bad company can't sink you. Look for yearly fees (expense ratio) under 0.2%.

**3. Invest on a schedule (dollar-cost averaging).** A fixed amount every week or month means you buy more
shares when prices are low and fewer when high, and it removes the stress of guessing the "right" day.
The **Backtest** tab lets you see how this would have worked historically.

**4. Choose a mix you can stick with.** More stocks = higher long-term growth but deeper drops (-30% to -50%
happens). More bonds = smoother ride, lower growth. A common rule of thumb: the shorter your time horizon or
the more a drop would scare you, the more bonds.

**5. Rebalance about once a year.** The **Plans** tab shows when your mix has drifted from its targets.

**6. Mind fees and taxes.** Use a low-fee broker, and check whether your country offers tax-advantaged
accounts for long-term investing.

**7. Don't react to every headline.** Daily moves are mostly noise. Use the daily view to stay on plan,
not to trade more.

**Daily / weekly / monthly / yearly routine with this app**
- *Daily*: glance at **Today**; if a contribution is due, buy at your broker and press "I bought these".
- *Weekly*: read the weekly report; check the **Signals** for anything unusual.
- *Monthly*: review your portfolio's month and your contributions.
- *Yearly*: run the **Balance check** in Plans and adjust your contribution amount as your income grows.

Tickers use Yahoo Finance symbols: US stocks/ETFs like `VOO`, crypto like `BTC-USD`, European listings with
a suffix like `VWCE.DE` (Germany) or `VUSA.L` (London).
"""
    )
    st.caption(DISCLAIMER)
