# InvestTrack

A personal investing app, set up for investors in **Armenia** by default. Your money is split into
three sections by when you may need it, and the **Action** screen tells you exactly what to do now:
what to buy, how much, and where. It works on your **PC and iPhone with the same data**, and reminds
you on Telegram when something is due.

> **Educational tool, not financial advice.** Signals describe what prices have done, not what they will do.
> Every investment can lose money.

## The three sections

| Section | For money you need | Suggested funds | Why |
|---|---|---|---|
| 🍞 **Short term: daily bread** | within about a year | SGOV (US Treasury bills) | very low risk, pays interest monthly, sell any day. An AMD bank deposit also works |
| 💵 **Medium term: monthly income** | in about 1 to 5 years | BND (bonds) + SCHD (dividend stocks) | pays you regularly: BND monthly, SCHD quarterly |
| 🌳 **Long term: growth** | in 5 years or more | VT (whole-world stocks) | grows the most over time, but can fall 30-50% along the way |

The sections are time horizons, not schedules. How often you add money (daily, weekly or monthly) is a
separate choice for each plan; monthly keeps fees lowest. **Plans → Quick start** splits a monthly budget
in AMD across the three sections (20% / 30% / 50% by default) and creates a plan for each.

## What each tab does

| Tab | What you get |
|---|---|
| **Action** | "Where your money goes": the funds for each section and what's due. Then your to-do list, grouped by section: exact orders to place ("buy 0.2725 SGOV ≈ 9,900 AMD"), money to set aside when a purchase is too small for the fee, optional extras during dips, the monthly balance check, weekly/monthly check-ins. Press **Done** (enter what you actually paid) or **Skip** |
| **Dashboard** | Market mood, portfolio value in AMD and USD, gains by day, week, month, year |
| **Plans** | Quick start, then one tab per section with its plans: amount, schedule, funds, "save, then buy", one order per purchase, extra during dips |
| **Portfolio** | Your investments **by section** (value, gain, share vs target), every holding, value over time; import trades from your broker's CSV export or record them by hand |
| **Markets / Analyze** | Major markets, the USD/AMD rate, any ticker with trend, RSI and plain-language signals |
| **Backtest** | "What if I had invested X every month for 10 years?", including your broker's fees |
| **Practice trading** | Learn short-term trading with **pretend money**: a 5-minute chart of today's session, a simple rule (opening range breakout or moving-average crossover) that shows when it would buy and sell, a pretend account with a daily loss limit and an honest record after fees, a test of the rule on the last 60 days compared with just holding the fund, and trading fees of brokers available in Armenia |
| **Reports** | Daily, weekly, monthly and yearly reports |
| **Settings** | Country and currency, broker and fees, funds you can buy, **reminders**, **use on PC and iPhone** |

A yellow 🔔 bar at the top of every page lists what's due right now.

## Use it on your PC and iPhone (same data, free)

The app runs online on Streamlit Community Cloud, and your data is kept in a **private** GitHub
repository that only you can see. Open the same link on your PC and your iPhone.

1. **A private place for your data.** On GitHub, create a repository named `investtrack-data`, choose
   **Private**, tick **Add a README file**.
2. **A key that can only open that repository.** GitHub → your picture → Settings → Developer settings →
   Personal access tokens → **Fine-grained tokens** → Generate new token. Repository access: *Only select
   repositories* → `investtrack-data`. Repository permissions → **Contents: Read and write**. Copy the token.
