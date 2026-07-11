"""
Run on the VPS before doing anything to trades.db that ISN'T a plain
CREATE TABLE IF NOT EXISTS / ALTER TABLE ... ADD COLUMN (i.e. before hand-
editing/replacing the DB file itself, which the normal deploy flow never
does). Reports whether any configured MT5 instance currently has open
positions.

Usage:
    python check_open_positions.py             # uses trades.db next to app_server.py
    python check_open_positions.py --db path\to\trades.db

Exit code 0  -> no open positions anywhere, safe to proceed
Exit code 1  -> at least one instance has open positions, DO NOT touch the DB
Exit code 2  -> couldn't check (bad DB / MT5 not reachable) -- treat as unsafe
"""
import argparse
import os
import sqlite3
import sys

import MetaTrader5 as mt5

parser = argparse.ArgumentParser()
parser.add_argument("--db", default=os.path.join(os.path.dirname(__file__), "..", "trades.db"))
args = parser.parse_args()

if not os.path.exists(args.db):
    print(f"DB not found at {args.db}")
    sys.exit(2)

conn = sqlite3.connect(args.db)
rows = conn.execute("SELECT id, name, path FROM instances").fetchall()
conn.close()

if not rows:
    print("No instances configured. Safe to proceed.")
    sys.exit(0)

any_open = False
any_error = False

for instance_id, name, path in rows:
    if not mt5.initialize(path=path):
        print(f"[{name}] could not connect to terminal at {path} -- treating as UNSAFE")
        any_error = True
        mt5.shutdown()
        continue

    positions = mt5.positions_get()
    count = len(positions) if positions else 0
    mt5.shutdown()

    if count > 0:
        print(f"[{name}] {count} OPEN position(s)")
        any_open = True
    else:
        print(f"[{name}] no open positions")

print()
if any_error:
    print("RESULT: UNSAFE (could not verify one or more instances)")
    sys.exit(2)
elif any_open:
    print("RESULT: UNSAFE -- open positions exist, do not modify trades.db now")
    sys.exit(1)
else:
    print("RESULT: SAFE -- no open positions on any instance")
    sys.exit(0)
