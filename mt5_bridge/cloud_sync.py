"""Pushes a redacted copy of trades.db to the cloud (Vercel + Postgres) ingestion
endpoint. Runs two ways that share this exact same code path, so a manual sync and
the daily scheduled one can never disagree about what was sent:

  - Daily, unattended, via Windows Task Scheduler: `python cloud_sync.py`
  - On demand, via the Settings "Sync Now" button: POST /api/cloud_sync on
    app_server.py, which imports and calls sync_to_cloud() directly.

Only data needed for portfolio/performance review crosses this boundary. Never
sent: `path` (would leak the local filesystem layout), copier role/sizing
config, alert thresholds, or trade_locked -- none of that is meaningful outside
this machine, and copier config in particular controls live order sizing.
"""
import json
import os
import sqlite3
import time

import requests
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trades.db')
CLOUD_SYNC_URL = os.getenv('CLOUD_SYNC_URL', '')
CLOUD_SYNC_SECRET = os.getenv('CLOUD_SYNC_SECRET', '')


def _rows(c, query, params=()):
    c.execute(query)
    cols = [d[0] for d in c.description]
    return [dict(zip(cols, row)) for row in c.execute(query, params) or []]


def _table_rows(c, table, columns, order_by=None):
    col_list = ', '.join(columns)
    query = f"SELECT {col_list} FROM {table}"
    if order_by:
        query += f" ORDER BY {order_by}"
    c.execute(query)
    return [dict(zip(columns, row)) for row in c.fetchall()]


def build_sync_payload():
    """Reads the redacted table set out of trades.db into a plain JSON-able dict."""
    conn = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True)
    c = conn.cursor()
    try:
        instances = _table_rows(
            c, 'instances',
            ['id', 'name', 'group_name', 'account_type', 'copier_role'],
            order_by='id ASC',
        )

        trading_log = _table_rows(
            c, 'trading_log',
            ['instance_id', 'ticket', 'position_id', 'symbol', 'type', 'direction',
             'volume', 'profit', 'commission', 'swap', 'raw_profit', 'time',
             'local_time', 'local_start_time', 'entry_price', 'exit_price',
             'sl_at_open', 'tp_at_open', 'entry_risk_usd', 'mae_usd', 'mfe_usd',
             'magic', 'comment'],
        )

        trade_annotations = _table_rows(
            c, 'trade_annotations',
            ['instance_id', 'position_id', 'tags', 'grade', 'note', 'updated_at'],
        )

        balance_operations = _table_rows(
            c, 'balance_operations',
            ['instance_id', 'ticket', 'time', 'local_time', 'deal_type', 'amount', 'comment'],
        )

        risk_snapshots = _table_rows(
            c, 'risk_snapshots',
            ['instance_id', 'date', 'peak_drawdown_pct', 'max_risk_usd', 'no_sl_count'],
        )

        # trade_history is the analytics source of record on both sides now -- the cloud
        # dashboard and the weekly/monthly reports read it, not trading_log. It carries the
        # open time in the broker's own clock as well as UTC, which trading_log cannot.
        trade_history = _table_rows(
            c, 'trade_history',
            ['instance_id', 'position_id', 'ticket', 'symbol', 'direction', 'volume',
             'open_time_server', 'close_time_server', 'open_time_utc', 'close_time_utc',
             'broker_offset_sec', 'duration_sec', 'entry_price', 'exit_price',
             'sl_at_open', 'tp_at_open', 'raw_profit', 'commission', 'swap', 'profit',
             'entry_risk_usd', 'mae_usd', 'mfe_usd', 'magic', 'comment'],
            order_by='instance_id ASC, close_time_utc ASC',
        )

        profit_lock_events = _table_rows(
            c, 'profit_lock_events',
            ['id', 'instance_id', 'date', 'crossed_at', 'target_pct', 'peak_pct',
             'peak_floating_usd', 'start_equity', 'equity', 'balance', 'armed',
             'ticket_count', 'status', 'resolved_at', 'realized_usd', 'verdict'],
            order_by='crossed_at ASC',
        )

        profit_lock_event_tickets = _table_rows(
            c, 'profit_lock_event_tickets',
            ['event_id', 'instance_id', 'ticket', 'symbol', 'floating_usd_at_cross',
             'realized_usd', 'closed_at'],
        )

        # public_username/public_password_hash don't exist yet -- Settings' Cloud Sync
        # panel only ships the sync button in this phase. SELECTing a column that
        # doesn't exist raises OperationalError immediately (unlike a short row), so
        # fall back to the smaller query rather than relying on a length check.
        auth = {"username": None, "password_hash": None}
        try:
            c.execute("SELECT journal_day_anchor, journal_day_offset_min, public_username, public_password_hash "
                      "FROM global_settings WHERE id = 1")
            row = c.fetchone()
            if row:
                auth = {"username": row[2], "password_hash": row[3]}
        except sqlite3.OperationalError:
            c.execute("SELECT journal_day_anchor, journal_day_offset_min FROM global_settings WHERE id = 1")
            row = c.fetchone()

        journal_config = {
            "journal_day_anchor": row[0] if row else 'MACHINE',
            "journal_day_offset_min": row[1] if row else 0,
        }
    finally:
        conn.close()

    return {
        "generated_at": int(time.time()),
        "instances": instances,
        "trading_log": trading_log,
        "trade_annotations": trade_annotations,
        "balance_operations": balance_operations,
        "risk_snapshots": risk_snapshots,
        "trade_history": trade_history,
        "profit_lock_events": profit_lock_events,
        "profit_lock_event_tickets": profit_lock_event_tickets,
        "journal_config": journal_config,
        "auth": auth,
    }


