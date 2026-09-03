"""Profit-lock decision ledger: what it cost to *not* arm.

The alert flow in app_server.py's poller offers an ARM button at 75% of an instance's
profit-lock target. Arming auto-closes the moment the full target is hit; ignoring it
leaves the trades running. Until now, ignoring it left no trace, so there was no way to
answer "was letting that run the right call?" -- the same judgement was made every few
days with zero feedback.

This module records the decision and grades it once the trades actually close.

What counts as an event
-----------------------
Only a genuine *crossing* of the full target. An alert that fires at the pre-alert level
and then fades never had money on the table, because ARM would never have triggered --
there is no counterfactual to measure, so nothing is recorded. The event is created at the
instant unrealized P&L crosses the target unarmed (the state machine's IDLE/APPROACHING ->
MISSED transitions), which is exactly the moment an armed instance would have closed flat.

The benchmark
-------------
`peak_floating_usd` is equity - balance at the crossing: precisely what an armed auto-close
would have banked, and the same quantity the % trigger itself is derived from, so the
trigger and the benchmark can never disagree. Grading compares it against what that same
set of positions went on to realize.

Armed events are recorded too, with armed=1. They are the control group: without them the
weekly report is a list of regrets with no baseline, and the question the whole feature
exists to answer ("should I just always arm?") stays unanswerable.
"""
import logging
import time

# Verdicts. Ordered worst -> best.
GAVE_IT_BACK = "GAVE_IT_BACK"   # cluster closed red: money in hand, finished at a loss
LEAKED = "LEAKED"               # closed green but under the benchmark: still left profit behind
RIGHT_CALL = "RIGHT_CALL"       # closed at or above the benchmark: holding paid


def _open_event(c, inst_id):
    c.execute(
        "SELECT id, peak_pct, peak_floating_usd FROM profit_lock_events "
        "WHERE instance_id = ? AND status = 'OPEN' ORDER BY id DESC LIMIT 1",
        (inst_id,)
    )
    return c.fetchone()


def record_cross(c, inst_id, date_str, target_pct, unrealized_pct, floating_usd,
                 start_equity, equity, balance, positions, armed=False):
    """Record that `inst_id` crossed its profit-lock target. Returns the event id.

    One open event per instance at a time. Unrealized P&L can cross the target, fade below
    the disarm level, and cross again the same day; making each crossing its own event would
    count the same positions two or three times and inflate the leak. A later crossing while
    an event is still unresolved raises that event's high-water benchmark instead, which is
    what "the best moment you passed on" actually means.
    """
    existing = _open_event(c, inst_id)
    if existing is not None:
        event_id, peak_pct, peak_usd = existing
        if floating_usd > (peak_usd or 0.0):
            c.execute(
                "UPDATE profit_lock_events SET peak_pct = ?, peak_floating_usd = ?, "
                "equity = ?, balance = ? WHERE id = ?",
                (max(unrealized_pct, peak_pct or 0.0), floating_usd, equity, balance, event_id)
            )
        return event_id

    c.execute(
        "INSERT INTO profit_lock_events "
        "(instance_id, date, crossed_at, target_pct, peak_pct, peak_floating_usd, "
        " start_equity, equity, balance, armed, ticket_count, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')",
        (inst_id, date_str, int(time.time()), target_pct, unrealized_pct, floating_usd,
         start_equity, equity, balance, 1 if armed else 0, len(positions))
    )
    event_id = c.lastrowid

    for p in positions:
        c.execute(
            "INSERT OR IGNORE INTO profit_lock_event_tickets "
            "(event_id, instance_id, ticket, symbol, floating_usd_at_cross) "
            "VALUES (?, ?, ?, ?, ?)",
            (event_id, inst_id, p.get("ticket"), p.get("symbol"), p.get("profit", 0.0))
        )

    logging.info(
        "profit-lock: instance %s crossed +%.2f%% (target +%.2f%%) %s, "
        "cluster of %d position(s) worth $%.2f -> event %d",
        inst_id, unrealized_pct, target_pct, "ARMED" if armed else "not armed",
        len(positions), floating_usd, event_id
    )
    return event_id


def verdict_for(peak_floating_usd, realized_usd):
    if realized_usd < 0:
        return GAVE_IT_BACK
    if realized_usd < (peak_floating_usd or 0.0):
        return LEAKED
    return RIGHT_CALL


def resolve_open_events(c, live_tickets_by_instance):
    """Grade every open event whose cluster has fully closed.

    Deliberately independent of the poller's in-memory profit_lock_state, which resets to
    IDLE on every app restart -- these rows are the durable record, so a restart mid-cluster
    loses nothing and the event still grades itself when the trades finally close.

    The join is ticket -> trade_history.position_id, NOT trade_history.ticket. A live
    position's ticket is its position identifier; trading_log/trade_history.ticket is the
    last OUT *deal*. Joining on ticket matches nothing and every event sits OPEN forever.
    """
    c.execute("SELECT id, instance_id, peak_floating_usd FROM profit_lock_events WHERE status = 'OPEN'")
    open_events = c.fetchall()
    resolved = 0

    for event_id, inst_id, peak_usd in open_events:
        c.execute(
            "SELECT ticket FROM profit_lock_event_tickets WHERE event_id = ?", (event_id,)
        )
        tickets = [r[0] for r in c.fetchall()]
        if not tickets:
            continue

        live = live_tickets_by_instance.get(inst_id)
        # No entry at all means the instance wasn't in this poll (offline). Absent data is
        # not evidence the trades closed, so leave the event open rather than grading it
        # against a cluster we simply couldn't see.
        if live is None:
            continue
        if any(t in live for t in tickets):
            continue

        placeholders = ",".join("?" * len(tickets))
        c.execute(
            f"SELECT position_id, profit, close_time_utc FROM trade_history "
            f"WHERE instance_id = ? AND position_id IN ({placeholders})",
            (inst_id, *tickets)
        )
        found = {r[0]: (r[1], r[2]) for r in c.fetchall()}

        # trade_history only refreshes on the history sync pass, so a just-closed cluster is
        # briefly closed-but-not-yet-recorded. Wait for the whole cluster rather than grading
        # against a partial sum, which would read as a leak that never happened.
        if len(found) < len(tickets):
            continue

        realized = sum(v[0] or 0.0 for v in found.values())
        closed_at = max((v[1] or 0) for v in found.values())

        for ticket, (profit, close_time) in found.items():
            c.execute(
                "UPDATE profit_lock_event_tickets SET realized_usd = ?, closed_at = ? "
                "WHERE event_id = ? AND ticket = ?",
                (profit, close_time, event_id, ticket)
            )

        verdict = verdict_for(peak_usd, realized)
        c.execute(
            "UPDATE profit_lock_events SET status = 'RESOLVED', resolved_at = ?, "
            "realized_usd = ?, verdict = ? WHERE id = ?",
            (int(closed_at or time.time()), realized, verdict, event_id)
        )
        resolved += 1
        logging.info(
            "profit-lock: event %d resolved %s -- benchmark $%.2f, realized $%.2f (leak $%.2f)",
            event_id, verdict, peak_usd or 0.0, realized, (peak_usd or 0.0) - realized
        )

    return resolved
