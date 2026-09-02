"""Deterministic copier reconciliation, incident tracking and alerting.

The copier is fire-and-forget over ZMQ: the provider pushes, consumers act, and
nothing ever reports back. That means a rejected or undelivered copy is silent
-- the failure paths in mt5_worker.py only print() to a console nobody is
watching. This module makes those failures loud.

Two independent detection layers, on purpose:

  1. LEDGER (what was *reported*) -- every signal and every consumer outcome is
     recorded via localhost HTTP, so we know who filled, who rejected and why,
     with the broker's own retcode and comment.

  2. RECONCILER (what is *true*) -- every ~15s, diff the provider's live open
     positions against each consumer's. This needs no cooperation from the
     workers at all, so it still catches failures when a worker has crashed,
     lost its ZMQ subscription, or never received the signal in the first place.

Layer 2 is the real safety net; layer 1 explains what layer 2 finds. Both feed
one incident engine that dedupes, alerts once, and auto-resolves.

No LLM anywhere in the detection path: the ground truth here is an exact set
difference, and a monitor whose failure mode is silence must not have a
probabilistic detector.
"""
import json
import os
import sqlite3
import threading
import time
from datetime import datetime

import issue_log

COPIER_MAGIC = 777888

# A provider position must be visible this long before a missing mirror counts
# as a real failure rather than normal fill latency.
COPY_GRACE_SEC = 25
# How long after the provider goes flat before a still-open mirror is an alarm.
CLOSE_GRACE_SEC = 30
# A consumer must have been continuously online this long before we judge it,
# so a terminal that just reconnected doesn't produce a burst of false alarms.
CONSUMER_SETTLE_SEC = 30
# Wait this long after a signal before summarising its fan-out, so slow
# consumers land in the same message rather than looking like failures.
FANOUT_SUMMARY_SEC = 10
# More than this many CRITICALs for one instance inside 60s collapses into a
# single "this consumer is failing everything" alert.
STORM_LIMIT = 5
STORM_WINDOW_SEC = 60

# --- injected by app_server.configure() to avoid a circular import ---
_send_telegram = None
_send_telegram_buttons = None
_notify_clients = None
_execute_trade = None
_close_position = None

# in-memory reconciler state
_provider_seen_at = {}      # provider_ticket -> local epoch first observed
_provider_gone_at = {}      # provider_ticket -> local epoch first seen absent
_consumer_online_since = {}  # consumer_id -> local epoch
_storm_events = {}          # instance_id -> [epoch, ...]
_worker_restarts = {}       # instance_id -> [epoch, ...]
_state_lock = threading.Lock()

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trades.db')


def configure(send_telegram=None, send_telegram_buttons=None, notify_clients=None,
              execute_trade=None, close_position=None):
    """Wire in app_server's helpers. Called once at startup."""
    global _send_telegram, _send_telegram_buttons, _notify_clients
    global _execute_trade, _close_position
    _send_telegram = send_telegram
    _send_telegram_buttons = send_telegram_buttons
    _notify_clients = notify_clients
    _execute_trade = execute_trade
    _close_position = close_position


def _tg(msg):
    try:
        if _send_telegram:
            _send_telegram(msg)
    except Exception:
        pass


def _tg_buttons(msg, buttons):
    try:
        if _send_telegram_buttons:
            return _send_telegram_buttons(msg, buttons)
    except Exception:
        pass
    return None


# --- MT5 RETCODES ---------------------------------------------------------
# name + plain-English cause, so an alert reads as a diagnosis instead of a number.
RETCODES = {
    10004: ("REQUOTE", "price moved before the order landed"),
    10006: ("REJECT", "broker rejected the request"),
    10007: ("CANCEL", "cancelled by the trader/terminal"),
    10010: ("DONE_PARTIAL", "only part of the volume was filled"),
    10011: ("ERROR", "request processing error"),
    10012: ("TIMEOUT", "request timed out"),
    10013: ("INVALID", "malformed request"),
    10014: ("INVALID_VOLUME", "lot size is below min, above max, or not a multiple of the step"),
    10015: ("INVALID_PRICE", "price is invalid for this symbol"),
    10016: ("INVALID_STOPS", "SL/TP too close to price or on the wrong side (stops level)"),
    10017: ("TRADE_DISABLED", "trading is disabled on this account"),
    10018: ("MARKET_CLOSED", "market is closed for this symbol"),
    10019: ("NO_MONEY", "not enough free margin"),
    10020: ("PRICE_CHANGED", "price changed during execution"),
    10021: ("PRICE_OFF", "no quotes available for this symbol"),
    10024: ("TOO_MANY_REQUESTS", "request rate limited by the broker"),
    10026: ("SERVER_DISABLES_AT", "algo trading disabled on the broker side"),
    10027: ("CLIENT_DISABLES_AT", "algo trading disabled in the terminal (Tools > Options)"),
    10028: ("LOCKED", "request locked by the dealer"),
    10029: ("FROZEN", "position is frozen and cannot be modified"),
    10030: ("INVALID_FILL", "unsupported filling mode"),
    10031: ("CONNECTION", "no connection to the trade server"),
    10034: ("LIMIT_VOLUME", "symbol/account volume limit reached"),
    10036: ("POSITION_CLOSED", "position was already closed"),
    10038: ("INVALID_CLOSE_VOLUME", "close volume exceeds the open position"),
    10040: ("LIMIT_POSITIONS", "max open positions reached for this account"),
    10042: ("LONG_ONLY", "only long positions are allowed on this symbol"),
    10043: ("SHORT_ONLY", "only short positions are allowed on this symbol"),
    10044: ("CLOSE_ONLY", "only position closing is allowed"),
    10045: ("FIFO_CLOSE", "FIFO rule: older positions must be closed first"),
    10046: ("HEDGE_PROHIBITED", "hedging is not allowed on this account"),
}


def retcode_name(code):
    return RETCODES.get(code, ("UNKNOWN", ""))[0]


def retcode_hint(code):
    return RETCODES.get(code, ("UNKNOWN", ""))[1]


# --- SCHEMA ---------------------------------------------------------------

