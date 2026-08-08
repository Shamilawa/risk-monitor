"""Hand-checked cases for the journal metric functions.

These are pure-function tests -- no MT5, no DB -- so they can run anywhere:
    python test_journal_metrics.py

Every expected value here was computed by hand from the house rules in app_server.py's
TRADING JOURNAL section (win > 0, loss < 0, scratch == 0; scratches excluded from the
win-rate denominator; profit already net of costs; R only over trades that had a stop).
"""
import sys
import types

# Stub MetaTrader5 so app_server imports without a terminal present.
if 'MetaTrader5' not in sys.modules:
    try:
        import MetaTrader5  # noqa: F401
    except ImportError:
        fake = types.ModuleType('MetaTrader5')
        fake.DEAL_TYPE_BUY, fake.DEAL_TYPE_SELL = 0, 1
        fake.DEAL_ENTRY_IN, fake.DEAL_ENTRY_OUT = 0, 1
        fake.DEAL_ENTRY_INOUT, fake.DEAL_ENTRY_OUT_BY = 2, 3
        sys.modules['MetaTrader5'] = fake

from app_server import (  # noqa: E402
    _downside_deviation, _drawdown_series, _duration_bucket, _edge_ratio, _journal_metrics,
    _monte_carlo_drawdown, _r_distribution, _risk_adjusted_metrics, _streaks, _stdev,
    _ulcer_index, MIN_MC_TRADES, MIN_RETURN_DAYS,
)

FAILURES = []


def check(label, actual, expected, tol=1e-6):
    if expected is None or actual is None:
        ok = actual is expected
    elif isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        ok = abs(actual - expected) <= tol
    else:
        ok = actual == expected
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<34} got={actual!r} want={expected!r}")
    if not ok:
        FAILURES.append(label)


def trade(profit, risk=0.0, duration=600, sl=1.0, commission=0.0, swap=0.0, volume=0.1,
          symbol='EURUSD', magic=1, direction=0, ts=1000):
    return {
        "profit": profit, "entry_risk_usd": risk, "duration_sec": duration,
        "sl_at_open": sl, "commission": commission, "swap": swap, "volume": volume,
        "symbol": symbol, "magic": magic, "direction": direction,
        "side": "LONG" if direction == 0 else "SHORT", "close_ts": ts,
        "r_multiple": (profit / risk) if risk > 0 else None,
    }


print("\n--- win/loss/scratch buckets ---")
# 3 wins (+100 each), 2 losses (-50 each), 1 scratch.
# net = 300 - 100 = 200; win rate = 3/5 = 60% (scratch NOT in denominator)
m = _journal_metrics([trade(100), trade(100), trade(100), trade(-50), trade(-50), trade(0)])
check("total_trades", m['total_trades'], 6)
check("wins", m['wins'], 3)
check("losses", m['losses'], 2)
check("scratches", m['scratches'], 1)
check("win_rate excludes scratch", m['win_rate'], 60.0)
check("net_pnl", m['net_pnl'], 200.0)
check("gross_profit", m['gross_profit'], 300.0)
check("gross_loss", m['gross_loss'], -100.0)
check("profit_factor", m['profit_factor'], 3.0)
check("expectancy_usd = net/all", m['expectancy_usd'], 200.0 / 6)

print("\n--- payoff and breakeven win rate ---")
# avg win 100, avg loss -50 -> payoff 2.0 -> breakeven win rate 1/(1+2) = 33.33%
check("avg_win", m['avg_win'], 100.0)
check("avg_loss", m['avg_loss'], -50.0)
check("payoff_ratio", m['payoff_ratio'], 2.0)
check("breakeven_win_rate", m['breakeven_win_rate'], 100.0 / 3)

print("\n--- profit factor is undefined, not 99.9, with no losses ---")
m2 = _journal_metrics([trade(10), trade(20)])
check("profit_factor None", m2['profit_factor'], None)
check("payoff None", m2['payoff_ratio'], None)
check("win_rate 100", m2['win_rate'], 100.0)

print("\n--- empty set returns zeros, not crashes ---")
m3 = _journal_metrics([])
check("total_trades", m3['total_trades'], 0)
check("win_rate None", m3['win_rate'], None)
check("profit_factor None", m3['profit_factor'], None)
check("net_pnl", m3['net_pnl'], 0.0)

