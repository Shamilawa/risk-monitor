# Trend Following — MT5

Native MQL5 port of the Pine Script v6 indicator "Pro: Flow & Value Pullback". Standalone —
does not touch `mt5_bridge/`.

| File | Role |
|---|---|
| `TrendFollowing_EA.mq5` | Expert Advisor — signal logic, order placement, trades |
| `TrendFollowing_Visual.mq5` | Indicator — EMA/zone/ATR-band plots **and** Entry/SL/TP signal drawings, computed independently so it works with or without the EA attached |

Both files detect signals the same way and both can draw Entry/SL/TP on the chart. Run either
alone, or both together — they share an object-name prefix, so a signal drawn by one is
recognized by the other and never drawn twice (see "Running both at once" below).

## Install

1. Copy `TrendFollowing_EA.mq5` → `<MT5 Data Folder>\MQL5\Experts\`
2. Copy `TrendFollowing_Visual.mq5` → `<MT5 Data Folder>\MQL5\Indicators\`
3. Compile both in MetaEditor (F7).
4. Attach the indicator to the chart to see EMAs/zone/bands and every historical signal
   (Entry/SL/TP lines + arrow + `FLOW`/`VALUE` label), same as Pine draws on load.
5. Attach the EA and enable AlgoTrading if you also want it to trade the signals live.
6. Keep `InpFastLen` / `InpSlowLen` / `InpTrendLen` / `InpSlopeBars` / `InpUseDoubleHA` /
   `InpEntryBufferPips` / `InpTPRMultiple` / `InpAtrPeriodBands` / `InpAtrMultBands` identical
   between the two — they must agree or the drawn levels and the EA's actual orders diverge.

### Running both at once

Both files use the same `TF_` object-name prefix on purpose. Each signal's object name is
derived only from its bar time and tag (`FLOW`/`VALUE`), so if the indicator draws a signal
first and the EA later computes the identical signal (or vice versa), the second one finds the
name already taken and skips drawing — one set of objects, not two. Turn off one side entirely
with `InpShowSignals=false` (indicator) or `InpShowChartObjects=false` (EA) if you only ever want
one of them drawing, but it's not required for correctness anymore.

**Previously this produced visibly garbled/doubled text labels** (two independent "FLOW" labels
drawn a pixel or two apart) when both files were attached with default settings. Two things were
wrong, both now fixed:
1. The two files used *different* prefixes (`TF_` vs `TFV_`), so a real duplicate never
   collided — it just drew twice. Fixed by sharing one prefix.
2. The EA's re-arm lock (`can_take_long`/`can_take_short`) used to persist across ticks starting
   from `true`/`true` at attach time, evolving only forward — it never replayed history. The
   indicator, by contrast, always recomputes across its whole loaded chart. If the EA was
   attached mid-trend, its lock state could genuinely disagree with the indicator's, causing it
   to fire on a *different* bar than the indicator — two near-but-not-exactly-overlapping labels,
   which is what produced the garbled look specifically (not a clean stacked duplicate).
   Fixed: `ProcessClosedBar()` now replays the full lock state across up to `HISTORY_BARS`
   (3000) bars on every call, the same way the indicator's `OnCalculate()` does, so the two
   files agree on exactly which bar fires which signal. This also unified the EA's ATR
   implementation with the indicator's (previously two separately-hand-written Wilder-RMA
   routines that weren't guaranteed bit-identical) — see the Fidelity audit below.

## Defaults

| Input | Default | Pine original |
|---|---|---|
| Fast / Slow / Trend EMA | 21 / 50 / 200 | same |
| EMA slope lookback | 5 | same (hardcoded) |
| Double HA confirmation | on | same |
| Entry tolerance | 5 pips | same |
| **ATR Period (Bands)** | **14** | 3 |
| **ATR Band Scale Factor** | **3.0** | 2.5 |
| **Take Profit** | **single target, 1.8R** | two targets, 0.7R / 1.75R |
| Risk per signal | $100 (EA only — the indicator doesn't size positions) | same |

The ATR change is a real behavioural change, not cosmetic: ATR(14)×3 is a much wider, much
steadier stop than ATR(3)×2.5, which reacted to the last few candles. Downstream effects —
position size shrinks for the same `$100` risk (stop distance is the divisor), and TP moves
further out since it's an R-multiple of that stop. Expect fewer stop-outs but each win pays out
less often at full size than the old TP1-heavy split did. Worth a Strategy Tester comparison of
settings before committing.

The single-TP change is also behavioural, not cosmetic: the EA no longer splits a signal into
two half-size legs — it opens **one position** at full risk-sized lot, one SL, one TP at 1.8R.
Simpler fills, one ticket to manage, but no partial-profit-taking at a closer target anymore.

## Removed, per request

Volume filter, UTC session filter, JSON/CSV alert payloads, ATR data table, and all webhook
plumbing (`mt5_symbol`, `use_json_alert`, `show_csv_label`) are gone from both files — the
inputs, the condition terms, and the code. In the Pine source both filters defaulted to off
(`use_vol = false`, `use_session = false`), so removing them matches the script's default
behaviour exactly.

## Fidelity audit vs. the Pine source

Verified equivalent, condition by condition:

| Pine | MQL5 |
|---|---|
| `a1/a2_stack_bull/bear` | `stackBull` / `stackBear` — the source declares `a1_*` and `a2_*` with *identical* conditions, so they collapse to one pair |
| `ta.change(ema50, 5) > 0` etc. | `emaSlow[1] - emaSlow[1+InpSlopeBars] > 0` |
| `touch_a1/a2_bull/bear` | same comparisons, same strict/non-strict operators (`low < ema50` vs `low <= ema21`) |
| `haClose/haOpen` recursion | `CalcHeikinAshi()` — same recursive form, replayed across the full `HISTORY_BARS` window each cycle |
| `use_double_ha` | `InpUseDoubleHA` |
| `can_take_long/short` re-arm | local `canTakeLong`/`canTakeShort`, replayed from scratch across history every bar close (see "Running both at once" for why it's not a persisted flag), re-armed **before** signal evaluation, matching Pine's top-to-bottom execution order |
| `barstate.isconfirmed` | new-bar detection in `OnTick()`; signal logic walks every confirmed bar in the window, trades only on the newest one |
| `entry_buffer_pips * mintick * 10` | `InpEntryBufferPips * PipSize()` |
| `close > (ema21+buffer) ? ema21+buffer : close` | `isMarket` / limit-price branch |
| `sl_level := lowerATRBand_b` | `close[1] - ATR*mult` |
| `tp1 = entry + risk*0.7`, `tp2 = ...*1.75` (two targets) | `InpTPRMultiple` (single target, default 1.8R — changed on request) |
| `line.new(...)` ×4, `label.new(...)` | `DrawSignal()` — 3 dashed lines (entry/SL/TP) 2 bars forward + arrow + text + tooltip, in **both** files |
| dashboard table (Trend / Status) | `Comment()` panel (EA only) |
| `plot()` ×5, `fill()` | `TrendFollowing_Visual.mq5` |

Fidelity issues found and fixed during the port:

- **ATR smoothing.** MT5's built-in `iATR` uses a *simple* moving average of true range; Pine's
  `ta.atr` uses Wilder's RMA. Different numbers, and the stop is built on it.
  `CalcWilderATR()` implements the RMA form by hand so the stop lands where Pine puts it. Now
  computed identically (same algorithm, ascending arrays) in both the EA and the indicator.
- **Signal lock.** Pine sets `can_take_long := false` unconditionally once a signal fires. The
  first draft only locked when `risk > 0`; now unconditional.
- **Lot rounding.** A rounded-down lot below the broker minimum now skips the trade with a log
  line rather than silently trading at min lot (which would exceed `InpRiskUsd`).
- **EA re-arm state not replaying history.** Found after a user report of garbled/doubled signal
  labels on chart — see "Running both at once" above for the full root-cause writeup. The EA's
  lock state now replays from scratch every bar close instead of persisting a flag seeded
  `true` at attach time, so it can no longer disagree with the indicator about which bar fires.

Carried over from the source unchanged, including its quirks:

- `atr = ta.atr(14)`, `atr_mult`, and `rr_ratio` are declared in the Pine script but never used
  by any signal or SL/TP calculation. Not ported.
- `trend_bull` / `trend_bear` (price vs EMA200) only feed the dashboard cell — they are **not**
  entry filters. The real trend gate is the EMA stack order plus the 5-bar slope filter. Kept
  as-is; flag it if that was actually an oversight in the original and you want it enforced.
- `trade_active` is set but never read. Not ported.

## Necessary MT5-side additions (EA only)

An indicator only draws; an EA has to manage real orders. These have no Pine counterpart:

- **Position sizing** from `InpRiskUsd` via tick value/size, floored to the broker's lot step —
  one position per signal, full size, single SL, single TP at `InpTPRMultiple`.
- **Pending-order expiry** (`InpPendingExpiryBars`, default 10 bars) — a time-based backstop for
  a limit order that just sits there because price went nowhere.
- **Pending-order invalidation** (`InpInvalidateRMultiple`, default 1.4R, checked every tick via
  `CheckPendingInvalidation()`) — cancels a working limit order once price runs `1.4R` past the
  entry *in the trade's favor* without ever pulling back to fill it. That means the move already
  happened without us: the anticipated pullback never came, so filling late would mean chasing
  at a far worse risk:reward than the signal was built on. This is a distinct condition from
  the time-based expiry above and usually fires first on a fast run-away move — set to `0` to
  disable it and rely on `InpPendingExpiryBars` alone.
- **Duplicate guards** — won't stack a second position or pending order in the same direction
  while one is already open/working.
- Magic number (`990211`), slippage, order comments (`TF_*`), retcode logging.

## Notes

- EMAs come from MT5's `iMA`, which seeds its recursion differently from Pine (first close vs.
  SMA) but computes over the chart's full history — after a few hundred bars the difference is
  numerically irrelevant. Give the chart plenty of loaded history before trusting the EMA200.
- Market entries fill at the next tick's price, not the signal bar's close, so realised R can
  drift slightly from the drawn levels. Normal for any bar-close strategy.
- `InpMaxSignalsOnChart` (default 500, matching Pine's `max_lines_count=500`) prunes the oldest
  drawings so long backtests/history don't accumulate unbounded chart objects.
- Both files now recompute and (if enabled) draw every historical signal in their replay window
  on every bar close (like Pine does on load/replay) — the EA additionally *trades* only the
  newest confirmed bar; every earlier bar in the window is lock-state/drawing only, never a
  live order. `HISTORY_BARS` (3000, in the EA) caps how far back that replay goes.
- Chart drawings survive recompiles and parameter changes; they're cleared when the owning
  program (EA or indicator) is removed from the chart.
- Any IDE squiggles on these files from a generic C/C++ language server (`'input' is a reserved
  keyword`, undefined variables inside `#property` strings) are false positives — MQL5 is only
  validated by MetaEditor's compiler.
- **Not yet compiled or backtested.** Run both through MetaEditor, then the EA through Strategy
  Tester, before any demo or live use.