def init_schema(c):
    """Called from app_server.init_db() with an open cursor."""
    c.execute('''
        CREATE TABLE IF NOT EXISTS copier_signals (
            signal_id TEXT PRIMARY KEY,
            provider_id INTEGER,
            type TEXT,
            symbol TEXT,
            action TEXT,
            volume REAL,
            price REAL,
            sl REAL,
            tp REAL,
            provider_ticket INTEGER,
            sent_at INTEGER,
            expected_consumers TEXT,
            summary_sent INTEGER DEFAULT 0
        )
    ''')
    c.execute("CREATE INDEX IF NOT EXISTS idx_signals_sent ON copier_signals(sent_at)")

    c.execute('''
        CREATE TABLE IF NOT EXISTS copier_executions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id TEXT,
            consumer_id INTEGER,
            provider_ticket INTEGER,
            status TEXT,
            local_ticket INTEGER,
            filled_volume REAL,
            fill_price REAL,
            retcode INTEGER,
            broker_comment TEXT,
            reason TEXT,
            latency_ms INTEGER,
            updated_at INTEGER,
            UNIQUE(signal_id, consumer_id)
        )
    ''')
    c.execute("CREATE INDEX IF NOT EXISTS idx_exec_pticket ON copier_executions(provider_ticket, consumer_id)")

    # dedupe_key is deliberately NOT unique: the same condition may legitimately
    # recur after being resolved. Open-incident lookups filter on status instead.
    c.execute('''
        CREATE TABLE IF NOT EXISTS copier_incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dedupe_key TEXT,
            type TEXT,
            severity TEXT,
            category TEXT,
            instance_id INTEGER,
            instance_name TEXT,
            signal_id TEXT,
            provider_ticket INTEGER,
            fingerprint TEXT,
            detail TEXT,
            first_seen INTEGER,
            last_seen INTEGER,
            status TEXT DEFAULT 'OPEN',
            resolved_at INTEGER
        )
    ''')
    c.execute("CREATE INDEX IF NOT EXISTS idx_incidents_open ON copier_incidents(dedupe_key, status)")


# --- INCIDENT ENGINE ------------------------------------------------------

def _storm_check(instance_id, instance_name):
    """True if this instance is currently storming (and should be suppressed)."""
    now = time.time()
    with _state_lock:
        events = [t for t in _storm_events.get(instance_id, []) if now - t < STORM_WINDOW_SEC]
        events.append(now)
        _storm_events[instance_id] = events
        return len(events) > STORM_LIMIT


def raise_incident(conn, itype, severity, instance_id, instance_name, detail,
                   dedupe_key=None, signal_id=None, provider_ticket=None,
                   fingerprint=None, category='COPIER', buttons=None):
    """Record an incident once. Repeat sightings only bump last_seen.

    `detail` is an ordered dict -- it becomes both the Telegram body and the
    issue-log block, so the file and the phone can never disagree.
    """
    now = int(time.time())
    key = dedupe_key or f"{itype}:{instance_id}:{provider_ticket or signal_id or ''}"
    c = conn.cursor()

    c.execute(
        "SELECT id, status FROM copier_incidents WHERE dedupe_key = ? AND status IN ('OPEN','ACKED') LIMIT 1",
        (key,)
    )
    row = c.fetchone()
    if row:
        c.execute("UPDATE copier_incidents SET last_seen = ? WHERE id = ?", (now, row[0]))
        conn.commit()
        return row[0]

    c.execute(
        """INSERT INTO copier_incidents
           (dedupe_key, type, severity, category, instance_id, instance_name, signal_id,
            provider_ticket, fingerprint, detail, first_seen, last_seen, status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'OPEN')""",
        (key, itype, severity, category, instance_id, instance_name, signal_id,
         provider_ticket, fingerprint, json.dumps(detail), now, now)
    )
    conn.commit()
    incident_id = c.lastrowid

    issue_log.log_issue(
        severity=severity, category=category, itype=itype,
        instance_name=instance_name, instance_id=instance_id,
        signal_id=signal_id, fingerprint=fingerprint, details=detail,
    )

    if severity == 'CRITICAL':
        if _storm_check(instance_id, instance_name):
            # Suppress the individual alert; one storm notice covers the burst.
            storm_key = f"STORM:{instance_id}"
            c.execute(
                "SELECT id FROM copier_incidents WHERE dedupe_key = ? AND status IN ('OPEN','ACKED') LIMIT 1",
                (storm_key,)
            )
            if not c.fetchone():
                c.execute(
                    """INSERT INTO copier_incidents
                       (dedupe_key, type, severity, category, instance_id, instance_name,
                        detail, first_seen, last_seen, status)
                       VALUES (?,?,?,?,?,?,?,?,?,'OPEN')""",
                    (storm_key, 'FAILURE_STORM', 'CRITICAL', 'COPIER', instance_id, instance_name,
                     json.dumps({'note': f'>{STORM_LIMIT} critical issues in {STORM_WINDOW_SEC}s'}), now, now)
                )
                conn.commit()
                issue_log.log_issue(
                    'CRITICAL', 'COPIER', 'FAILURE_STORM', instance_name, instance_id,
                    details={'note': f'more than {STORM_LIMIT} critical issues within {STORM_WINDOW_SEC}s',
                             'action': 'individual alerts suppressed until this clears'},
                    fingerprint=f'FAILURE_STORM:{instance_name}',
                )
                _tg(f"🔴 {instance_name} is failing everything — more than {STORM_LIMIT} copier "
                    f"issues in {STORM_WINDOW_SEC}s. Further alerts for this instance are suppressed "
                    f"until it clears. Check the terminal.")
        else:
            _alert_incident(incident_id, itype, instance_name, detail, buttons)

    try:
        if _notify_clients:
            _notify_clients("copier_incident", json.dumps({
                "id": incident_id, "type": itype, "severity": severity,
                "instance_name": instance_name, "detail": detail,
            }))
    except Exception:
        pass

    return incident_id