print("\n--- R-multiples only count trades that had a stop ---")
# 2 trades with risk (R = +2.0 and -1.0), 2 without -> coverage 50%, expectancy 0.5R
rs = [trade(200, risk=100), trade(-100, risk=100), trade(50), trade(-25)]
m4 = _journal_metrics(rs)
check("r_trades", m4['r_trades'], 2)
check("r_coverage_pct", m4['r_coverage_pct'], 50.0)
check("expectancy_r", m4['expectancy_r'], 0.5)
check("sqn suppressed under n=30", m4['sqn'], None)

print("\n--- SQN reported once there are 30 R-trades ---")
# 30 trades alternating +1R / -0.5R: mean = 0.25, sample stdev of the two-value set,
# SQN = sqrt(30) * mean / stdev
many = [trade(100 if i % 2 == 0 else -50, risk=100) for i in range(30)]
m5 = _journal_metrics(many)
rvals = [1.0 if i % 2 == 0 else -0.5 for i in range(30)]
expected_sqn = (30 ** 0.5) * (sum(rvals) / 30) / _stdev(rvals)
check("r_trades", m5['r_trades'], 30)
check("expectancy_r", m5['expectancy_r'], 0.25)
check("sqn", m5['sqn'], expected_sqn)

print("\n--- streaks ---")
# W W L L L W  -> max win 2, max loss 3, current +1
check("max_win_streak", _streaks([1, 1, -1, -1, -1, 1])[0], 2)
check("max_loss_streak", _streaks([1, 1, -1, -1, -1, 1])[1], 3)
check("current +1", _streaks([1, 1, -1, -1, -1, 1])[2], 1)
check("current -2", _streaks([1, -1, -1])[2], -2)
# A scratch breaks a streak without starting one.
check("scratch breaks streak", _streaks([1, 1, 0, 1])[0], 2)
check("current after scratch", _streaks([-1, -1, 0])[2], 0)

print("\n--- drawdown against a real starting balance ---")
# start 1000: +100 -> 1100 (peak), -300 -> 800, +50 -> 850
# max dd = 1100 - 800 = 300 = 27.2727% of peak; current dd = 1100 - 850 = 250
dd = _drawdown_series([trade(100), trade(-300), trade(50)], start_balance=1000.0)
check("max_dd_usd", dd['max_dd_usd'], 300.0)
check("max_dd_pct", dd['max_dd_pct'], 300.0 / 1100.0 * 100, tol=1e-3)
check("current_dd_usd", dd['current_dd_usd'], 250.0)
check("points", len(dd['points']), 3)
check("final equity", dd['points'][-1]['equity'], 850.0)

print("\n--- cost drag separates commission from swap ---")
# gross profit 100; commission -3, swap -7 -> drag = 10/100 = 10%
m6 = _journal_metrics([trade(100, commission=-3, swap=-7)])
check("commission_total", m6['commission_total'], -3.0)
check("swap_total", m6['swap_total'], -7.0)
check("cost_drag_pct", m6['cost_drag_pct'], 10.0)

print("\n--- hold-time asymmetry ---")
# winners held 60s, losers held 3600s -- the signature of an EA not honouring its stop
m7 = _journal_metrics([trade(10, duration=60), trade(10, duration=60), trade(-10, duration=3600)])
check("avg_hold_win_sec", m7['avg_hold_win_sec'], 60.0)
check("avg_hold_loss_sec", m7['avg_hold_loss_sec'], 3600.0)

print("\n--- trades without a stop are flagged ---")
m8 = _journal_metrics([trade(10, sl=0.0), trade(-5, sl=1.2), trade(3, sl=0.0)])
check("no_sl_count", m8['no_sl_count'], 2)

print("\n--- duration buckets ---")
check("30s", _duration_bucket(30), "< 1m")
check("90s", _duration_bucket(90), "1-5m")
check("2h", _duration_bucket(7200), "1-4h")
check("3 days", _duration_bucket(259200), "> 1d")
check("None", _duration_bucket(None), "unknown")

print("\n--- stdev ---")
check("stdev of one point", _stdev([1.0]), None)
check("sample stdev", _stdev([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]), 2.13809, tol=1e-4)

print("\n=== Phase 2 ===")

print("\n--- downside deviation (Sortino denominator) ---")
# +2, -1, +3, -2 with MAR 0: shortfalls 0,1,0,4 -> mean 1.25 -> sqrt = 1.11803
check("downside dev", _downside_deviation([2.0, -1.0, 3.0, -2.0]), (1.25) ** 0.5, tol=1e-6)
check("no downside -> 0", _downside_deviation([1.0, 2.0]), 0.0)
check("empty -> None", _downside_deviation([]), None)

