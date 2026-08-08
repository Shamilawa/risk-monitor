# Trading Journal — Market Analysis, Metric Design & Business Plan

Status: **research / pre-implementation**. No code has been written for this yet.
Scope: a per-instance trading journal reached by clicking a card on Portfolio Management.

---

## 0. Executive summary

Every mainstream trading journal (TradeZella, TraderSync, Edgewonk, Tradervue, TradesViz)
is built for a **discretionary, single-account, manual-import trader**. Their feature
gravity is screenshots, emotion tags, playbooks and AI coaching. That is not our user.

Our user is an **algo trader running several MT5 terminals at once**, some of them prop
firm accounts, wired together by a trade copier. For that user three questions dominate,
and no existing tool answers any of them well:

1. *Which of my EAs is actually making money, on which symbol, at which hour?*
   (needs per-magic-number segmentation — only FX Blue does this, and badly)
2. *Is my current drawdown normal for this strategy, or is the edge dead?*
   (needs R-multiples + Monte Carlo, which no consumer journal computes)
3. *Is my copier faithfully reproducing the master, and what is the divergence costing me?*
   (**nobody** offers this — it is only possible because we own both sides of the copy)

The strategic recommendation is therefore **not** to clone TradeZella. It is to build a
narrow, dense, algo-first journal that leans on three assets we already own and they
never will: multi-instance topology, copier provider/consumer pairing, and prop-firm
account context.

**Critical precondition:** four data-integrity defects in `sync_trading_log()` currently
corrupt trade history (see §7). Partial closes are counted multiple times, trade direction
is stored inverted, and day bucketing mixes timezones. Any journal built on top of this
today would produce confidently wrong numbers. Phase 0 fixes these before a single chart
is drawn.

---

## 1. Competitive landscape

| Tool | Price | Built for | Strengths | Gaps that matter to us |
|---|---|---|---|---|
| **TradeZella** | ~$30–35/mo | US equities/futures day traders | Best-in-class UX, calendar view, MAE/MFE, tag reports, 50+ reports, backtesting, trade replay, "Zella Score" | No per-EA/magic segmentation. No multi-account roll-up. MT5 support is an import, not a live link. Nothing algo-statistical (no SQN, no Monte Carlo). |
| **TraderSync** | $30–80/mo | Same, plus mobile | Mobile app, AI "coaching", broad broker list | Same gaps. Expensive at the tier where the good analytics live. |
| **Edgewonk** | $197/yr | Discretionary, psychology-focused | Deepest *behavioural* analytics, cheap, "Tiltmeter" | Psychology tooling is dead weight for an EA. Narrow broker import. No replay/backtest. |
| **Tradervue** | Free tier / $30 | Legacy equities | Only meaningful free tier | Stagnant. No AI, no replay, no backtest, no mobile. |
| **TradesViz** | ~$18/mo | Data-heavy traders | Genuinely 100s of metrics, MT5 supported | Overwhelming UI — the "wall of charts" failure mode we explicitly want to avoid. |
| **Myfxbook** | Free | Forex retail | Free MT5 auto-sync, verified track record, social proof | Analytics are shallow and dated. Ad-heavy. Data leaves your machine. |
| **FX Blue** | Free | Forex/MT4-MT5 | **Splits by magic number**, symbol, hour — the closest to our need | Ugly, non-interactive HTML reports. No R-multiples, no risk-adjusted ratios, no journaling. |
| **MT5 built-in report** | Free | — | Always available, authoritative | Per-terminal only, no cross-account view, no tagging, static HTML. |

### What the market tells us

- **Table stakes** (users will notice their absence): equity curve, calendar heatmap,
  win rate, profit factor, net P&L, filterable trade log, per-symbol breakdown.
- **Differentiators available cheaply to us**: per-magic (EA) segmentation, R-multiple
  distribution, cost drag (swap+commission), hold-time asymmetry.
- **Unique to us, uncopyable by them**: copier divergence analysis, cross-instance
  portfolio correlation, prop-firm rule proximity, live socket-fed metrics.
- **Deliberately skipped**: screenshots, emotion sliders, playbook templates, AI chat
  coach, social feed. See §5.4 for the reasoning.

---

## 2. Who this is for, and what they actually stare at

Three personas, in priority order.

### P1 — Algo operator (primary; this is you)
Runs N EAs across M terminals. Does not care how a single trade "felt". Cares about
whether a *distribution* has shifted. Checks in daily for 60 seconds, deeply on Sundays.

Ranked information needs:
1. Net P&L and current drawdown from peak — *am I in trouble right now?*
2. Equity curve **with an underwater plot** — *is this dip within normal range?*
3. Per-EA table — *which magic number is bleeding?*
4. Expectancy in R and R-distribution — *is the edge intact or am I riding outliers?*
5. Hold-time asymmetry (avg winner vs avg loser duration) — *has an EA stopped honouring stops?*
6. Hour/weekday grid — *is the edge concentrated in a session that just changed regime?*