TITLES = {
    'COPY_MISSING': '🔴 COPY MISSING',
    'CLOSE_NOT_MIRRORED': '🔴 CLOSE NOT MIRRORED',
    'ORPHAN_POSITION': '🔴 ORPHAN POSITION',
    'WRONG_DIRECTION': '🔴 WRONG DIRECTION',
    'WORKER_DOWN': '🔴 COPIER WORKER DOWN',
    'COPY_REJECTED': '🔴 COPY REJECTED',
    'SIZE_MISMATCH': '⚠️ SIZE MISMATCH',
    'MISSING_SL': '⚠️ NO SL ON MIRROR',
    'MODIFY_NOT_MIRRORED': '⚠️ MODIFY NOT MIRRORED',
    'SLOW_FILL': '⚠️ SLOW FILL',
}


def _alert_incident(incident_id, itype, instance_name, detail, buttons):
    title = TITLES.get(itype, f'🔴 {itype}')
    lines = [f"{title} — {instance_name}"]
    for k, v in detail.items():
        if v not in (None, ""):
            lines.append(f"{k}: {v}")
    msg = "\n".join(lines)
    if buttons:
        _tg_buttons(msg, [(label, f"cop:{act}:{incident_id}") for label, act in buttons])
    else:
        _tg(msg)


def resolve_incident(conn, dedupe_key, how, extra=None):
    """Close an open incident and say so, on the phone and in the file."""
    c = conn.cursor()
    c.execute(
        """SELECT id, type, instance_id, instance_name, signal_id, first_seen, detail
           FROM copier_incidents WHERE dedupe_key = ? AND status IN ('OPEN','ACKED') LIMIT 1""",
        (dedupe_key,)
    )
    row = c.fetchone()
    if not row:
        return False

    incident_id, itype, inst_id, inst_name, signal_id, first_seen, _detail = row
    now = int(time.time())
    c.execute("UPDATE copier_incidents SET status='RESOLVED', resolved_at=? WHERE id=?", (now, incident_id))
    conn.commit()

    open_for = now - (first_seen or now)
    details = {'via': how}
    if extra:
        details.update(extra)
    details['open_for'] = f"{open_for // 60}m {open_for % 60}s"

    issue_log.log_resolution(itype, inst_name, inst_id, signal_id, details)

    if itype in ('COPY_MISSING', 'CLOSE_NOT_MIRRORED', 'ORPHAN_POSITION', 'WRONG_DIRECTION',
                 'WORKER_DOWN', 'COPY_REJECTED', 'FAILURE_STORM'):
        detail_str = " ".join(f"{k}={v}" for k, v in details.items())
        _tg(f"🟢 RESOLVED — {inst_name} {itype} ({detail_str})")
    return True


# --- LEDGER ---------------------------------------------------------------

def record_signal(conn, payload):
    """Provider reported a signal. Snapshots who *should* mirror it, so
    'who didn't fill' is answerable later even if config changes."""
    c = conn.cursor()
    try:
        c.execute("SELECT id FROM instances WHERE copier_role = 'CONSUMER'")
        expected = [r[0] for r in c.fetchall()]
    except sqlite3.OperationalError:
        expected = []

    c.execute(
        """INSERT OR REPLACE INTO copier_signals
           (signal_id, provider_id, type, symbol, action, volume, price, sl, tp,
            provider_ticket, sent_at, expected_consumers, summary_sent)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0)""",
        (payload.get('signal_id'), payload.get('provider_id'), payload.get('type'),
         payload.get('symbol'), payload.get('action'), payload.get('volume'),
         payload.get('price'), payload.get('sl'), payload.get('tp'),
         payload.get('provider_ticket'), int(time.time()), json.dumps(expected))
    )
    conn.commit()
    return expected


