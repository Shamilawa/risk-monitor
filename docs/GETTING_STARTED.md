# Getting Started

A practical, start-to-finish guide to running Risk Monitor for yourself —
from a bare Windows machine to a live dashboard watching your MT5 accounts.

For how the system fits together internally, see
**[ARCHITECTURE.md](ARCHITECTURE.md)**. This guide is about *using* it.

---

## Table of contents

1. [What you'll need](#1-what-youll-need)
2. [Install](#2-install)
3. [First run](#3-first-run)
4. [Add your first MT5 instance](#4-add-your-first-mt5-instance)
5. [Set drawdown & profit alerts](#5-set-drawdown--profit-alerts)
6. [Connect Telegram](#6-connect-telegram)
7. [Set up the trade copier](#7-set-up-the-trade-copier)
8. [Prop-firm news blackout](#8-prop-firm-news-blackout)
9. [Build your trading journal](#9-build-your-trading-journal)
10. [Optional: cloud dashboard](#10-optional-cloud-dashboard)
11. [Running unattended / on a VPS](#11-running-unattended--on-a-vps)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. What you'll need

- **Windows** (the `MetaTrader5` Python package is Windows-only — this app
  cannot run on macOS/Linux, including WSL).
- **One MetaTrader 5 terminal per account** you want to monitor or copy
  trades to/from, each **installed and logged in**. Running two accounts on
  the *same* terminal install isn't supported — each instance needs its own
  install folder (MT5's own multi-terminal installer, or copy-pasting the
  install directory, both work).
- **Python 3.9+** — [python.org](https://www.python.org/downloads/), with
  **"Add Python to PATH"** checked during install.
- **Node.js 18+** — needed once, to build the dashboard.
- *(Optional)* a **Telegram account**, if you want alerts on your phone.
- *(Optional)* a **Vercel account**, if you want the cloud analytics
  dashboard in [risk-monitor-cloud](https://github.com/Shamilawa/risk-monitor-cloud).

## 2. Install

```bash
git clone https://github.com/Shamilawa/risk-monitor.git
cd risk-monitor/mt5_bridge

# Python backend
pip install -r requirements.txt

# React dashboard — built once, then served by Flask
cd frontend
npm install
npm run build
cd ..
```

That's the whole install. There's no database setup step —
`trades.db` (SQLite) is created and migrated automatically the first time
the server starts.

## 3. First run

For **every** MT5 terminal you plan to connect, do this once:

> MT5 → **Tools → Options → Expert Advisors** → check
> **"Allow algorithmic trading"** → OK.

Skip this and every trade the copier tries to place will fail with retcode
`10027 CLIENT_DISABLES_AT`.

Then start the server:

```bash
python app_server.py
# or just double-click run.bat
```

It prints `Starting Premium MT5 Bridge Server...`, then opens
`http://127.0.0.1:5000` in your browser automatically. Leave this window
open — closing it stops everything (polling, copier, alerts).

At this point the dashboard is up but empty: no instances configured yet.

## 4. Add your first MT5 instance

Go to the **Trade Copier** tab (`F2`) → **+ Add Instance**.

| Field | What to put |
|---|---|
| **Name** | Whatever you'll recognise it by — "FTMO 100k", "Personal Live", etc. |
| **Executable Path** | Click **Browse** and pick that terminal's `terminal64.exe`. Each install has its own — this is how the app tells terminals apart. |
| **Group** | Optional label for the portfolio overview (e.g. "Prop Firms", "Personal"). |
| **Account Type** | `PERSONAL` or `PROPFIRM`. Only `PROPFIRM` accounts are subject to the news blackout (§8). |

Save, and within half a second it should show up on the **Dashboard**
(`F1`) with live equity, balance and drawdown. If it doesn't, see
[Troubleshooting](#12-troubleshooting).

Repeat for every account. There's no limit built in beyond your machine's
resources — polling is concurrent across instances.

## 5. Set drawdown & profit alerts

Still in the instance's edit modal (Copier tab → click an existing
instance):

- **Alert Drawdown Levels** — comma-separated percentages (default
  `2,4,6,8,10`). You get one alert the first time equity crosses each level
  from its daily starting balance, not a spam of repeats.
- **Profit Ceiling ($)** — once closed + open profit crosses this since the
  window was last reset, the app **auto-closes every position on that
  instance** and locks it (`trade_locked`) so nothing new can open until you
  manually unlock it from the same screen. Leave at `0` to disable.
- **Profit Lock (%)** — a softer version: as profit approaches this
  percentage of equity, you get a Telegram message with an **ARM** button.
  Tap it, and the app auto-closes the instant the target is actually hit —
  you decide in the moment rather than it firing unattended by default.

None of this requires Telegram to be configured — thresholds without
Telegram just show up as red states in the UI instead of pinging your
phone.

## 6. Connect Telegram

Optional, but this is how you find out about a problem when you're not
staring at the dashboard.

1. Message **[@BotFather](https://t.me/BotFather)** on Telegram, send
   `/newbot`, follow the prompts. You'll get a **bot token**
   (`123456789:ABC-...`).
2. Message your new bot anything (so it has a chat with you), then visit
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser and
   find `"chat":{"id":...}` in the response — that's your **chat ID**.
3. Edit `mt5_bridge/.env`:
   ```
   TELEGRAM_BOT_TOKEN=123456789:ABC-your-token-here
   TELEGRAM_CHAT_ID=your-chat-id-here
   ```
4. Restart `app_server.py`.

You should immediately get *"✅ MT5 Bridge Server Started & Web UI Ready!"*.
From here you'll get drawdown/profit alerts, connection-loss alerts, daily/
weekly/monthly performance summaries, and — if you set up the copier —
incident alerts with **Retry**/**Close** buttons you can tap right from the
chat.

`.env` is checked into git with empty values by default — don't commit your
real token.

## 7. Set up the trade copier

This mirrors trades from one account (the **provider**) to any number of
others (**consumers**) in near real time. Every account involved must
already exist as an instance (§4).

1. On the account you want to copy **from**, open its edit modal → set
   **Copier Role** to **Master (ZMQ Out)**. Only one instance can be
   `PROVIDER` at a time.
2. On each account you want to copy **to**, set **Copier Role** to
   **Sub (ZMQ In)**, then choose a sizing mode:

   | Mode | What it does |
   |---|---|
   | **Fixed** | Always trades the same lot size, regardless of what the provider did. |
   | **Multiplier** | `provider_volume × your multiplier` (e.g. `0.5` = half size). |
   | **USD Risk** | Sizes the position so its stop-loss distance equals a fixed dollar amount — the same trade risks the same money on every account regardless of balance. |

3. *(Optional)* **Symbol Mapping** — if the consumer's broker uses different
   tickers (`EURUSD` vs `EURUSD.m`), map them per-instance from the same
   modal.
4. Save. Within a few seconds the **Copier Health** panel should show both
   worker processes as running.

From here, every trade the provider opens, closes, or modifies is mirrored
automatically. If a copy fails or a mirror position goes missing, you'll
get a Telegram alert — see
**[ARCHITECTURE.md § 7](ARCHITECTURE.md#7-copier-safety-net--ledger-reconciler-incidents)**
for exactly how that detection works and why it doesn't depend on the
worker processes cooperating.

## 8. Prop-firm news blackout

If an instance is marked `PROPFIRM` (§4), the copier automatically refuses
to open, close, or modify trades on it for a window around high-impact news
(fetched daily from a public economic calendar). Configure the window size
per instance:

- **News Block Before (min)** / **News Block After (min)** — minutes either
  side of the event (defaults 2/2).

If the calendar can't be fetched that day, **every** `PROPFIRM` instance is
blocked from all copying until you enter that day's events manually via the
**News** panel on the Dashboard — this fails closed on purpose, so a feed
outage can't quietly let a rule-violating trade through.

## 9. Build your trading journal

No setup needed — the journal (**Portfolio Mgmt** tab → click an instance)
builds itself from each account's MT5 deal history automatically, on a
15-minute sync cycle. It gives you equity curves, a calendar heatmap,
win/loss breakdowns by symbol/hour/weekday, risk-adjusted stats, and Monte
Carlo projections.

Two things worth doing once you have some history:

- **MAE/MFE backfill** — from a journal page, trigger the backfill to pull
  each trade's worst/best floating P&L from historical price data. This
  powers the risk-adjusted stats tab.
- **Verify it** — `python reconcile_journal.py` cross-checks the journal
  against MT5's own history through an independent code path and tells you
  if anything's drifted. Worth running after any manual DB surgery.

## 10. Optional: cloud dashboard

If you want to check performance from your phone without RDP-ing into the
machine, [risk-monitor-cloud](https://github.com/Shamilawa/risk-monitor-cloud)
is a companion Next.js app that receives a **redacted** daily snapshot (no
account paths, no copier sizing config, nothing that could move an order)
and renders a read-only analytics view.

1. Deploy that repo to Vercel and follow its own README to provision
   Postgres and get a `CLOUD_SYNC_SECRET`.
2. Add to `mt5_bridge/.env`:
   ```
   CLOUD_SYNC_URL=https://<your-project>.vercel.app/api/sync
   CLOUD_SYNC_SECRET=<the same secret>
   ```
3. Run `python cloud_sync.py` whenever you want to push (or put it on
   Windows Task Scheduler for a daily automatic sync).

## 11. Running unattended / on a VPS

The app is designed to run 24/5 on a Windows machine (a home PC left on, or
a Windows VPS/RDP box) with MT5 terminals logged in and the server started.
A couple of practicalities:

- Windows will sleep and drop your MT5 connections unless you disable sleep
  (**Settings → System → Power** → set to Never) on a machine that's meant
  to run unattended.
- For a VPS, `run.bat` can be dropped into the Windows **Startup** folder
  or wired to Task Scheduler to launch on boot/login.
- To push code updates to a VPS without touching its live `trades.db`,
  `.env`, or copier ticket-map state, use the release scripts:
  ```powershell
  # on your dev machine
  powershell -File mt5_bridge\deploy\build_release.ps1
  # copy the resulting zip to the VPS, then there:
  powershell -File mt5_bridge\deploy\apply_release.ps1
  ```
  These files are staged in a way that makes the VPS's live database and
  secrets structurally impossible to overwrite — see
  **[ARCHITECTURE.md § 19](ARCHITECTURE.md#19-build--deployment-pipeline)**.

## 12. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Instance shows offline immediately after adding it | MT5 terminal isn't logged in, or the path points at the wrong `terminal64.exe` | Open that terminal manually and confirm it's logged in; re-browse the path |
| Copier does nothing / every trade rejected | Algo trading not enabled in that terminal | Tools → Options → Expert Advisors → Allow algorithmic trading |
| Orders fail with `INVALID_VOLUME` | Consumer's symbol has a different min/max/step than the provider's | The app clamps to the symbol's actual limits automatically — if it still fails, check the symbol is enabled in that terminal's Market Watch |
| Two accounts on one terminal don't work | MT5 terminals are single-account by design | Install a separate terminal instance per account (MT5's multi-terminal installer, or copy the install folder) |
| Frontend changes don't show up | Flask serves the last `npm run build`, not source | Re-run `npm run build` in `frontend/` after any UI change |
| Telegram silent | Token/chat ID unset or wrong | Check `.env`, confirm you've messaged the bot at least once, restart the server |
| PROPFIRM instance won't trade at all | News calendar fetch failed today | Check the News panel — you'll see a `FAILED` status and can enter events manually |
| `sqlite3.OperationalError` on startup | Extremely unlikely — `init_db()` runs idempotent migrations every start | Back up `trades.db`, then check the server log for which `ALTER TABLE` failed |

Still stuck? Check the raw child logs at `mt5_bridge/logs/worker_<id>.log`
(copier subprocess output) and `mt5_bridge/logs/issues_<date>.txt` (curated
incident history) — both are plain text.