print("\n--- ulcer index ---")
# 100 -> 90 -> 100: drawdowns 0%, 10%, 0% -> sqrt(mean(0,100,0)) = sqrt(33.333) = 5.7735
check("ulcer", _ulcer_index([100.0, 90.0, 100.0]), (100.0 / 3) ** 0.5, tol=1e-4)
check("monotonic rise -> 0", _ulcer_index([10.0, 20.0, 30.0]), 0.0)

print("\n--- risk-adjusted metrics are suppressed on a short sample ---")
short = {
    "series": [
        {"date": f"2026-01-{d:02d}", "start_balance": 1000.0, "pnl": 10.0, "funding": 0.0, "ret": 0.01}
        for d in range(1, 11)
    ],
    "start_balance": 1000.0,
    "end_balance": 1100.0,
}
m9 = _risk_adjusted_metrics(short)
check("observations", m9['observations'], 10)
check("sufficient False", m9['sufficient'], False)
check("sharpe suppressed", m9['sharpe'], None)
check("sortino suppressed", m9['sortino'], None)
# Ulcer and max DD are descriptive, not estimates, so they are still reported.
check("ulcer still reported", m9['ulcer_index'], 0.0)
check("min_observations exposed", m9['min_observations'], MIN_RETURN_DAYS)

print("\n--- Sharpe on a constant-return series is undefined (no dispersion) ---")
flat = {
    "series": [
        {"date": f"2026-{1 + d // 28:02d}-{1 + d % 28:02d}", "start_balance": 1000.0,
         "pnl": 1.0, "funding": 0.0, "ret": 0.001}
        for d in range(70)
    ],
    "start_balance": 1000.0,
    "end_balance": 1070.0,
}
m10 = _risk_adjusted_metrics(flat)
check("sufficient True", m10['sufficient'], True)
check("sharpe None (stdev 0)", m10['sharpe'], None)
check("max_dd 0 on monotonic rise", m10['max_dd_pct'], 0.0)

print("\n--- deposits do not count as return ---")
# Two days: +100 on 1000, then a 5000 deposit. Total return must be 10%, not 510%.
dep = {
    "series": [
        {"date": "2026-01-01", "start_balance": 1000.0, "pnl": 100.0, "funding": 0.0, "ret": 0.1},
        {"date": "2026-01-02", "start_balance": 1100.0, "pnl": 0.0, "funding": 5000.0, "ret": 0.0},
    ],
    "start_balance": 1000.0,
    "end_balance": 6100.0,
}
m11 = _risk_adjusted_metrics(dep)
check("total_return_pct excludes deposit", m11['total_return_pct'], 10.0, tol=1e-6)

print("\n--- return is time-weighted, so an account funded INSIDE the window still reports ---")
# Regression: the opening balance of such a window is legitimately 0 (every dollar arrived
# as a deposit during it). The old end/start form divided by that zero and returned n/a for
# total return while every other metric computed fine.
funded_inside = {
    "series": [
        {"date": "2026-01-01", "start_balance": 10000.0, "pnl": 500.0, "funding": 10000.0, "ret": 0.05},
        {"date": "2026-01-02", "start_balance": 10500.0, "pnl": 525.0, "funding": 0.0, "ret": 0.05},
    ],
    "start_balance": 0.0,      # nothing in the account before the deposit
    "end_balance": 11025.0,
}
m12 = _risk_adjusted_metrics(funded_inside)
check("opening_balance reported as 0", m12['opening_balance'], 0.0)
check("total return is not n/a", m12['total_return_pct'] is not None, True)
# TWR chains the daily returns: 1.05 * 1.05 - 1 = 10.25%
check("TWR compounds daily returns", m12['total_return_pct'], 10.25, tol=1e-6)
check("funding_total reported", m12['funding_total'], 10000.0)

print("\n--- TWR compounds rather than summing ---")
comp = {
    "series": [
        {"date": "2026-01-01", "start_balance": 100.0, "pnl": 10.0, "funding": 0.0, "ret": 0.1},
        {"date": "2026-01-02", "start_balance": 110.0, "pnl": -11.0, "funding": 0.0, "ret": -0.1},
    ],
    "start_balance": 100.0,
    "end_balance": 99.0,
}
# +10% then -10% is -1%, not 0%. A naive sum of returns would say 0.
check("gain then equal loss nets negative", _risk_adjusted_metrics(comp)['total_return_pct'], -1.0, tol=1e-9)

print("\n--- R distribution and profit concentration ---")
# 4 winners: 1000, 10, 10, 10 (gross 1030) -- one trade is 97% of the profit.
conc = [trade(1000, risk=100), trade(10, risk=100), trade(10, risk=100), trade(10, risk=100),
        trade(-50, risk=100)]