def _record_sync_result(status, message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "UPDATE global_settings SET last_cloud_sync_at = ?, last_cloud_sync_status = ?, "
        "last_cloud_sync_message = ? WHERE id = 1",
        (int(time.time()), status, message),
    )
    conn.commit()
    conn.close()


def sync_to_cloud():
    """Builds the payload and POSTs it. Returns (ok, message) -- never raises, so both
    the Task Scheduler entrypoint and the Flask route can treat this as the single
    source of truth for what happened, without duplicating error handling."""
    if not CLOUD_SYNC_URL or not CLOUD_SYNC_SECRET:
        message = "CLOUD_SYNC_URL / CLOUD_SYNC_SECRET not configured in .env"
        _record_sync_result('error', message)
        return False, message

    try:
        payload = build_sync_payload()
    except Exception as e:
        message = f"Failed to read trades.db: {e}"
        _record_sync_result('error', message)
        return False, message

    try:
        resp = requests.post(
            CLOUD_SYNC_URL,
            headers={
                "Authorization": f"Bearer {CLOUD_SYNC_SECRET}",
                "Content-Type": "application/json",
            },
            data=json.dumps(payload),
            timeout=30,
        )
    except requests.RequestException as e:
        message = f"Request to cloud sync endpoint failed: {e}"
        _record_sync_result('error', message)
        return False, message

    if resp.status_code != 200:
        message = f"Cloud sync endpoint returned {resp.status_code}: {resp.text[:300]}"
        _record_sync_result('error', message)
        return False, message

    row_counts = {k: len(payload[k]) for k in
                  ('instances', 'trading_log', 'trade_annotations', 'balance_operations',
                   'risk_snapshots', 'trade_history', 'profit_lock_events',
                   'profit_lock_event_tickets')}
    message = (f"Synced {row_counts['trade_history']} trades across "
               f"{row_counts['instances']} instance(s)")
    _record_sync_result('success', message)
    return True, message


def generate_cloud_report(period, period_start, period_end):
    """Ask the cloud to build and freeze one weekly/monthly report.

    Called *after* a successful sync_to_cloud(), never on its own schedule. A cloud-side
    cron firing independently would sometimes build Saturday's report from Friday's data
    and be silently wrong; driving it from here makes the ordering structural.

    Returns (ok, url_or_message).
    """
    if not CLOUD_SYNC_URL or not CLOUD_SYNC_SECRET:
        return False, "cloud sync not configured"

    base = CLOUD_SYNC_URL.rsplit('/api/sync', 1)[0]
    try:
        resp = requests.post(
            f"{base}/api/reports/generate",
            headers={
                "Authorization": f"Bearer {CLOUD_SYNC_SECRET}",
                "Content-Type": "application/json",
            },
            data=json.dumps({
                "period": period,
                "period_start": period_start,
                "period_end": period_end,
            }),
            timeout=60,
        )
    except requests.RequestException as e:
        return False, f"report request failed: {e}"

    if resp.status_code != 200:
        return False, f"report endpoint returned {resp.status_code}: {resp.text[:300]}"

    try:
        report_id = resp.json().get("id")
    except ValueError:
        return False, "report endpoint returned a non-JSON body"

    return True, f"{base}/reports/{report_id}"


if __name__ == '__main__':
    ok, message = sync_to_cloud()
    print(("[OK] " if ok else "[FAIL] ") + message)
    raise SystemExit(0 if ok else 1)