def record_execution(conn, payload):
    """Consumer reported an outcome. REJECTED raises an incident immediately --
    this is the path that was previously a bare print() to nowhere."""
    c = conn.cursor()
    status = payload.get('status')
    consumer_id = payload.get('consumer_id')
    provider_ticket = payload.get('provider_ticket')
    signal_id = payload.get('signal_id')

    c.execute(
        """INSERT OR REPLACE INTO copier_executions
           (signal_id, consumer_id, provider_ticket, status, local_ticket, filled_volume,
            fill_price, retcode, broker_comment, reason, latency_ms, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (signal_id, consumer_id, provider_ticket, status, payload.get('local_ticket'),
         payload.get('filled_volume'), payload.get('fill_price'), payload.get('retcode'),
         payload.get('broker_comment'), payload.get('reason'), payload.get('latency_ms'),
         int(time.time()))
    )
    conn.commit()

    name = _instance_name(c, consumer_id)

    if status == 'REJECTED':
        code = payload.get('retcode') or 0
        detail = {
            'provider': _provider_desc(c, signal_id, provider_ticket),
            'consumer': f"{name} -- order rejected",
            'cause': retcode_hint(code) or 'broker rejected the order',
            'retcode': f"{code} {retcode_name(code)}",
            'broker': f'"{payload.get("broker_comment") or ""}"',
            'attempted': payload.get('attempted') or '',
            'action': 'none -- awaiting RETRY',
        }
        raise_incident(
            conn, 'COPY_REJECTED', 'CRITICAL', consumer_id, name, detail,
            dedupe_key=f"COPY_REJECTED:{consumer_id}:{provider_ticket}",
            signal_id=signal_id, provider_ticket=provider_ticket,
            fingerprint=f"{retcode_name(code)}:{name}:{payload.get('symbol') or '-'}",
            buttons=_buttons_for(c, consumer_id, allow_retry=True),
        )
    elif status == 'FILLED':
        # A fill clears any standing complaint about this trade on this consumer.
        for key in (f"COPY_REJECTED:{consumer_id}:{provider_ticket}",
                    f"COPY_MISSING:{consumer_id}:{provider_ticket}"):
            resolve_incident(conn, key, 'consumer reported FILLED', {
                'result': f"ticket {payload.get('local_ticket')} filled "
                          f"{payload.get('filled_volume')} @{payload.get('fill_price')}"
            })


def _instance_name(c, inst_id):
    try:
        c.execute("SELECT name FROM instances WHERE id = ?", (inst_id,))
        r = c.fetchone()
        return r[0] if r else f"Instance {inst_id}"
    except Exception:
        return f"Instance {inst_id}"


def _provider_desc(c, signal_id, provider_ticket):
    try:
        if signal_id:
            c.execute("""SELECT provider_id, action, symbol, volume, price, sl, tp, provider_ticket
                         FROM copier_signals WHERE signal_id = ?""", (signal_id,))
        else:
            c.execute("""SELECT provider_id, action, symbol, volume, price, sl, tp, provider_ticket
                         FROM copier_signals WHERE provider_ticket = ? ORDER BY sent_at DESC LIMIT 1""",
                      (provider_ticket,))
        r = c.fetchone()
        if not r:
            return f"ticket {provider_ticket}"
        pname = _instance_name(c, r[0])
        return (f"{pname} (id={r[0]}) {r[1]} {r[2]} {r[3]} @{r[4]} "
                f"sl={r[5]} tp={r[6]} ticket={r[7]}")
    except Exception:
        return f"ticket {provider_ticket}"


def _buttons_for(c, consumer_id, allow_retry=False, allow_close=False):
    """PROPFIRM consumers never get a RETRY button: a late unattended entry can
    breach a firm's rules, and that risk outweighs the missed copy."""
    try:
        c.execute("SELECT account_type FROM instances WHERE id = ?", (consumer_id,))
        r = c.fetchone()
        is_prop = bool(r and r[0] == 'PROPFIRM')
    except Exception:
        is_prop = True

    buttons = []
    if allow_retry and not is_prop:
        buttons.append(("RETRY", "retry"))
    if allow_close:
        buttons.append(("CLOSE NOW", "close"))
    buttons.append(("IGNORE", "ack"))
    return buttons


# --- RECONCILER -----------------------------------------------------------

def _load_ticket_map(inst_id):
    """Read a worker's provider_ticket -> local_ticket map. Read-only: the
    worker subprocess owns this file, we only observe it."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"ticket_map_{inst_id}.json")
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except Exception:
        return {}


def _consumer_config(c):
    """Copier config for every consumer, keyed by id."""
    out = {}
    try:
        c.execute("""SELECT id, name, copier_risk_type, copier_fixed_lot, copier_risk_multiplier,
                            symbol_mapping, trade_locked, account_type, path
                     FROM instances WHERE copier_role = 'CONSUMER'""")
        for r in c.fetchall():
            try:
                mapping = json.loads(r[5]) if r[5] else {}
            except Exception:
                mapping = {}
            out[r[0]] = {
                'id': r[0], 'name': r[1], 'risk_type': r[2] or 'FIXED',
                'fixed_lot': r[3] or 0.01, 'mult': r[4] or 1.0,
                'mapping': mapping, 'trade_locked': bool(r[6]),
                'account_type': r[7] or 'PERSONAL', 'path': r[8],
            }
    except sqlite3.OperationalError:
        pass
    return out


def _provider_ids(c):
    try:
        c.execute("SELECT id, name FROM instances WHERE copier_role = 'PROVIDER'")
        return c.fetchall()
    except sqlite3.OperationalError:
        return []


def _expected_volume(cfg, provider_volume):
    """None when the expectation isn't reproducible server-side: USD sizing
    depends on that terminal's own tick value, so we don't guess and don't alert."""
    rt = cfg['risk_type']
    if rt == 'FIXED':
        return cfg['fixed_lot']
    if rt == 'MULTIPLIER':
        return provider_volume * cfg['mult']
    return None


def _was_skipped(c, provider_ticket, consumer_id):
    """A copy the worker deliberately declined (news blackout, trade lock) is
    not a failure -- those already have their own notification."""
    try:
        c.execute("""SELECT status, reason FROM copier_executions
                     WHERE provider_ticket = ? AND consumer_id = ? ORDER BY updated_at DESC LIMIT 1""",
                  (provider_ticket, consumer_id))
        r = c.fetchone()
        if not r:
            return False, None
        return r[0] == 'SKIPPED', r[1]
    except Exception:
        return False, None


def _last_execution(c, provider_ticket, consumer_id):
    try:
        c.execute("""SELECT status, retcode, broker_comment, reason, signal_id FROM copier_executions
                     WHERE provider_ticket = ? AND consumer_id = ? ORDER BY updated_at DESC LIMIT 1""",
                  (provider_ticket, consumer_id))
        return c.fetchone()
    except Exception:
        return None


def _has_pending_block(c, consumer_id, ticket):
    try:
        c.execute("""SELECT 1 FROM blocked_copier_actions
                     WHERE instance_id = ? AND ticket = ? AND status = 'PENDING' LIMIT 1""",
                  (consumer_id, ticket))
        return c.fetchone() is not None
    except Exception:
        return False


def _heuristic_match(ppos, cons_positions, mapping, used):
    """Fallback for when the ticket map is stale (a worker crashed before saving
    it). Matches on mapped symbol + direction + a nearby open time. Deliberately
    conservative: a wrong match here would hide a real missing copy."""
    want_symbol = mapping.get(ppos['symbol'], ppos['symbol'])
    p_open = ppos.get('open_time') or 0
    for lt, cp in cons_positions.items():
        if lt in used or cp.get('magic') != COPIER_MAGIC:
            continue
        if cp['symbol'] != want_symbol or cp['type'] != ppos['type']:
            continue
        c_open = cp.get('open_time') or 0
        if p_open and c_open and abs(c_open - p_open) > 120:
            continue
        return lt, cp
    return None


def reconcile(conn, risk_payload):
    """One reconciliation pass. `risk_payload` is the poller's per-instance
    snapshot -- only ONLINE instances appear in it, which is exactly the set we
    are entitled to draw conclusions about."""
    c = conn.cursor()
    now = time.time()
    by_id = {r['id']: r for r in risk_payload}
    consumers = _consumer_config(c)
    providers = _provider_ids(c)

    # Track how long each consumer has been continuously online.
    with _state_lock:
        for cid in consumers:
            if cid in by_id:
                _consumer_online_since.setdefault(cid, now)
            else:
                _consumer_online_since.pop(cid, None)

    online_providers = [(pid, pname) for pid, pname in providers if pid in by_id]
    if not online_providers:
        # Provider offline: nothing can be concluded about the mirrors, and the
        # existing connection alert already covers the provider itself.
        return

    active_keys = set()
    scoped_consumers = set()

    for pid, pname in online_providers:
        prov = by_id[pid]
        prov_positions = {p['ticket']: p for p in prov.get('positions', [])}

        with _state_lock:
            for t in prov_positions:
                _provider_seen_at.setdefault(t, now)
                _provider_gone_at.pop(t, None)
            for t in list(_provider_seen_at):
                if t not in prov_positions:
                    _provider_gone_at.setdefault(t, now)
            # Forget long-closed tickets so these dicts stay bounded.
            for t in list(_provider_gone_at):
                if now - _provider_gone_at[t] > 3600:
                    _provider_gone_at.pop(t, None)
                    _provider_seen_at.pop(t, None)

        for cid, cfg in consumers.items():
            if cid not in by_id:
                continue  # offline; the connection alert owns this
            if now - _consumer_online_since.get(cid, now) < CONSUMER_SETTLE_SEC:
                continue
            scoped_consumers.add(cid)

            cons = by_id[cid]
            cons_positions = {p['ticket']: p for p in cons.get('positions', [])}
            tmap = _load_ticket_map(cid)
            reverse = {}
            for pt_str, lt in tmap.items():
                try:
                    reverse[int(lt)] = int(pt_str)
                except (TypeError, ValueError):
                    continue

            used = set()

            # --- A) every provider position should have a mirror ---
            for pt, ppos in prov_positions.items():
                seen_at = _provider_seen_at.get(pt, now)
                if now - seen_at < COPY_GRACE_SEC:
                    continue

                local = tmap.get(str(pt))
                if local is not None:
                    try:
                        local = int(local)
                    except (TypeError, ValueError):
                        local = None

                match = None
                if local is not None and local in cons_positions:
                    match = (local, cons_positions[local])
                if match is None:
                    match = _heuristic_match(ppos, cons_positions, cfg['mapping'], used)

                if match:
                    used.add(match[0])
                    _check_mirror_quality(conn, c, cfg, ppos, match[1], pt, active_keys)
                    continue

                # No mirror. Decide whether that is legitimate before alarming.
                skipped, _reason = _was_skipped(c, pt, cid)
                if skipped or cfg['trade_locked']:
                    continue

                key = f"COPY_MISSING:{cid}:{pt}"
                active_keys.add(key)

                last = _last_execution(c, pt, cid)
                if last and last[0] == 'REJECTED':
                    code = last[1] or 0
                    cause = f"order rejected -- {retcode_hint(code)}"
                    extra = {'retcode': f"{code} {retcode_name(code)}",
                             'broker': '"' + (last[2] or '') + '"'}
                    fp = f"{retcode_name(code)}:{cfg['name']}:{ppos['symbol']}"
                elif local is not None:
                    cause = "mirror was opened but is no longer live (closed early, or closed by hand)"
                    extra = {'mapped_ticket': local}
                    fp = f"MIRROR_CLOSED_EARLY:{cfg['name']}:{ppos['symbol']}"
                else:
                    cause = ("signal never executed -- this consumer never reported any outcome "
                             "(worker down, or the signal was never delivered)")
                    extra = {}
                    fp = f"NO_RESPONSE:{cfg['name']}:{ppos['symbol']}"

                age = int(now - seen_at)
                detail = {
                    'provider': f"{pname} (id={pid}) {ppos['type']} {ppos['symbol']} "
                                f"{ppos['volume']} @{ppos['price_open']} sl={ppos['sl']} "
                                f"tp={ppos['tp']} ticket={pt}",
                    'consumer': f"{cfg['name']} -- no matching position after {age}s",
                    'cause': cause,
                }
                detail.update(extra)
                detail['action'] = 'none -- awaiting RETRY'
                raise_incident(
                    conn, 'COPY_MISSING', 'CRITICAL', cid, cfg['name'], detail,
                    dedupe_key=key, signal_id=last[4] if last else None,
                    provider_ticket=pt, fingerprint=fp,
                    buttons=_buttons_for(c, cid, allow_retry=True),
                )

            # --- B) mirrors that outlived their provider position ---
            for lt, cpos in cons_positions.items():
                if cpos.get('magic') != COPIER_MAGIC:
                    continue  # manual or other-EA trade, not ours to police
                pt = reverse.get(lt)

                if pt is None:
                    opened = cpos.get('open_time') or 0
                    # Only complain once it has clearly outlived any in-flight map write.
                    if opened and (now - opened) < 300:
                        continue
                    key = f"ORPHAN_POSITION:{cid}:{lt}"
                    active_keys.add(key)
                    raise_incident(
                        conn, 'ORPHAN_POSITION', 'CRITICAL', cid, cfg['name'], {
                            'consumer': f"{cfg['name']} holds {cpos['type']} {cpos['symbol']} "
                                        f"{cpos['volume']} ticket={lt} P/L={cpos.get('profit')}",
                            'cause': 'copier-opened position with no entry in the ticket map -- '
                                     'the copier can never close it',
                            'action': 'close it manually or with CLOSE NOW',
                        },
                        dedupe_key=key,
                        fingerprint=f"ORPHAN:{cfg['name']}:{cpos['symbol']}",
                        buttons=_buttons_for(c, cid, allow_close=True),
                    )
                    continue

                if pt in prov_positions:
                    continue
                gone_at = _provider_gone_at.get(pt)
                if not gone_at or (now - gone_at) < CLOSE_GRACE_SEC:
                    continue
                if _has_pending_block(c, cid, lt):
                    continue  # the news blackout queue already owns this one

                key = f"CLOSE_NOT_MIRRORED:{cid}:{lt}"
                active_keys.add(key)
                last = _last_execution(c, pt, cid)
                cause = 'provider closed but the mirror is still open'
                if last and last[0] == 'REJECTED':
                    cause = f"close rejected -- {retcode_hint(last[1] or 0)}"
                raise_incident(
                    conn, 'CLOSE_NOT_MIRRORED', 'CRITICAL', cid, cfg['name'], {
                        'provider': f"{pname} closed ticket {pt} {int(now - gone_at)}s ago",
                        'consumer': f"{cfg['name']} still holds ticket {lt} {cpos['type']} "
                                    f"{cpos['symbol']} {cpos['volume']} P/L={cpos.get('profit')}",
                        'cause': cause,
                        'action': 'exposure is live and unmanaged -- CLOSE NOW',
                    },
                    dedupe_key=key, provider_ticket=pt,
                    fingerprint=f"CLOSE_NOT_MIRRORED:{cfg['name']}:{cpos['symbol']}",
                    buttons=_buttons_for(c, cid, allow_close=True),
                )

    _auto_resolve(conn, active_keys, scoped_consumers)


RECONCILER_TYPES = ('COPY_MISSING', 'CLOSE_NOT_MIRRORED', 'ORPHAN_POSITION',
                    'WRONG_DIRECTION', 'SIZE_MISMATCH', 'MISSING_SL')


def _auto_resolve(conn, active_keys, scoped_consumers):
    """Close incidents whose condition no longer holds. Scoped to the consumers
    actually evaluated this pass, so an offline consumer's incidents are never
    resolved merely because we couldn't see it."""
    if not scoped_consumers:
        return
    c = conn.cursor()
    types_ph = ",".join("?" * len(RECONCILER_TYPES))
    ids_ph = ",".join("?" * len(scoped_consumers))
    c.execute(
        f"""SELECT dedupe_key FROM copier_incidents
            WHERE status IN ('OPEN','ACKED') AND type IN ({types_ph})
              AND instance_id IN ({ids_ph})""",
        (*RECONCILER_TYPES, *scoped_consumers)
    )
    for (key,) in c.fetchall():
        if key not in active_keys:
            resolve_incident(conn, key, 'condition cleared on its own')


def _check_mirror_quality(conn, c, cfg, ppos, cpos, pt, active_keys):
    """The mirror exists -- but is it the right one?"""
    if cpos['type'] != ppos['type']:
        key = f"WRONG_DIRECTION:{cfg['id']}:{pt}"
        active_keys.add(key)
        raise_incident(
            conn, 'WRONG_DIRECTION', 'CRITICAL', cfg['id'], cfg['name'], {
                'provider': f"{ppos['type']} {ppos['symbol']} {ppos['volume']} ticket={pt}",
                'consumer': f"{cpos['type']} {cpos['symbol']} {cpos['volume']} ticket={cpos['ticket']}",
                'cause': 'mirror is on the opposite side of the provider',
                'action': 'close it -- this is hedging the master, not copying it',
            },
            dedupe_key=key, provider_ticket=pt,
            fingerprint=f"WRONG_DIRECTION:{cfg['name']}:{cpos['symbol']}",
            buttons=_buttons_for(c, cfg['id'], allow_close=True),
        )
        return

    expected = _expected_volume(cfg, ppos['volume'])
    if expected:
        actual = cpos['volume']
        drift = abs(actual - expected)
        # Conservative on purpose: broker min-lot and step clamping legitimately
        # move the size, and a noisy size alert would train you to ignore alerts.
        if drift > 0.01 and drift > expected * 0.25:
            key = f"SIZE_MISMATCH:{cfg['id']}:{pt}"
            active_keys.add(key)
            raise_incident(
                conn, 'SIZE_MISMATCH', 'WARN', cfg['id'], cfg['name'], {
                    'provider': f"{ppos['symbol']} {ppos['volume']} ticket={pt}",
                    'consumer': f"got {actual}, expected {round(expected, 3)} (mode={cfg['risk_type']})",
                    'cause': 'volume clamped by the broker min/step, or config drift',
                },
                dedupe_key=key, provider_ticket=pt,
                fingerprint=f"SIZE_MISMATCH:{cfg['name']}:{cpos['symbol']}",
            )

    if ppos.get('sl') and not cpos.get('sl'):
        key = f"MISSING_SL:{cfg['id']}:{pt}"
        active_keys.add(key)
        raise_incident(
            conn, 'MISSING_SL', 'WARN', cfg['id'], cfg['name'], {
                'provider': f"{ppos['symbol']} ticket={pt} sl={ppos['sl']}",
                'consumer': f"ticket={cpos['ticket']} has NO stop loss",
                'cause': 'SL was rejected at entry (stops level) or never applied',
                'action': 'set a stop manually -- this position is unprotected',
            },
            dedupe_key=key, provider_ticket=pt,
            fingerprint=f"MISSING_SL:{cfg['name']}:{cpos['symbol']}",
        )


# --- FAN-OUT SUMMARY ------------------------------------------------------

def send_fanout_summaries(conn):
    """One message per master trade instead of one per consumer.

    Replaces mt5_worker's per-consumer 'Copier Trade Executed' spam: with N
    consumers that was N messages and a missing (N+1)th was invisible. Here the
    denominator is explicit, so an incomplete fan-out is impossible to miss."""
    c = conn.cursor()
    cutoff = int(time.time()) - FANOUT_SUMMARY_SEC
    c.execute("""SELECT signal_id, symbol, action, volume, price, expected_consumers, sent_at
                 FROM copier_signals
                 WHERE summary_sent = 0 AND type = 'NEW_TRADE' AND sent_at <= ?
                 ORDER BY sent_at ASC LIMIT 20""", (cutoff,))
    rows = c.fetchall()

    for signal_id, symbol, action, volume, price, expected_json, sent_at in rows:
        try:
            expected = json.loads(expected_json) if expected_json else []
        except Exception:
            expected = []

        c.execute("""SELECT consumer_id, status, filled_volume, fill_price, retcode,
                            broker_comment, reason, latency_ms
                     FROM copier_executions WHERE signal_id = ?""", (signal_id,))
        execs = {r[0]: r for r in c.fetchall()}

        ok_parts, bad_parts, latencies = [], [], []
        for cid in expected:
            name = _instance_name(c, cid)
            e = execs.get(cid)
            if e is None:
                # Nobody reported: mark it so the ledger shows the gap explicitly.
                c.execute("""INSERT OR REPLACE INTO copier_executions
                             (signal_id, consumer_id, status, reason, updated_at)
                             VALUES (?,?,'TIMEOUT','no outcome reported',?)""",
                          (signal_id, cid, int(time.time())))
                bad_parts.append(f"❌ {name} — NO RESPONSE (worker down or signal not delivered)")
            elif e[1] == 'FILLED':
                ok_parts.append(f"{name} {e[2]}")
                if e[7]:
                    latencies.append(e[7])
            elif e[1] == 'SKIPPED':
                ok_parts.append(f"{name} skipped ({e[6] or 'blocked'})")
            elif e[1] == 'REJECTED':
                code = e[4] or 0
                bad_parts.append(f"❌ {name} — REJECTED {code} {retcode_name(code)} \"{e[5] or ''}\"")
            else:
                bad_parts.append(f"❌ {name} — {e[1]}")

        total = len(expected)
        filled = len(ok_parts)
        head = (f"{'✅' if not bad_parts else '🔴'} Mirrored {filled}/{total} — "
                f"{action} {symbol} {volume} @{price}")
        lines = [head]
        if ok_parts:
            lines.append("   " + " · ".join(ok_parts))
        lines.extend("   " + b for b in bad_parts)
        if latencies:
            lines.append(f"   avg fill {sum(latencies) / len(latencies) / 1000:.1f}s")

        _tg("\n".join(lines))
        c.execute("UPDATE copier_signals SET summary_sent = 1 WHERE signal_id = ?", (signal_id,))
        conn.commit()


# --- WORKER HEALTH --------------------------------------------------------

def report_worker_restart(conn, instance_id, instance_name, reason=None):
    """Called by copier_manager_thread each time it respawns a worker. A worker
    that keeps dying was previously invisible: the manager silently restarted it
    every 3s forever while nothing was copied."""
    now = time.time()
    with _state_lock:
        events = [t for t in _worker_restarts.get(instance_id, []) if now - t < 300]
        events.append(now)
        _worker_restarts[instance_id] = events
        count = len(events)

    if count > 3:
        raise_incident(
            conn, 'WORKER_DOWN', 'CRITICAL', instance_id, instance_name, {
                'consumer': f"{instance_name} worker restarted {count}x in the last 5 min",
                'cause': reason or 'worker exits immediately after start',
                'action': 'nothing is being copied to this instance -- check the terminal is '
                          'running, logged in, and that its path is correct',
                'log': f"logs/worker_{instance_id}.log",
            },
            dedupe_key=f"WORKER_DOWN:{instance_id}",
            fingerprint=f"WORKER_DOWN:{instance_name}",
        )


def has_restart_history(instance_id):
    """Cheap in-memory check so the manager loop doesn't open a DB connection
    every few seconds for workers that have never crashed."""
    return bool(_worker_restarts.get(instance_id))


def report_worker_healthy(conn, instance_id):
    """A worker that has stayed up clears its crash-loop incident."""
    now = time.time()
    with _state_lock:
        events = [t for t in _worker_restarts.get(instance_id, []) if now - t < 300]
        if events:
            _worker_restarts[instance_id] = events
            return
        _worker_restarts.pop(instance_id, None)
    resolve_incident(conn, f"WORKER_DOWN:{instance_id}", 'worker stayed up for 5 minutes')


# --- WARN DIGEST + DAILY HEARTBEAT ---------------------------------------

_last_digest_at = 0
DIGEST_INTERVAL_SEC = 15 * 60


def send_warn_digest(conn):
    """WARNs are never instant -- they batch into one message at most every
    15 min, and only when something is actually open."""
    global _last_digest_at
    now = time.time()
    if now - _last_digest_at < DIGEST_INTERVAL_SEC:
        return
    c = conn.cursor()
    c.execute("""SELECT instance_name, type, detail, COUNT(*) FROM copier_incidents
                 WHERE status = 'OPEN' AND severity = 'WARN' AND last_seen >= ?
                 GROUP BY instance_name, type""", (int(_last_digest_at or now - DIGEST_INTERVAL_SEC),))
    rows = c.fetchall()
    _last_digest_at = now
    if not rows:
        return

    lines = ["⚠️ Copier warnings (last 15 min)"]
    for inst_name, itype, detail_json, count in rows:
        try:
            detail = json.loads(detail_json)
        except Exception:
            detail = {}
        suffix = f" x{count}" if count > 1 else ""
        lines.append(f"• {inst_name} — {itype}{suffix}: {detail.get('consumer') or detail.get('cause') or ''}")

    c.execute("""SELECT COUNT(*) FROM blocked_copier_actions
                 WHERE status = 'PENDING' AND blocked_at < ?""", (int(now) - 1800,))
    stale = c.fetchone()
    if stale and stale[0]:
        lines.append(f"• {stale[0]} blocked action(s) pending over 30 min — resolve in the Blocked Actions panel")

    _tg("\n".join(lines))


def daily_rollover(conn, prev_date):
    """Footer yesterday's issue file and send the heartbeat.

    The heartbeat matters more than any single alert: this system's failure mode
    is silence, so a message that arrives every day is the only way silence can
    ever mean 'nothing broke' rather than 'the monitor is dead'."""
    c = conn.cursor()
    start = int(datetime.strptime(prev_date, "%Y-%m-%d").timestamp())
    end = start + 86400

    c.execute("SELECT COUNT(*), COALESCE(SUM(json_array_length(expected_consumers)), 0) FROM copier_signals WHERE sent_at >= ? AND sent_at < ?", (start, end))
    row = c.fetchone() or (0, 0)
    signals, expected = row[0] or 0, row[1] or 0

    c.execute("""SELECT status, COUNT(*) FROM copier_executions
                 WHERE updated_at >= ? AND updated_at < ? GROUP BY status""", (start, end))
    by_status = dict(c.fetchall())
    mirrored = by_status.get('FILLED', 0)
    rejected = by_status.get('REJECTED', 0)

    c.execute("""SELECT instance_name, type, dedupe_key FROM copier_incidents
                 WHERE status IN ('OPEN','ACKED')""")
    open_incidents = [f"{t} {n} ({k})" for n, t, k in c.fetchall()]

    stats = {'signals': signals, 'mirrored': mirrored, 'expected': expected,
             'open_incidents': open_incidents}
    issue_log.finalize_day(prev_date, stats)

    summary = issue_log.day_summary(prev_date)
    healthy = rejected == 0 and not open_incidents and summary['critical'] == 0
    lines = [f"{'💚' if healthy else '⚠️'} Copier — {datetime.strptime(prev_date, '%Y-%m-%d').strftime('%a %d %b')}"]
    lines.append(f"Signals: {signals}   Mirrored: {mirrored}/{expected}   "
                 f"Rejections: {rejected}   Issues: {summary['issues']} ({summary['resolved']} resolved)")
    for fp, count in sorted(summary['fingerprints'].items(), key=lambda x: -x[1])[:3]:
        if count > 1:
            lines.append(f"⚠️ recurring: {fp} x{count}")
    if open_incidents:
        lines.append(f"Still open: {len(open_incidents)} — {open_incidents[0]}")
    lines.append(f"Log: logs/issues_{prev_date}.txt")
    _tg("\n".join(lines))


def purge_old_rows(conn):
    """Ledger rows older than 30 days are dead weight; the issue log is the
    long-term record."""
    cutoff = int(time.time()) - 30 * 86400
    c = conn.cursor()
    try:
        c.execute("DELETE FROM copier_executions WHERE updated_at < ?", (cutoff,))
        c.execute("DELETE FROM copier_signals WHERE sent_at < ?", (cutoff,))
        c.execute("DELETE FROM copier_incidents WHERE status = 'RESOLVED' AND resolved_at < ?", (cutoff,))
        conn.commit()
    except Exception:
        pass


# --- TELEGRAM BUTTON ACTIONS ---------------------------------------------

def handle_action(conn, action, incident_id):
    """RETRY / CLOSE NOW / IGNORE from a Telegram inline button.
    Returns a short string for the callback toast."""
    c = conn.cursor()
    c.execute("""SELECT type, instance_id, instance_name, signal_id, provider_ticket, detail, status
                 FROM copier_incidents WHERE id = ?""", (incident_id,))
    row = c.fetchone()
    if not row:
        return "Unknown incident"
    itype, inst_id, inst_name, signal_id, provider_ticket, detail_json, status = row
    if status == 'RESOLVED':
        return "Already resolved"

    if action == 'ack':
        c.execute("UPDATE copier_incidents SET status = 'ACKED' WHERE id = ?", (incident_id,))
        conn.commit()
        issue_log.log_resolution(itype, inst_name, inst_id, signal_id,
                                 {'via': 'IGNORE (acknowledged from Telegram)'})
        return "Ignored"

    c.execute("SELECT path, account_type FROM instances WHERE id = ?", (inst_id,))
    inst = c.fetchone()
    if not inst:
        return "Instance not found"
    inst_path, account_type = inst

    if action == 'close':
        try:
            detail = json.loads(detail_json)
        except Exception:
            detail = {}
        ticket = _ticket_from_key(c, incident_id)
        if not ticket:
            return "No ticket on this incident"
        ok, err = _close_position(inst_path, ticket, None)
        if ok:
            resolve_incident(conn, _dedupe_of(c, incident_id), 'CLOSE NOW (Telegram button)',
                             {'result': f"closed ticket {ticket}"})
            return "Closed"
        return f"Close failed: {err}"

    if action == 'retry':
        if account_type == 'PROPFIRM':
            # Belt and braces: the button isn't offered for prop accounts, but a
            # stale message could still deliver one.
            return "RETRY is disabled on prop firm accounts"
        c.execute("""SELECT symbol, action, volume, sl, tp FROM copier_signals
                     WHERE signal_id = ? OR provider_ticket = ? ORDER BY sent_at DESC LIMIT 1""",
                  (signal_id, provider_ticket))
        sig = c.fetchone()
        if not sig:
            return "Original signal not found"
        symbol, act, volume, sl, tp = sig
        try:
            cfg = _consumer_config(c).get(inst_id, {})
            mapped = cfg.get('mapping', {}).get(symbol, symbol)
            ticket = _execute_trade(mapped, (act or 'BUY').lower(), sl or 0, tp or 0,
                                    volume, 0, instance_path=inst_path,
                                    magic=COPIER_MAGIC, comment="")
        except Exception as e:
            return f"Retry error: {e}"
        if ticket:
            resolve_incident(conn, _dedupe_of(c, incident_id), 'RETRY (Telegram button)',
                             {'result': f"filled as ticket {ticket}"})
            return "Retried"
        return "Retry failed -- see the log"

    return "Unknown action"


def _dedupe_of(c, incident_id):
    c.execute("SELECT dedupe_key FROM copier_incidents WHERE id = ?", (incident_id,))
    r = c.fetchone()
    return r[0] if r else ""


def _ticket_from_key(c, incident_id):
    """CLOSE-able incidents encode the *local* ticket as the last key segment."""
    key = _dedupe_of(c, incident_id)
    try:
        return int(key.rsplit(":", 1)[-1])
    except (ValueError, IndexError):
        return None


def open_incidents(conn, limit=100):
    """For the /copier UI panel."""
    c = conn.cursor()
    c.execute("""SELECT id, type, severity, instance_id, instance_name, signal_id,
                        provider_ticket, fingerprint, detail, first_seen, last_seen, status
                 FROM copier_incidents WHERE status IN ('OPEN','ACKED')
                 ORDER BY first_seen DESC LIMIT ?""", (limit,))
    out = []
    for r in c.fetchall():
        try:
            detail = json.loads(r[8])
        except Exception:
            detail = {}
        out.append({
            'id': r[0], 'type': r[1], 'severity': r[2], 'instance_id': r[3],
            'instance_name': r[4], 'signal_id': r[5], 'provider_ticket': r[6],
            'fingerprint': r[7], 'detail': detail, 'first_seen': r[9],
            'last_seen': r[10], 'status': r[11],
        })
    return out