### P2 — Prop-firm account holder (same person, different hat)
The account has hard rules and a payout on the line. Needs a **rule-proximity panel**,
not analytics: distance to daily loss limit, distance to max drawdown, profit-target
progress, and the consistency rule (largest single day as % of total profit — most firms
cap this at 30–45%). This is the single highest-anxiety screen in the product and it
should be answerable in under two seconds.

### P3 — Copier operator (same person, third hat)
Runs a PROVIDER and one or more CONSUMERs. Needs to know whether the mirror is faithful:
fill delay, price slippage per trade, trades the consumer missed entirely, and the
cumulative P&L gap versus the master. `blocked_copier_actions` already records refusals —
that table is half of this report and is currently invisible in the UI.

---

## 3. Metric catalogue

Every metric below is listed with its exact definition and its data status against our
current `trading_log` schema. This is the contract for "calculations must be perfect".

### 3.1 Core P&L (computable today)

| Metric | Formula | Notes |
|---|---|---|
| Net P&L | `Σ profit` | `profit` already = `raw_profit + commission + swap`. Never re-add them. |
| Gross profit / loss | `Σ profit where >0` / `Σ profit where <0` | |
| Profit factor | `gross_profit / |gross_loss|` | If `gross_loss == 0`: display `∞`, **not** a sentinel. Current code returns `99.9` — misleading. |
| Win rate | `wins / (wins + losses)` | Three buckets: win `>0`, loss `<0`, **scratch** `==0`. Scratches excluded from the denominator, reported separately. |
| Avg win / avg loss | mean of each bucket | |
| Payoff ratio | `avg_win / |avg_loss|` | |
| Breakeven win rate | `1 / (1 + payoff)` | Show next to actual win rate — instantly says whether the edge is real. |
| Expectancy ($) | `net_pnl / trade_count` | Identical to the textbook `(W×avgW) − (L×avgL)`; use the simple form to avoid rounding drift. |
| Largest win / loss | max / min | |
| Max consecutive wins / losses | streak walk in close-time order | Already implemented for losses. |
| Cost drag | `(|Σ commission| + |Σ swap|) / gross_profit` | **Differentiator.** We store commission and swap separately; most journals silently fold them in. Swap is what quietly kills carry-holding EAs. |

### 3.2 R-multiple family (computable today — this is our anchor)

`sl_at_open` and `entry_risk_usd` are already captured at sync time from the entry
order's history. That means the denominator for R already exists, which most journals
have to ask the user to type in manually.

| Metric | Formula | Notes |
|---|---|---|
| R-multiple per trade | `profit / entry_risk_usd` | Only defined where `entry_risk_usd > 0`. |
| **R-coverage** | `% of trades with entry_risk_usd > 0` | **Must be displayed beside every R metric.** If only 60% of trades had a stop, an "expectancy 0.3R" headline is a lie. This honesty is a feature. |
| Expectancy (R) | `mean(R)` | The single most important number for a systematic trader. |
| R-distribution | histogram, bins of 0.5R | The chart that reveals whether P&L comes from an edge or from three lucky outliers. |
| SQN (Van Tharp) | `√N × mean(R) / stdev(R)` | Suppress below N=30; the estimator is unstable. Cap N at 100 for the comparison variant. |
| Trades without SL | `count(sl_at_open == 0)` | Already computed. Promote to a first-class risk flag. |

### 3.3 Drawdown family

| Metric | Formula | Data status |
|---|---|---|
| Realized (balance) max DD | high-water-mark walk over closed trades | ✅ implemented (`realized_dd_pct`) |
| Equity max DD (incl. floating) | HWM walk over an equity time series | ⚠️ `risk_snapshots` only holds a daily peak, sampled by the poller. Needs a proper equity time series table. |
| **Current DD from peak** | `(peak − now) / peak` | ⚠️ needs live equity + stored peak. **Highest-value single number on the page.** |
| Drawdown duration | bars/days spent below the prior peak | derived from the same series |
| Underwater plot | `DD%` over time, shares x-axis with equity | The equity curve alone hides depth and duration; overlaying it is the strongest single UX upgrade. |
| Recovery factor | `net_profit / max_dd_$` | |
| Ulcer index | `√(mean(DD_i²))` | Better "pain" measure than max DD, which is a single unlucky sample. |

### 3.4 Risk-adjusted ratios (need a daily equity series)

All of these consume a **daily return series**, which requires the equity time series in
§3.3. `daily_equity_baseline` gets us partway.

| Metric | Formula | Guidance |
|---|---|---|
| Sharpe (annualised) | `mean(r_d) / stdev(r_d) × √252` | Use time-weighted returns so deposits/withdrawals don't distort. Assume rf = 0 and say so in the tooltip. |
| Sortino | as Sharpe, denominator = downside deviation (MAR = 0) | |
| Calmar / MAR | `annualised return / max DD` | |
| Volatility | `stdev(r_d) × √252` | |

Suppress all four below ~60 trading days of data with an explicit "insufficient history"
state. A Sharpe computed on three weeks is noise dressed as authority.

### 3.5 Segmentation (computable today — highest value per unit of effort)

`magic` and `comment` are already stored, so per-EA analysis needs **no new capture**.
Every one of these is a sortable table, with columns: trades, net P&L, expectancy R,
profit factor, win %, max DD.

