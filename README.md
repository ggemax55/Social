# InvestTrack

A personal app for investing on a schedule (**daily, weekly and monthly**), set up for investors in
**Armenia** by default. Its **Action** screen tells you exactly what to do today: what to buy, how much,
or how much to set aside. Everything you finish is recorded in your portfolio.

It downloads live prices and the USD/AMD rate from Yahoo Finance, plans every purchase around your
broker's fees, and explains the market in plain language.

> **Educational tool, not financial advice.** Signals describe what prices have done, not what they will do.
> Every investment can lose money.

## What it does

| Tab | What you get |
|---|---|
| **Action** | Your to-do list for right now: "Buy 2 VT for the Monthly plan", "Set aside 1,000 AMD for the Daily plan", optional extra purchases during market dips, the monthly balance check, and weekly/monthly check-ins. Press **Done** after doing each one (enter what you actually paid), or **Skip**. Also shows signals and what's coming up this week |
| **Dashboard** | Market mood, portfolio value in AMD and USD, gains by day, week, month, year |
| **Plans** | Three tracks (**Daily**, **Weekly**, **Monthly**) with a **Quick start** that splits a monthly budget in AMD across them. Plans can save up before buying so fees stay low, use one order per purchase, and buy a little extra during dips |
| **Portfolio** | Holdings, gains, allocation, value over time; **import trades from your broker's CSV export**, or record trades by hand |
| **Markets** | Major markets, the USD/AMD rate, the funds your broker offers, your watchlist |
| **Analyze** | Any ticker: price with 50/200-day averages, RSI, trend, plain-language signals |
| **Backtest** | "What if I had invested X every week for 10 years?", including your broker's fees; compares daily vs weekly vs monthly |
| **Reports** | Daily, weekly, monthly and yearly reports |
| **Settings** | Country and currency, your broker and its fees (presets for brokers available in Armenia), the list of funds you can buy, app version |
| **Learn** | A short beginner's guide, notes on investing from Armenia, and a daily/weekly/monthly routine |

### Brokers

You don't need an account to start: plan with the app first, compare brokers in **Settings**, then open one.
Presets (published fees as found in 2026; always confirm on the broker's site):

| Broker | Fee per US order | Fractional shares |
|---|---|---|
| Interactive Brokers (direct account) | $0.0035/share, min $0.35, max 1% | yes |
| Interactive Brokers via Acba bank | $0.01/share, min $4 | ask Acba |
| Freedom Broker Armenia | 0.12%, min $1.20 | ask Freedom |
| Other broker | enter its fees | your choice |

The app doesn't log in to your broker and never places orders. It tells you what to buy, and you buy it
in your broker's app. To bring in trades from the broker, use **Portfolio → Import trades (CSV)**.
A direct read-only connection to Interactive Brokers (its Flex reports) can be added once you have an account.

## Run it on your computer

1. Install [Python 3.10 or newer](https://www.python.org/downloads/). On Windows, tick
   **"Add python.exe to PATH"** on the first screen of the installer.
2. Download this project: on GitHub press the green **Code** button, then **Download ZIP**, and unzip it.
3. Open the unzipped folder and double-click:
   - Windows: **`start-windows.bat`** (if Windows shows "Windows protected your PC", click
     **More info**, then **Run anyway**)
   - Mac: **`start-mac.command`** (the first time, right-click it and choose **Open**)
4. The first start takes a few minutes while it installs what it needs. Then the app opens in your
   web browser at http://localhost:8501. Keep the black window open while you use the app; close it to stop.

Next time, just double-click the same file again.

### Updates are automatic

Every time you start the app with `start-windows.bat` or `start-mac.command`, it checks GitHub
(`ggemax55/Social`, default branch) for a newer version, downloads it, and restarts. Your data in the
`data` folder is never touched. You don't need to download anything again. When the app is open and an
update appears, the sidebar tells you; close the window and start it again to install it.

Your data (trades, plans, tasks) is saved in `data/portfolio.json` on your computer. It is listed in
`.gitignore`, so it is never uploaded. Use **Download my data** in the sidebar for backups.

### With a terminal

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open http://localhost:8501. To keep the data file somewhere else, set `INVESTAPP_DATA` to its path.

## How the plans decide what to buy

- Each contribution goes to the funds that are below their target weight, so the mix stays balanced
  without selling. With **one order per purchase**, all of it goes to the single fund furthest below
  target, so you pay one fee instead of several.
- **Save, then buy**: when a contribution is too small for the broker's minimum fee, the app asks you to
  set the money aside and tells you to buy once it adds up (fees stay at or under 1% of each purchase).
- If your broker only sells whole shares, cash that doesn't buy a full share carries over to next time.
- Missed contributions from the last month are combined into one task; you can catch up or skip them.
- Contributions that fall on a weekend move to Monday. Daily plans contribute on weekdays.

## Reports from the command line

```bash
python -m investapp.report daily     # or weekly, monthly, yearly
python -m investapp.report weekly --save   # also writes reports/<date>-weekly.md
```

## Limitations

- Yahoo Finance data is free and unofficial; it can be delayed or briefly unavailable.
- Gains use the average-cost method; taxes are not modeled. Ask an Armenian tax adviser about
  dividends and gains from foreign funds.
- Fee presets are estimates; set your broker's exact fees in **Settings**.

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest
```

```
app.py                  Streamlit user interface
launch.py               starter used by start-windows.bat / start-mac.command
investapp/actions.py    the Action center: tasks from plans, fees, dips and routines
investapp/fees.py       broker fee profiles
investapp/money.py      USD / AMD conversion and formatting
investapp/planner.py    plans, schedules, contribution allocation, rebalancing, projections
investapp/portfolio.py  trades, holdings, valuation, period performance
investapp/imports.py    CSV trade import
investapp/updater.py    self-update from GitHub
investapp/indicators.py returns, moving averages, RSI, volatility, drawdowns, signals
investapp/backtest.py   historical simulation with fees, money-weighted return (XIRR)
investapp/report.py     daily / weekly / monthly / yearly reports and CLI
investapp/data.py       price downloads (yfinance)
investapp/storage.py    JSON save / load
tests/                  unit tests and offline end-to-end tests of the app
```
