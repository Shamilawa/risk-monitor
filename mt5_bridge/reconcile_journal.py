"""Reconcile trading_log against MT5's own deal history, per instance.

This is the acceptance test for the journal: every metric the app shows is derived from
trading_log, so if trading_log doesn't agree with the broker's history to the cent, nothing
built on top of it can be trusted.

It recomputes closed-position count, net P&L, gross profit/loss and commission/swap totals
straight from `history_deals_get`, using an independent code path from the one the app's
sync uses, then diffs the two.

Usage (from mt5_bridge/, with the MT5 terminals installed and running):
    python reconcile_journal.py                # all instances, full history
    python reconcile_journal.py --days 90      # trailing window
    python reconcile_journal.py --instance 2   # single instance
    python reconcile_journal.py --verbose      # list every mismatched position

Exit code is 0 when everything reconciles, 1 when any instance is off.
"""

import argparse
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta

import MetaTrader5 as mt5

DEAL_ENTRY_IN = getattr(mt5, 'DEAL_ENTRY_IN', 0)
DEAL_ENTRY_OUT = getattr(mt5, 'DEAL_ENTRY_OUT', 1)
DEAL_ENTRY_INOUT = getattr(mt5, 'DEAL_ENTRY_INOUT', 2)
DEAL_ENTRY_OUT_BY = getattr(mt5, 'DEAL_ENTRY_OUT_BY', 3)

# Currency comparisons are done to the cent; anything tighter just trips on float noise.
TOLERANCE = 0.01


def money(v):
    return f"{v:>12,.2f}"


def broker_truth(days=None):
    """Closed positions straight from MT5 deal history, grouped by position_id.

    Intentionally written independently of app_server.sync_trading_log() -- a reconciliation
    that shares the code under test proves nothing.
    """
    from_date = datetime(2000, 1, 1) if days is None else datetime.now() - timedelta(days=days)
    to_date = datetime.now() + timedelta(days=1)

    deals = mt5.history_deals_get(from_date, to_date)
    if deals is None:
        raise RuntimeError(f"history_deals_get failed: {mt5.last_error()}")

    by_position = defaultdict(list)
    for d in deals:
        if d.type in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL) and d.position_id:
            by_position[d.position_id].append(d)

    positions = {}
    for pid, pos_deals in by_position.items():
        opened = sum(d.volume for d in pos_deals if d.entry == DEAL_ENTRY_IN)
        closed = sum(
            d.volume for d in pos_deals
            if d.entry in (DEAL_ENTRY_OUT, DEAL_ENTRY_OUT_BY, DEAL_ENTRY_INOUT)
        )
        if opened <= 0 or closed + 1e-8 < opened:
            continue  # still open, or opened outside the window -- not a closed trade here

        raw = sum(d.profit for d in pos_deals)
        commission = sum(d.commission for d in pos_deals)
        swap = sum(d.swap for d in pos_deals)
        positions[pid] = {
            "net": raw + commission + swap,
            "raw": raw,
            "commission": commission,
            "swap": swap,
        }
    return positions


def logged_positions(db, instance_id, days=None):
    """The same set as the app stores it, keyed by position_id."""
    c = db.cursor()
    sql = (
        "SELECT position_id, profit, raw_profit, commission, swap, ticket "
        "FROM trading_log WHERE instance_id = ?"
    )
    params = [instance_id]
    if days is not None:
        cutoff = int((datetime.now() - timedelta(days=days)).timestamp())
        sql += " AND COALESCE(local_time, time) >= ?"
        params.append(cutoff)

    out = {}
    duplicates = []
    for pid, profit, raw, commission, swap, ticket in c.execute(sql, params):
        if pid is None:
            duplicates.append(("<no position_id>", ticket))
            continue
        if pid in out:
            # Exactly the defect this script exists to catch: more than one row for a
            # position means a scale-out was counted once per partial exit.
            duplicates.append((pid, ticket))
            continue
        out[pid] = {
            "net": profit or 0.0,
            "raw": raw or 0.0,
            "commission": commission or 0.0,
            "swap": swap or 0.0,
        }
    return out, duplicates