- **By magic number (EA)** — the flagship view for P1. Add an EA alias map so `12345`
  reads as "London Breakout v3".
- By symbol
- By direction (long / short) — *blocked until the direction bug in §7.2 is fixed*
- By hour of day and by weekday — *blocked until the timezone bug in §7.3 is fixed*
- By duration bucket (<1m, 1–5m, 5–60m, 1–24h, >1d)
- By volume/lot bucket — catches position-sizing drift

### 3.6 Needs new data capture

| Metric | What's missing | How to get it |
|---|---|---|
| Entry / exit price | not stored | trivial — already on the deal objects during sync |
| TP at open | not stored | `history_orders_get`, same call already used for SL |
| **MAE / MFE** | not stored | **Reconstruct from M1 bars** via `mt5.copy_rates_range(symbol, M1, open_time, close_time)`. Works *retroactively over all existing history* — no live sampling needed, no waiting months to accumulate data. This is a genuinely strong approach and cheaper than what the competition does. |
| Edge ratio | depends on MAE/MFE | `mean(MFE/R) / mean(MAE/R)` |
| Slippage | requested vs filled price | provider/consumer deal comparison |
| Monte Carlo DD envelope | nothing — pure computation | shuffle the trade sequence 10k times, report the 50th/95th/99th percentile of max DD. Answers "is this drawdown normal?" Cheap for ≤5k trades. |

---

## 4. The moat: three reports nobody else can build

### 4.1 Copier divergence report
Pair a PROVIDER instance with its CONSUMERs, match trades on `(symbol, magic, open time
window)`, and report per trade: fill delay (ms), price slippage, volume ratio vs the
configured risk mode, and P&L gap. Roll up to: cumulative divergence cost, missed-trade
count, and a join against `blocked_copier_actions` to explain *why* each miss happened.
Nothing on the market does this because nothing on the market owns both sides of the copy.

### 4.2 Prop-firm rule tracker
For `account_type = 'PROPFIRM'`: daily loss used vs limit, max DD used vs limit (static or
trailing), profit target progress, days traded, and the **consistency rule** (largest day
as % of total profit). Rendered as proximity bars, not charts. Sourced from existing
`alert_drawdown_limit` / `alert_profit_ceiling_usd` plus new per-firm rule fields.

### 4.3 Cross-instance portfolio view
Correlation matrix of daily returns between instances, plus a combined equity curve. If
three EAs are 0.9-correlated you are running one strategy at 3× size and don't know it.
This is a Portfolio-page addition rather than a per-instance journal feature, but it falls
directly out of the same daily-return series.

---

## 5. UX / information architecture

### 5.1 Entry point
Portfolio card becomes clickable → route `/portfolio/:id`. Keep the terminal design
system (`components/ui/Terminal.tsx`) — Panel, MetricTile, StatusTag, Meter, SectionLabel
already cover ~80% of what this page needs. Breadcrumb back to `/portfolio`, plus
prev/next instance arrows so you can flip between accounts without going back.

### 5.2 The three-tier rule

Design each screen so it answers a question at one of three depths:

- **5 seconds** — "am I OK?" → the verdict bar
- **30 seconds** — "where is the problem?" → curve + underwater + EA table
- **5 minutes** — "what exactly happened?" → filtered trade log + per-trade detail

Anything that serves none of these three does not ship.

### 5.3 Page layout (top to bottom)

```
┌─ HEADER ────────────────────────────────────────────────────────────┐
│ ‹ PORTFOLIO   ACCOUNT-NAME  [PROPFIRM] [MASTER] [LOCKED]   ‹ prev ›  │
│ Equity $12,480.22   Balance $12,150.00   Floating +$330.22          │
├─ VERDICT BAR ── period: [7D|30D|90D|YTD|ALL]  ──────────────────────┤
│  NET P&L  │ EXPECT R │  PF   │ MAX DD │ CUR DD │  SQN  │ TRADES     │
│  +$2,340  │  0.34R   │ 1.62  │  8.4%  │  2.1%  │  2.8  │  184       │
│                                          (R-coverage 78%)           │
├─ PROP RULES (only when account_type = PROPFIRM) ────────────────────┤
│  Daily loss   [████░░░░░░] 40% of $500                              │
│  Max DD       [██░░░░░░░░] 21% of $1,000                            │
│  Target       [███████░░░] 68% of $1,000                            │
│  Consistency  38% ⚠ (cap 45%)                                       │
├─ EQUITY + UNDERWATER ───────────────────────────────────────────────┤
│  [equity curve, shared x-axis]                     $ | R  balance|eq│
│  [underwater / drawdown %, inverted, filled red]                    │
├─ R-DISTRIBUTION ─────────────┬─ STREAKS & HOLD TIME ────────────────┤
│  histogram, 0.5R bins        │  win/loss streak bars                │
│  outlier flag if top 3       │  avg hold: win 42m / loss 3h 10m ⚠   │
├─ BREAKDOWNS (tabbed tables) ────────────────────────────────────────┤
│  [BY EA] [SYMBOL] [HOUR] [WEEKDAY] [DURATION] [DIRECTION]           │
│  sortable; cols: trades, net, expR, PF, win%, maxDD                 │
├─ CALENDAR ──────────────────────────────────────────────────────────┤
│  month grid, daily P&L, colour-scaled; click a day → filters log    │
├─ TRADE LOG ─────────────────────────────────────────────────────────┤
│  virtualized, filtered by every control above                       │
│  row expands → entry/exit, SL/TP, R, MAE/MFE, costs, notes          │
└─────────────────────────────────────────────────────────────────────┘
```

