# InvestTrack

A personal app for tracking the markets and investing on a schedule: **daily, weekly, monthly or yearly**.

It downloads live prices from Yahoo Finance, analyzes the market in plain language, tracks your portfolio,
and tells you exactly what to buy each time a planned contribution is due.

> **Educational tool, not financial advice.** Signals describe what prices have done, not what they will do.
> Every investment can lose money.

## What it does

| Tab | What you get |
|---|---|
| **Today** | Market mood, your portfolio's value and today's gain, which plans are due today and what to buy, signals worth noticing |
| **Markets** | Major markets (S&P 500, Nasdaq, small caps, international, bonds, gold, bitcoin, VIX) and your watchlist: returns over 1D / 1W / 1M / 3M / YTD / 1Y, trend, RSI, distance from the 1-year high; growth comparison chart |
| **Portfolio** | Holdings, cost basis, gains (realized and unrealized), allocation, value vs money invested over time; record trades by money amount or by shares |
| **Plans** | Recurring plans (e.g. 100 every month into 60% VTI / 30% VXUS / 10% BND). Shows the next dates and a buy list that sends new money to whatever is below target. One click records the purchases. Yearly balance check and a growth projection |
| **Analyze** | Any ticker: price with 50/200-day averages, RSI, trend, plain-language signals |
| **Backtest** | "What if I had invested X every week since 2016?" Compares daily vs weekly vs monthly vs yearly vs lump sum on real history |
| **Reports** | Daily, weekly, monthly and yearly reports you can read or download |
| **Learn** | A short beginner's guide and a suggested daily / weekly / monthly / yearly routine |

## Run it on your computer

**The easy way (no typing):**

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

**With a terminal:**

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open http://localhost:8501 in your browser.

Your data (trades, plans, watchlist) is saved in `data/portfolio.json`. That file is listed in `.gitignore`,
so it is never uploaded to GitHub. Use **Download my data** in the sidebar for backups. To keep the file
somewhere else, set the `INVESTAPP_DATA` environment variable to its path.

## Use it on your phone

Deploy it for free on [Streamlit Community Cloud](https://streamlit.io/cloud): sign in with GitHub,
choose **New app**, pick this repository and `app.py`, and press **Deploy**. You get a link that works on
any phone.

Two things to know about the cloud version:
- Its storage resets when the app restarts, so press **Download my data** after making changes and
  **Restore from a backup** when you come back.
- Apps can be public. Restrict who can view it in the app's sharing settings before entering real data.

## Reports from the command line

```bash
python -m investapp.report daily     # or weekly, monthly, yearly
python -m investapp.report weekly --save   # also writes reports/<date>-weekly.md
```

To get one automatically every weekday evening on macOS or Linux, add a line like this with `crontab -e`:

```
30 17 * * 1-5 cd /path/to/this/folder && python3 -m investapp.report daily --save
```

## How the plans decide what to buy

Each contribution is split so your portfolio moves toward its target weights: money goes only to the
assets that are below target, in proportion to how far below they are. With an empty portfolio this is
simply amount x weight. You never have to sell to stay balanced, though the yearly **balance check**
shows the trades that would restore the targets exactly. If your broker only sells whole shares, tick
that option and the leftover cash is spent on whichever asset is furthest below target.

Contributions that fall on a weekend move to the next Monday. Daily plans contribute on weekdays.

## Tickers

Use Yahoo Finance symbols: `VOO`, `AAPL`, `BTC-USD`, `VWCE.DE` (Frankfurt), `VUSA.L` (London).
Prices are shown in each asset's own currency, so keep one portfolio in one currency.

## Limitations

- Yahoo Finance data is free and unofficial; it can be delayed or briefly unavailable.
- Gains use the average-cost method; taxes are not modeled.
- If two plans share a ticker, both plans see the same holding.
- Projections use a constant return; real markets swing up and down.

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Code layout:

```
app.py                  Streamlit user interface
investapp/data.py       price downloads (yfinance)
investapp/indicators.py returns, moving averages, RSI, volatility, drawdowns, signals
investapp/portfolio.py  trades, holdings, valuation, period performance
investapp/planner.py    schedules, contribution allocation, rebalancing, projections
investapp/backtest.py   historical simulation and money-weighted return (XIRR)
investapp/report.py     daily / weekly / monthly / yearly reports and CLI
investapp/storage.py    JSON save / load
tests/                  unit tests and an offline smoke test of the whole app
```
