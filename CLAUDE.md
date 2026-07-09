# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Windows-only desktop trading dashboard that connects to one or more local **MetaTrader 5 (MT5)** terminal installations. It polls each terminal for account/position data over the `MetaTrader5` Python package, streams risk metrics to a React UI over Socket.IO, and can copy trades between MT5 instances (provider → consumer) via a ZeroMQ router.

All real work lives under `mt5_bridge/`. The repo root only has two legacy design docs (`how_this_works.md`, `installation_guide.md`) describing an older TradingView-webhook workflow — that workflow (`app.py`, `/webhook` route, `indicator.pine`) no longer exists in the code; treat those docs as historical/aspirational, not a description of `app_server.py`. `fix_tabs.py` and `fix_ui_freezes.py` at the root are one-off patch scripts that were run once against the legacy jQuery frontend (`mt5_bridge/static/*.js`, `mt5_bridge/templates/*.html`) — that frontend is dead code, fully superseded by the React app.

## Architecture

**Backend**: `mt5_bridge/app_server.py` (a single ~1800-line Flask + Flask-SocketIO app). No blueprints/modules — all routes, DB access, and background threads live in this one file. Run with `python app_server.py` (or `run.bat`), listens on port 5000.

Four background threads started in `main()`:
- `poller_thread` — every 0.5s, reads all rows from the `instances` table, connects to each MT5 terminal by its `path` (concurrently via a `ThreadPoolExecutor`), computes equity/drawdown/positions, and emits it as Socket.IO event `risk_data`. Also emits `mt5_status`, evaluates per-instance drawdown/profit-target alerts and connection-loss alerts, and sends Telegram notifications (daily/weekly/monthly summaries too).
- `zmq_router_thread` — binds a ZeroMQ `PULL` socket on `tcp://127.0.0.1:5555` and a `PUB` socket on `tcp://127.0.0.1:5556`; blindly re-broadcasts every message it receives (provider → all consumers).
- `copier_manager_thread` — every 3s, diffs the `instances` rows where `copier_role IN ('PROVIDER','CONSUMER')` against currently-running worker subprocesses, and starts/kills `python mt5_worker.py --id ... --role ...` child processes as needed to match DB state.
- (plus the Flask/SocketIO server itself, run via `socketio.run(...)`)

**Copier subprocess**: `mt5_bridge/mt5_worker.py` runs standalone per MT5 instance, in one of two roles (chosen by DB config, spawned by `copier_manager_thread`):
- `PROVIDER`: polls `mt5.history_deals_get` in a tight loop (10ms sleep) for that instance's terminal, detects new/closed/modified trades, and PUSHes them to the router on port 5555.
- `CONSUMER`: SUBs to the router on port 5556, applies the instance's risk mode (`FIXED` lot / volume `MULTIPLIER` / dynamic `USD` risk sizing) and optional symbol mapping, then places/closes/modifies the mirrored trade on its own terminal. Keeps a provider-ticket→local-ticket map persisted to `mt5_bridge/ticket_map_<id>.json`.

Multiple MT5 terminals on one Windows machine are addressed purely by their install `path` (each instance in the DB has its own `path`) — `mt5.initialize(path=...)` is how the backend targets a specific terminal.

**Frontend**: `mt5_bridge/frontend/` is a Vite + React 19 + TypeScript app (React Router, Zustand store, TanStack Query, Chart.js, `socket.io-client`). Key files:
- `src/hooks/useSocket.ts` — the only place the frontend talks to the backend in real time; wires `mt5_status`/`risk_data`/`log` Socket.IO events into the Zustand store (`src/store/useStore.ts`). Disconnects the socket when the tab is hidden and reconnects on visibility, to avoid UI freezes.
- `src/App.tsx` — three routes: `/` (`Dashboard.tsx`), `/copier` (`Copier.tsx`), `/review` (`Review.tsx`).
- Everything else (instance CRUD, tracker table, backtester, review dates, etc.) goes through plain REST calls to `/api/*`, proxied to `127.0.0.1:5000` in dev (`vite.config.ts`).

In production, Flask serves the built frontend directly: `flask_app` is constructed with `static_folder`/`template_folder` pointing at `mt5_bridge/frontend/dist`, and the catch-all route `serve_react` falls back to `index.html` for client-side routing. **You must run `npm run build` in `frontend/` for backend-served UI changes to show up** — `python app_server.py` does not rebuild the frontend itself.

**Persistence**: a single SQLite file, `mt5_bridge/trades.db` (checked into git — be careful with schema-breaking changes and don't assume a clean/empty DB). Main tables: `instances` (one row per MT5 terminal, holds path, risk settings, copier role/config, alert thresholds), `trading_log` (closed-trade history, unique on `(instance_id, ticket)`), `global_settings`, plus backtester tables. Schema migrations are done inline in `init_db()` via repeated `ALTER TABLE ... ADD COLUMN` wrapped in `try/except sqlite3.OperationalError: pass` — when adding a column, follow this same pattern rather than assuming a fresh schema, and note that several routes read the schema back with cascading `try/except` fallbacks for older column sets (e.g. `api_instances`, `poller_thread`) — update all fallback tiers together or you'll get column-count mismatches at runtime, not at import time.

## Commands

Frontend (`mt5_bridge/frontend/`):
```
npm run dev       # Vite dev server with /api proxy to 127.0.0.1:5000
npm run build     # tsc -b && vite build -> dist/ (required for backend to serve current UI)
npm run lint      # eslint .
npm run preview   # preview the production build
```

Backend (`mt5_bridge/`), from a Python environment with the MetaTrader5 package available (Windows only — the terminal(s) must already be installed and logged in, with Tools → Options → Expert Advisors → "Allow algorithmic trading" enabled):
```
python app_server.py     # or double-click run.bat; serves on http://127.0.0.1:5000, auto-opens browser
```
No `requirements.txt` exists. Dependencies to have installed: `flask`, `flask-socketio`, `MetaTrader5`, `requests`, `python-dotenv`, `pyzmq`.

There is no automated Python test suite (no pytest config, nothing in CI). The `mt5_bridge/test_*.py` scripts are standalone manual debugging scripts (e.g. `test_drift.py`, `test_history.py`) that connect to a live MT5 terminal and print diagnostics — run individually with `python test_<name>.py`, not as a suite. `test.bat` references a `test_webhook.py` that no longer exists in the repo.

## Config

`mt5_bridge/.env` (tracked in git, currently with empty values — don't fill in real tokens without confirming that's intended) holds `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`, loaded via `python-dotenv`. Telegram notifications (`send_telegram_message`) silently no-op if these aren't set.