### 5.4 Explicit non-goals, and why

Ruling things out is as important as the feature list. The user brief was clear: no chart
or metric for its own sake.

| Not building | Why |
|---|---|
| Screenshot upload / chart replay | An EA has no chart to screenshot. Huge storage and UI cost, zero algo value. |
| Emotion / mood / tilt tags | Edgewonk's core feature. Meaningless for a program. |
| Playbook templates, AI coach | Discretionary hand-holding. Our user writes the strategy in code. |
| Social feed / public track record | Myfxbook's business, not ours. Data stays local — that's a selling point. |
| 50-report library | TradesViz's wall-of-charts failure mode. Twelve views that get used beat fifty that don't. |
| Manual trade entry | Everything syncs from MT5. Manual entry invites data corruption. |

### 5.5 Interaction principles

- **One period selector governs the whole page.** No per-panel date pickers.
- **Every filter is global and cross-linked.** Click an EA row → whole page rescopes to
  that magic number. Click a calendar day → same. A breadcrumb chip stack shows active
  filters with one-click removal.
- **Every metric has a tooltip with its formula and sample size.** Non-negotiable for
  trust; it is also how we stay honest about assumptions (rf = 0, scratch handling).
- **Insufficient-data states are explicit.** "SQN — needs 30 trades (have 12)" beats a
  number that looks authoritative and isn't.
- **The page must not stutter.** Metrics come from REST + TanStack Query, cached, computed
  server-side in SQL/Python. Only equity/floating come off the socket. Do not push a
  0.5s-cadence socket feed into a page holding a 5,000-row table.

---

## 6. Business plan

### 6.1 Problem
Trade history is currently visible only as raw rows and a 90-day card summary. There is no
way to answer "which EA is losing money and when" without exporting to Excel. Meanwhile
the account-level risk data the app already collects — SL at open, entry risk in dollars,
magic numbers, copier topology — is captured and then thrown away.

### 6.2 Value hypothesis
Making per-EA expectancy and drawdown-normality visible turns the app from a *monitor*
(tells you what happened) into a *decision tool* (tells you which EA to switch off). The
decision it enables — cutting a dead strategy two weeks earlier — is worth more than the
entire feature costs to build.

### 6.3 Positioning
> A local-first, algo-first trading journal for multi-account MT5 operators.
> Everything TradeZella measures, plus the three things it structurally cannot:
> per-EA segmentation, copier fidelity, and prop-firm rule proximity.

### 6.4 Phasing

**Phase 0 — Data integrity (blocking, ~1–2 days)**
Fix the four defects in §7. Add the annotations table. Nothing else starts until trade
history is trustworthy; every downstream number inherits these errors.

**Phase 1 — MVP journal — ✅ shipped**
Route `/portfolio/:id` (cards are clickable), verdict bar, equity + underwater chart,
breakdown tables, calendar, filterable trade log with expandable detail and annotations.
Ships §3.1, §3.2 (minus the R-histogram, which stays in Phase 2) and §3.5.

Backend — all DB-only, no `mt5_lock`, under the `TRADING JOURNAL` banner in `app_server.py`:

| Endpoint | Returns |
|---|---|
| `GET /api/journal/<id>/summary` | every headline metric; `?balance=` anchors drawdown to real account size |
| `GET /api/journal/<id>/equity` | per-trade equity curve + underwater series, shared x-axis |
| `GET /api/journal/<id>/breakdown?by=` | magic / symbol / direction / hour / weekday / duration |
| `GET /api/journal/<id>/calendar` | daily P&L by journal day, plus best/worst day |
| `GET /api/journal/<id>/trades` | paginated, filtered trade log with annotations joined |
| `GET /api/journal/<id>/filters` | distinct symbols and magics, to populate the controls |
| `POST /api/journal/<id>/annotation` | upsert tags/grade/note on `(instance_id, position_id)` |

The metric maths lives in pure functions (`_journal_metrics`, `_drawdown_series`,
`_streaks`, `_stdev`) that take rows and return numbers — no DB, no MT5 — which is what
makes `test_journal_metrics.py` able to check them against hand-computed cases.

Frontend — `frontend/src/components/journal/`: `Journal.tsx` (shell, one filter object for
the whole page), `VerdictBar`, `EquityUnderwater`, `Breakdowns`, `CalendarHeatmap`,
`TradeLog`, `format.ts`.

**Phase 1 verification**
- `test_journal_metrics.py` — 45 hand-computed assertions covering scratch handling,
  payoff/breakeven, undefined profit factor, R coverage, SQN suppression below n=30,
  streaks, drawdown against a real balance, cost drag, hold-time asymmetry, duration
  buckets. All pass.