3. **Put the app online.** At [share.streamlit.io](https://share.streamlit.io), sign in with GitHub →
   **Create app** → repository `ggemax55/Social`, branch `claude/investment-tracker-app`, file `app.py` →
   **Advanced settings** → paste into **Secrets**:

   ```toml
   APP_PASSWORD = "choose-a-password"

   [github_store]
   token = "github_pat_paste-your-token-here"
   repo = "ggemax55/investtrack-data"
   path = "portfolio.json"
   ```

   Press **Deploy**. You get a link like `https://something.streamlit.app`.
4. **Open it on both devices.** Bookmark it on your PC. On your iPhone, open it in Safari → Share →
   **Add to Home Screen** (it gets an app icon). The password keeps others out.
5. **Bring your existing data.** In the PC version press **Download my data**; in the online app press
   **Restore from a backup**.

The free online version sleeps after about 12 hours without visits and wakes when you open it. If two
devices change data at the same moment, the second one is told and reloads instead of overwriting.
To make the PC version use the same online data, save the secrets above as `.streamlit/secrets.toml`
in the app folder (this file is never uploaded).

## Reminders on your phone

- **Telegram** (works on iPhone and PC): in Telegram open **@BotFather**, send `/newbot`, copy the token.
  In the app: Settings → Reminders → paste the token → Save → open your bot and press **Start** →
  **Connect my Telegram** → **Send test message**.
- **Every morning even when the app is closed**: on GitHub open `ggemax55/Social` → Settings → Secrets and
  variables → Actions → add `INVESTAPP_GITHUB_TOKEN` (the same token as above) and `INVESTAPP_GITHUB_REPO`
  (`ggemax55/investtrack-data`). The *Daily reminders* workflow then sends the day's to-do list at 9:00
  Yerevan time. GitHub pauses scheduled workflows in public repositories after 60 days without activity in the
  repository; if reminders stop, open the **Actions** tab → *Daily reminders* → **Enable workflow**.
- **Phone calendar**: Settings → Reminders → **Add my plan dates to my calendar** downloads an `.ics` file;
  open it on your iPhone and choose **Add All**.

## Run it on your PC only (no online setup)

1. Install [Python 3.10 or newer](https://www.python.org/downloads/) (on Windows tick **"Add python.exe to PATH"**).
2. Download this project: green **Code** button → **Download ZIP**, unzip it.
3. Double-click **`start-windows.bat`** (Windows; if it says "Windows protected your PC", click
   **More info → Run anyway**) or **`start-mac.command`** (Mac; the first time right-click → **Open**).
4. The app opens at http://localhost:8501. Keep the black window open while you use it.

The PC version updates itself from GitHub each time you start it and never touches your data in `data/`.
The online version updates automatically.

## Brokers

You don't need an account to start. Compare brokers in **Settings** (published fees as found in 2026;
confirm on their sites):

| Broker | Fee per US order | Fractional shares |
|---|---|---|
| Interactive Brokers (direct account) | $0.0035/share, min $0.35, max 1% | yes |
| Interactive Brokers via Acba bank | $0.01/share, min $4 | ask Acba |
| Freedom Broker Armenia | 0.12%, min $1.20 | ask Freedom |

The app doesn't log in to your broker and never places orders: it tells you what to buy, you buy it in
the broker's app and press Done. Trades can also be imported from a broker's CSV export. A read-only
automatic connection to Interactive Brokers can be added once you have an account there.

## About day trading

The Practice trading tab exists so you can find out with pretend money whether short-term trading works
for you, before risking real money. When this was built (October 2026), both rules **lost money over the
previous 60 days after fees** on SPY, QQQ, Nvidia and Tesla, while simply holding those funds gained.
Studies of real day traders find that the large majority lose money. The app never places trades.

## How purchases are sized

- Each section's plans look only at that section's holdings, and new money goes to the funds below
  target. With **one order per purchase**, all of it goes to the single fund furthest below target.
- **Save, then buy**: when a purchase would be too small for the broker's minimum fee (fee over 1%),
  the app asks you to set money aside and tells you to buy once it adds up.
- Cash that doesn't buy a whole share (if your broker requires whole shares) carries over.
- Missed contributions from the last month are combined into one task; you can catch up or skip them.
  Contributions that fall on a weekend move to Monday.

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest
python -m investapp.report daily      # text report
python -m investapp.notify --dry-run  # the reminder message
```

```
app.py                  Streamlit user interface
launch.py               starter used by start-windows.bat / start-mac.command
investapp/buckets.py    the three sections and their suggested funds
investapp/actions.py    the Action center: tasks from plans, fees, dips and routines
investapp/storage.py    data: local file or private GitHub repository (sync between devices)
investapp/notify.py     Telegram reminders (used by .github/workflows/reminders.yml)
investapp/practice.py   practice trading: 5-minute data, rules, 60-day test, pretend account
investapp/ics.py        calendar file with plan dates
investapp/fees.py       broker fee profiles
investapp/money.py      USD / AMD conversion and formatting
investapp/planner.py    plans, schedules, contribution allocation, rebalancing, projections
investapp/portfolio.py  trades, holdings (also by section), valuation, performance
investapp/imports.py    CSV trade import
investapp/updater.py    self-update of the PC version
investapp/indicators.py returns, moving averages, RSI, volatility, drawdowns, signals
investapp/backtest.py   historical simulation with fees, money-weighted return (XIRR)
investapp/report.py     daily / weekly / monthly / yearly reports
investapp/data.py       price downloads (yfinance)
tests/                  unit tests and offline end-to-end tests of the app
```