def reconcile_instance(db, inst_id, name, path, days, verbose):
    print(f"\n=== {name} (instance {inst_id}) ===")

    initialized = mt5.initialize(path=path) if path else mt5.initialize()
    if not initialized:
        print(f"  SKIP: could not initialize MT5 ({mt5.last_error()})")
        return None

    try:
        truth = broker_truth(days)
    except RuntimeError as e:
        print(f"  SKIP: {e}")
        return None
    finally:
        mt5.shutdown()

    logged, duplicates = logged_positions(db, inst_id, days)

    truth_net = sum(p["net"] for p in truth.values())
    logged_net = sum(p["net"] for p in logged.values())

    print(f"  {'':<22}{'MT5':>13}{'trading_log':>15}{'diff':>13}")
    rows = [
        ("closed positions", len(truth), len(logged)),
        ("net P&L", truth_net, logged_net),
        ("gross profit", sum(p["net"] for p in truth.values() if p["net"] > 0),
         sum(p["net"] for p in logged.values() if p["net"] > 0)),
        ("gross loss", sum(p["net"] for p in truth.values() if p["net"] < 0),
         sum(p["net"] for p in logged.values() if p["net"] < 0)),
        ("commission", sum(p["commission"] for p in truth.values()),
         sum(p["commission"] for p in logged.values())),
        ("swap", sum(p["swap"] for p in truth.values()),
         sum(p["swap"] for p in logged.values())),
    ]

    ok = True
    for label, a, b in rows:
        diff = b - a
        if abs(diff) > TOLERANCE:
            ok = False
        flag = "" if abs(diff) <= TOLERANCE else "  <-- MISMATCH"
        if isinstance(a, int):
            print(f"  {label:<22}{a:>13,}{b:>15,}{diff:>13,}{flag}")
        else:
            print(f"  {label:<22}{money(a)}{money(b):>15}{money(diff)}{flag}")

    if duplicates:
        ok = False
        print(f"  DUPLICATE ROWS: {len(duplicates)} position(s) logged more than once "
              f"(or with no position_id) -- these multi-count P&L")
        for pid, ticket in duplicates[:10]:
            print(f"    position {pid} (ticket {ticket})")

    missing = set(truth) - set(logged)
    extra = set(logged) - set(truth)
    if missing:
        ok = False
        print(f"  MISSING: {len(missing)} closed position(s) in MT5 but not in trading_log")
        if verbose:
            for pid in sorted(missing)[:20]:
                print(f"    {pid}  net {truth[pid]['net']:.2f}")
    if extra:
        ok = False
        print(f"  EXTRA: {len(extra)} position(s) in trading_log but not in MT5's window")
        if verbose:
            for pid in sorted(extra)[:20]:
                print(f"    {pid}  net {logged[pid]['net']:.2f}")

    mismatched = [
        pid for pid in set(truth) & set(logged)
        if abs(truth[pid]["net"] - logged[pid]["net"]) > TOLERANCE
    ]
    if mismatched:
        ok = False
        print(f"  VALUE MISMATCH: {len(mismatched)} position(s) with a different net P&L")
        if verbose:
            for pid in sorted(mismatched)[:20]:
                print(f"    {pid}  MT5 {truth[pid]['net']:.2f}  log {logged[pid]['net']:.2f}")

    print(f"  RESULT: {'OK' if ok else 'FAILED'}")
    return ok


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default='trades.db')
    parser.add_argument('--days', type=int, default=None,
                        help='reconcile only the trailing N days (default: all history)')
    parser.add_argument('--instance', type=int, default=None, help='single instance id')
    parser.add_argument('--verbose', action='store_true', help='list mismatched positions')
    args = parser.parse_args()

    db = sqlite3.connect(args.db)
    c = db.cursor()
    if args.instance is not None:
        c.execute("SELECT id, name, path FROM instances WHERE id = ?", (args.instance,))
    else:
        c.execute("SELECT id, name, path FROM instances ORDER BY id")
    instances = c.fetchall()

    if not instances:
        print("No instances configured.")
        return 0

    window = "all history" if args.days is None else f"trailing {args.days} days"
    print(f"Reconciling trading_log against MT5 deal history ({window}, tolerance ${TOLERANCE})")

    results = []
    for inst_id, name, path in instances:
        results.append(reconcile_instance(db, inst_id, name, path, args.days, args.verbose))
    db.close()

    checked = [r for r in results if r is not None]
    failed = [r for r in checked if not r]
    print(f"\n{len(checked) - len(failed)}/{len(checked)} instance(s) reconciled"
          f"{f', {len(results) - len(checked)} skipped' if len(results) != len(checked) else ''}")
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