- Cross-panel reconciliation on live data: under one filter (XAUUSD.sml SHORT, 365d),
  summary net P&L, trade-log sum, breakdown sum and calendar sum all agree to the cent,
  and the equity series has exactly one point per trade.
- Outcome filters are mutually exclusive and exhaustive (50W + 34L + 0S = 84, P&L sums to
  the unfiltered total).
- Clicking a calendar day narrows the log to exactly that day and matches the cell's value.
- `npm run build` clean; `eslint` clean on every file touched (the 10 remaining repo lint
  errors are all pre-existing in the unrouted `Review.tsx`).

### Bug found and fixed during Phase 1
**SPA deep links 404'd in production.** `flask_app` was constructed with
`static_url_path='/'`, which makes Flask register a `/<path:filename>` static rule that
outranks the `serve_react` catch-all. Every client-side route — `/portfolio`, `/copier`,
and now `/portfolio/:id` — returned 404 when loaded directly or refreshed; only in-app
navigation hid it. Static is now scoped to `/assets` (where Vite's hashed bundles actually
live) so everything else falls through to `serve_react`. Confirmed: all four routes now
serve `index.html`.

**Phase 2 — Algo depth — ✅ shipped**

| Endpoint | Returns |
|---|---|
| `GET /api/journal/<id>/distribution` | R-multiple histogram, profit-concentration stats, edge ratio |
| `GET /api/journal/<id>/riskadjusted` | Sharpe / Sortino / Calmar / Ulcer + the daily return series |
| `GET /api/journal/<id>/montecarlo` | permutation drawdown envelope + bootstrap forward outlook |
| `POST /api/journal/<id>/backfill_mae` | starts the M1-bar MAE/MFE reconstruction |
| `GET /api/journal/<id>/backfill_status` | progress + pending/filled counts |

Frontend: MAE/MFE rows and a backfill control in the trade log.

> **Panels removed on request (2026-08-08).** The `RDistribution`, `RiskAdjusted` and
> `MonteCarlo` panels were built, verified, then taken off the journal page — they did not
> earn their space against the §5.4 rule that nothing ships unless it answers a question at
> one of the three depths. The **endpoints, metric functions and their tests are all
> retained**, so re-adding a panel is UI-only work. MAE/MFE backfill stays wired into the
> trade log, and excursions still show in the per-trade detail; only the edge-ratio *display*
> went with `RDistribution`.

**Design decisions worth recording**

- *Returns are realized-balance, not equity.* There is no historical equity record — only
  closed trades — so daily returns are reconstructed from trade P&L anchored to live
  balance. Floating swings on open positions are therefore not in the volatility. Every
  response ships a `basis` string saying so.
- *Deposits are captured and subtracted.* New `balance_operations` table records every
  non-trade balance change. Without it a $5,000 deposit reads as a 40% daily return and
  every ratio built on top is garbage. Schema version bumped to 3 to backfill it.
- *Annualisation is measured, not assumed.* `periods_per_year` comes from the observed
  trading-day density rather than a hard-coded 252, so a crypto account that trades seven
  days a week isn't annualised on an equities calendar. Weekends are excluded unless they
  contain activity — a data test, not a calendar test.
- *Estimators are suppressed below sample.* Sharpe/Sortino/Calmar need 60 trading days,
  Monte Carlo needs 20 trades, SQN needs 30 R-trades. Below that the UI shows the reason
  and a progress meter, never a number. Descriptive figures (Ulcer, max DD) still show,
  because they are measurements rather than estimates.
- *Two simulations, because there are two questions.* Permutation (same trades, reshuffled)
  isolates **sequencing risk** — final P&L is invariant under it by construction, which is
  exactly why a "final P&L percentile" from a permutation is meaningless. A separate
  bootstrap with replacement answers the **forward** question. Both are seeded on
  `(instance, trade count)` so an envelope doesn't jitter on every reload.
- *MAE/MFE from M1 bars, not live sampling.* `copy_rates_range` works retroactively over
  all history, where a live poller can only ever catch positions it happens to sample and
  misses fast trades entirely. The backfill takes `mt5_lock` **per trade**, not for the
  whole job, so a multi-minute run never stalls the poller or the live risk alerts.
- *NULL vs 0 is load-bearing.* `mae_usd IS NULL` means "not backfilled"; `0.0` means "never
  went against you". The UI renders them differently.
- *Return is time-weighted (TWR).* Daily returns are chained geometrically rather than
  taking `(end − funding) / start`. See the bug below for why this is not optional.

### Bug found and fixed during Phase 2 testing
**Total Return read `n/a` while every other metric computed normally.** Surfaced by the
live UI immediately after the v3 resync captured the account's `Initial Deposit` of
$10,000 on 2026-05-29.

The window's reconstructed opening balance is legitimately **0** — every dollar in the
account arrived as a deposit *inside* the window — and the old `(end − funding) / start`
form divided by that zero. Two fixes:

1. **Time-weighted return.** Daily returns are now chained geometrically. Each day is
   already measured against the balance it actually started with, so a deposit moves the
   base without ever appearing as performance. This is the standard treatment for accounts
   with cash flows and it is well-defined regardless of the opening balance. It also
   compounds correctly: +10% then −10% is −1%, not 0%.