d1 = _r_distribution(conc)
check("r_trades", d1['r_trades'], 5)
check("coverage", d1['coverage_pct'], 100.0)
check("winners", d1['winners'], 4)
check("top1 share", d1['top1_share_pct'], round(1000 / 1030 * 100, 2))
check("top3 share", d1['top3_share_pct'], round(1020 / 1030 * 100, 2))
check("max_r", d1['max_r'], 10.0)
check("min_r", d1['min_r'], -0.5)
# Every trade must land in exactly one bin.
check("bins cover all trades", sum(b['count'] for b in d1['bins']), 5)

print("\n--- R distribution with no stops reports zero coverage, not a fake histogram ---")
d2 = _r_distribution([trade(10), trade(-5)])
check("r_trades", d2['r_trades'], 0)
check("coverage", d2['coverage_pct'], 0.0)
check("no bins", len(d2['bins']), 0)
check("median None", d2['median_r'], None)

print("\n--- Monte Carlo ---")
mc_trades = [trade(100 if i % 3 else -60, risk=100) for i in range(40)]
mc = _monte_carlo_drawdown(mc_trades, start_balance=10000.0, iterations=500, seed=42)
check("sufficient", mc['sufficient'], True)
check("trades", mc['trades'], 40)
check("iterations", mc['iterations'], 500)
# Percentiles must be monotonically non-decreasing, or the distribution is being read wrong.
pcts = [mc['percentiles'][k] for k in ('50', '75', '90', '95', '99')]
check("percentiles ascending", all(pcts[i] <= pcts[i + 1] for i in range(len(pcts) - 1)), True)
check("actual percentile in range", 0.0 <= mc['actual_percentile'] <= 100.0, True)
check("prob_worse complements", round(mc['actual_percentile'] + mc['prob_worse'], 6), 100.0)
check("same seed reproduces", _monte_carlo_drawdown(mc_trades, 10000.0, 500, seed=42)['percentiles']['95'],
      mc['percentiles']['95'])

print("\n--- Monte Carlo: bootstrap answers the forward question, permutation does not ---")
total = round(sum(t['profit'] for t in mc_trades), 2)
bs = mc['bootstrap']
check("actual_total recorded", bs['actual_total'], total, tol=0.01)
# Resampling with replacement MUST produce a spread; a degenerate one would mean the
# bootstrap silently collapsed back into a permutation.
check("bootstrap spreads outcomes", bs['final_percentiles']['5'] < bs['final_percentiles']['95'], True)
fps = [bs['final_percentiles'][k] for k in ('5', '25', '50', '75', '95')]
check("final percentiles ascending", all(fps[i] <= fps[i + 1] for i in range(len(fps) - 1)), True)
bds = [bs['dd_percentiles'][k] for k in ('50', '90', '95', '99')]
check("bootstrap DD ascending", all(bds[i] <= bds[i + 1] for i in range(len(bds) - 1)), True)
check("prob_losing in range", 0.0 <= bs['prob_losing'] <= 100.0, True)

print("\n--- Monte Carlo refuses to run on too small a sample ---")
mc2 = _monte_carlo_drawdown([trade(10, risk=100)] * 5, 10000.0, seed=1)
check("sufficient False", mc2['sufficient'], False)
check("min_trades exposed", mc2['min_trades'], MIN_MC_TRADES)
check("no percentiles", len(mc2['percentiles']), 0)
check("no balance -> insufficient", _monte_carlo_drawdown(mc_trades, None, seed=1)['sufficient'], False)

print("\n--- edge ratio ---")
def excursion(profit, risk, mae, mfe):
    t = trade(profit, risk=risk)
    t['mae_usd'], t['mfe_usd'] = mae, mfe
    return t

# avg MFE 1.5R, avg MAE 0.5R -> edge ratio 3.0
e = _edge_ratio([excursion(100, 100, -50, 150), excursion(-100, 100, -50, 150)])
check("avg_mfe_r", e['avg_mfe_r'], 1.5)
check("avg_mae_r", e['avg_mae_r'], 0.5)
check("edge_ratio", e['edge_ratio'], 3.0)
check("sample", e['sample'], 2)
# Trades still awaiting backfill must be excluded, not treated as zero excursion.
check("un-backfilled excluded", _edge_ratio([trade(100, risk=100)])['sample'], 0)
check("no sample -> None", _edge_ratio([trade(100, risk=100)])['edge_ratio'], None)

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURE(S): {', '.join(FAILURES)}")
    sys.exit(1)
print("All journal metric checks passed.")