2. **Funding is applied before the day's trading**, not after. Capital deposited on day D
   is available to trade that day. The old ordering left a zero opening balance on the
   funding date and silently dropped it from the series — visible as 52 observations where
   there should have been 53.

Verified on live data: total return now reports **25.478%**, and an independent
recomputation of the TWR straight from the returned daily series matches to three decimals.
`opening_balance`, `closing_balance` and `funding_total` are now returned so the figure can
be audited rather than trusted. Regression tests cover the funded-inside-window case and
the compounding property.

**Phase 2 verification**
- `test_journal_metrics.py` now covers 90 assertions. New ones: downside deviation, Ulcer
  index, suppression below sample, Sharpe undefined on zero dispersion, deposits excluded
  from return, R-histogram bin coverage and concentration shares, Monte Carlo percentile
  monotonicity and seed reproducibility, bootstrap producing a genuine spread, edge ratio
  excluding un-backfilled trades.
- Live-data run: 70 R-trades at 83.3% coverage; profit concentration top-1 7.0%, top-3
  17.6% (an edge spread across many trades, not a few outliers); actual max drawdown
  12.64% sits at the **95.7th percentile** of reshuffled orderings; bootstrap median
  +$2,594 against an actual +$2,548 — a good sanity signal.
- Sharpe correctly suppressed: 53 trading days against a 60-day minimum.
- Phase 1 still reconciles to the cent across summary / log / calendar / breakdown.
- v2 → v3 migration on a copy of the live DB: no rows lost, idempotent, forces exactly one
  full resync.

**Phase 3 — Moat (~5–7 days)**
Copier divergence report, prop-firm rule tracker, strategy comparison overlay,
auto-generated weekly review pushed through the existing Telegram channel.

### 6.5 Success criteria
- Every metric reconciles **exactly** against the MT5 built-in report for the same period
  (this is the acceptance test — build a reconciliation script in Phase 0).
- Page interactive in <1s on ~10k trades.
- The Sunday review that currently means exporting CSVs happens entirely in-app.
- At least one EA gets switched off or resized as a direct result of a journal view within
  the first month.

### 6.6 Risks
| Risk | Mitigation |
|---|---|
| Metrics that silently disagree with MT5 | Reconciliation script as a Phase 0 deliverable, run per instance |
| `sync_trading_log()` DELETE-all wipes user annotations | Annotations in a separate table keyed on `(instance_id, ticket)`, never on `trading_log.id` |
| Full-history resync gets slow as the log grows | Move to incremental sync in Phase 0 (already worth doing on its own) |
| Feature creep toward TradeZella parity | §5.4 non-goals list is binding |
| Broker vs local time confusion | One canonical time column, decided in Phase 0, used everywhere |

---

## 7. Data-integrity defects (Phase 0 — **implemented**)

Found while reading `sync_trading_log()` and `_query_daily_pnl()`. Two of the five were
initially written up more severely than the code warranted; the corrected assessments are
below, based on running the migration and unit-testing the replacement logic.

### 7.1 Partial closes are counted multiple times — *severity: critical, latent* ✅ fixed
The old sync iterated every OUT deal and inserted a row for each, while assigning each row
the **whole position's** summed profit/commission/swap. A position closed in three partials
produced three rows each carrying the full position P&L — a 3× overstatement, which
`UNIQUE(instance_id, ticket)` could never catch because it keys on the *deal* ticket.

**Latent, not active:** a fingerprint scan of the live `trades.db` (84 rows, net $2,547.77)
found no multi-counted positions — nothing traded so far has scaled out, so displayed
numbers were not actually wrong. The defect would have fired the first time an EA took
partial profits.

Fixed by aggregating **one row per `position_id`** in `_build_position_row()`. Verified
against a synthetic 3-part scale-out with a true net of $95.00: the old path produces
$285.00 across three rows, the new path $95.00 across one.

### 7.2 Trade direction is stored inverted — *severity: low (not user-visible)* ✅ fixed
The stored `type` is the **closing** deal's type, so a long position persists as `type = 1`
(sell). The original write-up called this a display bug; it wasn't — the single reader
(`/api/performance`) already inverted it at read time and showed the correct side. The real
problems were that the compensation was undocumented and load-bearing, and that no
queryable direction column existed for a long/short breakdown.

Fixed by storing an explicit `direction` column taken from the **entry** deal, with the old
inversion kept as a documented fallback for rows written before the column existed.

### 7.3 Day bucketing is inconsistent between backend and frontend — *severity: medium* ✅ fixed
The original write-up claimed `local_time` was machine-local and therefore mis-bucketed by
`utcfromtimestamp()`. That was wrong. `time_offset = time.time() - tick.time` cancels the
broker's UTC offset, so `local_time` is in fact a true **UTC** epoch and the backend was
bucketing consistently.

The genuine defect is a *disagreement*: the backend buckets days in UTC while the frontend
calls `new Date(local_time * 1000).toLocaleDateString()` and buckets in the **browser's**
timezone ([Review.tsx:421](../mt5_bridge/frontend/src/components/Review.tsx#L421),
[:464](../mt5_bridge/frontend/src/components/Review.tsx#L464),
[:547](../mt5_bridge/frontend/src/components/Review.tsx#L547)). The same trade can therefore
land on different dates in different views. Neither frame matches the broker's day, which is
what the daily candle and a prop firm's daily-loss reset actually use.

Fixed by giving the app one definition of a trading day, via `_journal_day_config()` and a
single `_journal_date_str()` helper used by daily P&L and review dates, exposed through
`GET/POST /api/journal/config`. Three anchors:

| Anchor | Day starts at | Use when |
|---|---|---|
| **`MACHINE`** (default, chosen) | 00:00 on this computer's clock | you want the journal to match the clock you actually read |
| `UTC` | 00:00 UTC | you want days independent of where the machine is |
| `FIXED` | 00:00 UTC + `journal_day_offset_min` | you want the broker's server day |

`MACHINE` is a *mode*, not a stored offset, because a fixed number of minutes cannot track
DST — it would be an hour out for half the year anywhere that observes it.
`datetime.fromtimestamp()` applies the rules that were in force at each instant, so historic
trades keep the offset they were actually traded under.

The useful property: `MACHINE` is precisely the frame the frontend already renders in via
`new Date(ts * 1000)`. Verified across all 84 stored trades — **0 mismatches** between the
backend's bucket and the date JavaScript produces — so backend and UI now agree by
construction and `Review.tsx` needs no change. Confirmed the anchor genuinely bites: a
timestamp at 02:00 local (20:30 UTC the previous day) resolves to 2026-03-16 under `MACHINE`
and 2026-03-15 under `UTC`.

**Deliberately left alone:** the poller writes `risk_snapshots.date` and
`daily_equity_baseline.date` in UTC, and those still drive the live daily-drawdown reset.
Moving them to machine time would change *risk behaviour*, not display — and for a prop
account the daily-loss window is the broker's day, not this machine's. Range queries against
`risk_snapshots` therefore stay in UTC to match their own writer. Unifying the two is tied
to open question 2 (prop-firm rules) and belongs in Phase 3, not here.

### 7.4 Full-history DELETE + reinsert on every sync — *severity: medium* ✅ fixed
The old sync wiped an instance's entire log every 15 minutes and re-fetched from the year
2000, issuing a `history_deals_get(position=…)` call per deal. Replaced with an incremental
sync bookmarked per instance in `trading_log_sync_state`, with a 3-day overlap window to
absorb positions that span the boundary and late broker swap/commission adjustments.
`schema_version` forces exactly one full rebuild on an existing DB so pre-aggregation rows
get replaced rather than merged into. `/api/sync_log` still forces a full rebuild.

### 7.5 `profit_factor` sentinel — *severity: low* ✅ fixed
Returned `99.9` when there were no losing trades, which renders as a real (and excellent)
number. Now returns `null`; the Portfolio UI already renders that as `n/a`.

### 7.7 Trailing-window queries ended hours in the past — *severity: high* ✅ fixed
Found while implementing the day anchor, not in the original review. Both `_query_daily_pnl()`
and `api_portfolio_overview()` built their window with `datetime.utcnow().timestamp()`.
`.timestamp()` interprets a **naive** datetime as *local* time, but `utcnow()` returns naive
UTC — so on this UTC+5:30 machine the expression produced an epoch **19,800 seconds (5h30m)
in the past**, measured directly.

Every metric on the Portfolio page — trade count, win rate, profit factor, realized P&L,
drawdown, the daily P&L series — was therefore computed over a window that ended 5½ hours
ago, silently excluding anything closed since. Worse on any machine further from UTC, and
invisible unless you happened to close a trade and compare.

Fixed by using `int(time.time())` (a true UTC epoch, matching what `trading_log` stores) for
both bounds.

### 7.8 Regression caught during verification — *introduced and fixed in Phase 0*
Worth recording: the first version of the day-anchor change called `_journal_day_config(c)`
*after* the trade `SELECT` in `_query_daily_pnl()`, on the same cursor. The config helper
runs its own query, which discarded the pending trade rows — every day silently read $0.00
while the totals elsewhere on the page stayed correct. Caught by asserting that
`daily_pnl`'s active days match `review_dates` (0/19 agreement before the fix, 19/19 after),
which is exactly the kind of cross-view check the reconciliation approach exists to force.

### 7.6 Also fixed while in here
`/api/performance` excluded every trade with exactly zero profit from its metrics — a
workaround for the multi-counting in 7.1 that also silently discarded genuine scratch
trades. Now every closed position counts, with breakeven trades reported separately as
`scratch_trades` and excluded from the win-rate denominator rather than counted as losses.

### Phase 0 verification performed
- `init_db()` run against a copy of the live `trades.db`: migrates clean, is idempotent on
  a second run, and preserves all 84 existing rows.
- `app_server` imports cleanly against the real `MetaTrader5` 5.0.5509 package.
- `_build_position_row()` unit-tested for scale-out aggregation, short-side direction, and
  correct exclusion of a still-open position.
- Changed routes exercised against a DB copy: `/api/journal/config` (incl. rejecting an
  out-of-range offset), `/api/performance`, `/api/review_dates`, `/api/portfolio_overview`.
- `reconcile_journal.py` added — the standing acceptance test, recomputing closed-position
  count, net P&L, gross profit/loss, commission and swap directly from MT5 deal history via
  an independent code path and diffing against `trading_log`. **Not yet run against a live
  terminal** — that requires the MT5 instances to be running.

---

## 8. Proposed schema changes (for review, not yet applied)

Following the existing inline-migration convention (`ALTER TABLE … ADD COLUMN` wrapped in
`try/except sqlite3.OperationalError`), and remembering that several routes read the
schema back positionally with cascading fallbacks — **all fallback tiers must be updated
together**.

```sql
-- trading_log additions
ALTER TABLE trading_log ADD COLUMN position_id   INTEGER;   -- group partial closes
ALTER TABLE trading_log ADD COLUMN direction     INTEGER;   -- 0=long 1=short, from ENTRY deal
ALTER TABLE trading_log ADD COLUMN entry_price   REAL DEFAULT 0;
ALTER TABLE trading_log ADD COLUMN exit_price    REAL DEFAULT 0;
ALTER TABLE trading_log ADD COLUMN tp_at_open    REAL DEFAULT 0;
ALTER TABLE trading_log ADD COLUMN mae_usd       REAL;      -- NULL = not yet backfilled
ALTER TABLE trading_log ADD COLUMN mfe_usd       REAL;

-- Annotations survive the DELETE-all resync: keyed on (instance_id, ticket), never on id
CREATE TABLE IF NOT EXISTS trade_annotations (
    instance_id INTEGER,
    ticket      INTEGER,
    tags        TEXT DEFAULT '',      -- comma-separated
    grade       TEXT DEFAULT '',      -- A/B/C/D
    note        TEXT DEFAULT '',
    updated_at  INTEGER,
    PRIMARY KEY (instance_id, ticket)
);

-- Daily equity series: feeds Sharpe/Sortino/Calmar and the true equity-based drawdown
CREATE TABLE IF NOT EXISTS equity_series (
    instance_id  INTEGER,
    date         TEXT,
    open_equity  REAL,
    close_equity REAL,
    peak_equity  REAL,
    low_equity   REAL,
    deposits     REAL DEFAULT 0,      -- for time-weighted returns
    PRIMARY KEY (instance_id, date)
);

-- Friendly names for magic numbers, so the EA table is readable
CREATE TABLE IF NOT EXISTS strategy_aliases (
    instance_id INTEGER,
    magic       INTEGER,
    alias       TEXT,
    PRIMARY KEY (instance_id, magic)
);
```

New endpoints (all DB-only, no `mt5_lock`, so they are safe from request handlers):
`/api/journal/<id>/summary`, `/trades`, `/breakdown?by=magic|symbol|hour|weekday`,
`/calendar`, `/equity_curve`, `/distribution`, and `POST /api/journal/annotation`.

---

## 9. Open questions before implementation

1. ~~**Timezone**~~ — **decided: machine local time.** Implemented as
   `journal_day_anchor = 'MACHINE'` (the default), with `UTC` and `FIXED` available. See §7.3.
2. **Prop firm rules**: which firms, and are the limits static or trailing? This determines
   how many fields the rule tracker needs.
3. **Partial closes**: should scale-outs appear as one trade or several in the log? (One
   row with an expandable exit breakdown is the recommendation.)
4. **MAE/MFE backfill cost**: fetching M1 bars for every historic trade is a one-off but
   potentially long job. Background task with progress, or on-demand per trade?
5. **Scope of "journal"**: per-instance only, or also a combined all-accounts journal?
   (Recommendation: per-instance for Phase 1; combined view is a Phase 3 Portfolio-page
   feature.)

---

## Sources

Market and metric research drawn from:
[TradeZella — best trading journal software](https://www.tradezella.com/blog/best-trading-journal-software) ·
[TradeZella vs TraderSync](https://tradingjournal.com/blog/tradezella-vs-tradersync) ·
[TradingSFX journal comparison](https://tradingsfx.com/blog/best-trading-journals) ·
[Advanced trading metrics: Sharpe, Sortino, Calmar, SQN](https://tradingwyckoff.com/en/algorithmic-trading/advanced-trading-metrics/) ·
[Algorithmic trading metrics guide](https://tradingwyckoff.com/en/algorithmic-trading/algorithmic-trading-metrics/) ·
[R-multiple, expectancy, MAE/MFE](https://forexmechanics.com/traders-workshop/journal-metrics/) ·
[Trading dashboard KPIs that matter](https://www.tradezella.com/blog/trading-dashboard) ·
[Building a trading performance dashboard](https://journalplus.co/learn/guides/trading-performance-dashboard-guide/) ·
[TradesViz for MetaTrader 5](https://www.tradesviz.com/brokers/MetaTrader5) ·
[Using MyFXBook and FX Blue](https://www.fortraders.com/blog/use-myfxbook-fx-blue-pro)
