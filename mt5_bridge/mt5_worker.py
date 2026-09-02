import argparse
import time
import json
import os
import threading
import urllib.request
import urllib.parse
import uuid
import zmq
import news_calendar

# Attempt to import mt5, handle gracefully if not available in this env
try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COPIER_MAGIC = 777888

# Retcodes worth another attempt: transient pricing/queue conditions, not
# configuration problems. Anything else (invalid volume, no money, invalid
# stops) will fail identically on a retry, so we report it instead.
RETRYABLE_RETCODES = {10004, 10011, 10012, 10020, 10021, 10024}
MAX_ORDER_ATTEMPTS = 3

# A restarted consumer replays only signals this recent. Older ones are stale:
# entering a trade minutes late is its own risk, and the reconciler will flag
# the gap anyway rather than acting on it unattended.
REPLAY_WINDOW_SEC = 120


def _post(path, payload, as_json=True):
    """Fire-and-forget report to app_server. Never blocks the trading loop and
    never raises -- reporting must not be able to break copying."""
    def _send():
        try:
            url = f"http://127.0.0.1:5000{path}"
            if as_json:
                data = json.dumps(payload).encode()
                req = urllib.request.Request(url, data=data,
                                             headers={"Content-Type": "application/json"})
            else:
                data = urllib.parse.urlencode(payload).encode()
                req = urllib.request.Request(url, data=data)
            urllib.request.urlopen(req, timeout=3)
        except Exception:
            pass
    threading.Thread(target=_send, daemon=True).start()


def notify_ui(msg):
    _post("/api/internal_notify", {"msg": msg}, as_json=False)


def report_signal(payload):
    """Tell the server a signal went out, so it knows who *should* mirror it."""
    _post("/api/copier/signal", payload)


def report_execution(args, status, signal_id=None, provider_ticket=None, **kw):
    """Report every outcome -- FILLED, REJECTED, SKIPPED -- for one consumer.

    This is the path that previously did not exist: a rejected copy only ever
    reached a print() on a console nobody watches, so a failed mirror was
    completely silent.
    """
    payload = {
        "consumer_id": args.id,
        "signal_id": signal_id,
        "provider_ticket": provider_ticket,
        "status": status,
    }
    payload.update(kw)
    _post("/api/copier/execution", payload)


def report_blocked_action(args, action_type, ticket, symbol, reason, volume=None, sl=None, tp=None):
    """Tells the backend a CLOSE/MODIFY was blocked by a news blackout so it
    can be queued in the UI's Blocked Actions table for manual resolution
    (the master's own event is fire-and-forget over ZMQ, no auto-replay)."""
    _post("/api/news/blocked_actions", {
        "instance_id": args.id, "instance_name": f"Instance {args.id}",
        "action_type": action_type, "ticket": ticket, "symbol": symbol,
        "volume": volume, "sl": sl, "tp": tp, "reason": reason,
    })


# --- PROVIDER -------------------------------------------------------------

def _provider_state_path(instance_id):
    return os.path.join(BASE_DIR, f"provider_state_{instance_id}.json")


def load_provider_state(instance_id):
    """Deal tickets already routed, persisted across restarts.

    Without this, a provider restart re-read its own last deal (history_deals_get
    is inclusive of the from-time) and re-emitted it, so every consumer opened a
    duplicate trade -- and because the ticket map was then overwritten by the
    second copy, the first became an orphan the copier could never close.

    Returns (seen_tickets, last_deal_time, is_first_boot). On a first boot there
    is no state file, so provider_loop must seed seen_tickets from history --
    see the comment there.
    """
    try:
        with open(_provider_state_path(instance_id), 'r') as f:
            state = json.load(f)
            return set(state.get("seen_tickets", [])), state.get("last_deal_time", 0), False
    except Exception:
        return set(), 0, True


def save_provider_state(instance_id, seen_tickets, last_deal_time):
    try:
        # Bounded: only recent tickets can plausibly be re-read from history.
        recent = sorted(seen_tickets)[-500:]
        with open(_provider_state_path(instance_id), 'w') as f:
            json.dump({"seen_tickets": recent, "last_deal_time": last_deal_time}, f)
    except Exception:
        pass


def provider_loop(push_socket, args):
    print("[PROVIDER] Starting polling loop...")

    seen_tickets, saved_time, first_boot = load_provider_state(args.id)

    # Initialize last_deal_time using integer timestamp to completely bypass datetime timezone drift bugs
    deals = mt5.history_deals_get(0, 2147483647)
    if deals:
        deals = sorted(deals, key=lambda x: x.time)
        last_deal_time = deals[-1].time
        if first_boot:
            # First run after an upgrade: there is no state file yet, so without
            # this seen_tickets would be empty and the inclusive
            # history_deals_get(last_deal_time, ...) below would treat the most
            # recent deal as brand new and re-route it -- telling every consumer
            # to open a trade that is already open. Seed from history so the
            # existing book is never re-announced.
            seen_tickets = {d.ticket for d in deals[-500:]}
            save_provider_state(args.id, seen_tickets, last_deal_time)
            print(f"[PROVIDER] First boot: seeded {len(seen_tickets)} historical deal(s); "
                  f"existing positions will not be re-routed.")
    else:
        # Fallback to current broker time if account has 0 history deals
        last_deal_time = 0
        symbols = mt5.symbols_get()
        if symbols:
            for s in symbols:
                if s.visible:
                    tick = mt5.symbol_info_tick(s.name)
                    if tick and tick.time > 0:
                        last_deal_time = tick.time
                        break

    if saved_time:
        last_deal_time = max(last_deal_time, saved_time)

    active_positions_cache = {}
    dirty = False
    last_save = time.time()

    def route(payload):
        """Stamp, publish, and register a signal in one place."""
        payload["signal_id"] = uuid.uuid4().hex[:12]
        payload["sent_at"] = time.time()
        push_socket.send_json(payload)
        report_signal({**payload, "provider_id": args.id})
        return payload["signal_id"]

    while True:
        # Polling using integers (broker time posix timestamps) is 100% robust
        current_deals = mt5.history_deals_get(last_deal_time, 2147483647)

        if current_deals:
            # Sort deals by time to process in order
            current_deals = sorted(current_deals, key=lambda x: x.time)
            for deal in current_deals:
                if deal.ticket not in seen_tickets:
                    seen_tickets.add(deal.ticket)
                    dirty = True

                    if deal.time > last_deal_time:
                        last_deal_time = deal.time

                    # We only care about new position entries
                    if deal.entry == mt5.DEAL_ENTRY_IN:
                        # Fetch the active position to get the SL and TP
                        # (since market execution deals often don't have SL/TP at execution time, but the position might)
                        positions = mt5.positions_get(ticket=deal.position_id)
                        sl = positions[0].sl if positions and len(positions) > 0 else 0.0
                        tp = positions[0].tp if positions and len(positions) > 0 else 0.0

                        sid = route({
                            "type": "NEW_TRADE",
                            "symbol": deal.symbol,
                            "action": "BUY" if deal.type == mt5.DEAL_TYPE_BUY else "SELL",
                            "volume": deal.volume,
                            "price": deal.price,
                            "sl": sl,
                            "tp": tp,
                            "provider_ticket": deal.position_id
                        })
                        print(f"[PROVIDER] Routed Trade {sid}: {deal.symbol} (Vol: {deal.volume})")
                    elif deal.entry in [mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY]:
                        # Volume of the remaining provider position, so consumers
                        # can mirror a PARTIAL close proportionally instead of
                        # closing their whole position.
                        remaining = mt5.positions_get(ticket=deal.position_id)
                        remaining_vol = remaining[0].volume if remaining else 0.0

                        sid = route({
                            "type": "CLOSE_TRADE",
                            "symbol": deal.symbol,
                            "action": "BUY" if deal.type == mt5.DEAL_TYPE_BUY else "SELL",  # OUT deal for BUY position is SELL
                            "volume": deal.volume,
                            "remaining_volume": remaining_vol,
                            "provider_ticket": deal.position_id
                        })
                        print(f"[PROVIDER] Routed Close {sid}: {deal.symbol} "
                              f"(Vol: {deal.volume}, Remaining: {remaining_vol}, PosID: {deal.position_id})")

        # Track SL/TP Modifications
        positions = mt5.positions_get()
        current_positions = {}
        if positions:
            for p in positions:
                current_positions[p.ticket] = {"sl": p.sl, "tp": p.tp}

                if p.ticket in active_positions_cache:
                    cached = active_positions_cache[p.ticket]
                    # Check if SL or TP changed
                    if abs(cached["sl"] - p.sl) > 0.00001 or abs(cached["tp"] - p.tp) > 0.00001:
                        route({
                            "type": "MODIFY_TRADE",
                            "provider_ticket": p.ticket,
                            "sl": p.sl,
                            "tp": p.tp
                        })
                        print(f"[PROVIDER] Routed Modification: PosID {p.ticket} (SL: {p.sl}, TP: {p.tp})")

        active_positions_cache = current_positions

        # Persist at most once a second, and only when something changed.
        if dirty and time.time() - last_save > 1:
            save_provider_state(args.id, seen_tickets, last_deal_time)
            dirty = False
            last_save = time.time()

        # 10ms sleep for ultra-low latency without 100% CPU lock
        time.sleep(0.01)


# --- CONSUMER -------------------------------------------------------------

def load_ticket_map(instance_id):
    file_path = os.path.join(BASE_DIR, f"ticket_map_{instance_id}.json")
    if os.path.exists(file_path):
        try:
            with open(file_path, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_ticket_map(instance_id, mapping):
    with open(os.path.join(BASE_DIR, f"ticket_map_{instance_id}.json"), "w") as f:
        json.dump(mapping, f)


def ensure_symbol(symbol):
    """A symbol that isn't in Market Watch returns no tick and the copy fails.
    Selecting it is the actual fix, and is the single most common cause of a
    consumer silently missing trades that others took."""
    tick = mt5.symbol_info_tick(symbol)
    if tick:
        return tick
    if mt5.symbol_select(symbol, True):
        return mt5.symbol_info_tick(symbol)
    return None


def normalize_volume(symbol, volume):
    """Clamp to the broker's min/max and snap to its volume step.

    Previously only the USD risk mode did this; FIXED and MULTIPLIER just did
    round(v, 2), so a broker with a 0.1 min lot or a 0.001 step rejected every
    order with retcode 10014 -- silently.
    """
    info = mt5.symbol_info(symbol)
    if not info:
        return round(volume, 2), "no symbol info"

    step = info.volume_step or 0.01
    vmin = info.volume_min or step
    vmax = info.volume_max or 1000.0

    snapped = round(round(volume / step) * step, 8)
    if snapped < vmin:
        snapped = vmin
    if snapped > vmax:
        snapped = vmax

    # Match the step's decimal precision so floats don't reintroduce 0.30000000004
    decimals = max(0, len(str(step).split('.')[-1].rstrip('0'))) if '.' in str(step) else 0
    snapped = round(snapped, decimals or 2)

    note = f"step={step} min={vmin} max={vmax}"
    if abs(snapped - volume) > 1e-9:
        note = f"requested {round(volume, 4)} -> {snapped} ({note})"
    return snapped, note


def _send_with_fallbacks(request):
    """Try each filling mode, then retry transient failures.

    Returns the last result, which may be None -- mt5.order_send() returns None
    on some errors and the old code dereferenced .retcode on it, throwing an
    AttributeError that the loop swallowed and the signal was lost.
    """
    result = None
    for attempt in range(MAX_ORDER_ATTEMPTS):
        for filling in (mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN):
            request["type_filling"] = filling
            result = mt5.order_send(request)
            if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
                return result
            if result is not None and result.retcode != mt5.TRADE_RETCODE_INVALID_FILL:
                break  # a non-filling problem: no point cycling filling modes

        if result is None or result.retcode not in RETRYABLE_RETCODES:
            return result

        time.sleep(0.2 * (attempt + 1))
        # Refresh the price for a market order before retrying.
        if request.get("action") == mt5.TRADE_ACTION_DEAL:
            tick = mt5.symbol_info_tick(request["symbol"])
            if tick:
                is_buy = request["type"] == mt5.ORDER_TYPE_BUY
                request["price"] = tick.ask if is_buy else tick.bid
    return result


def execute_trade(action, symbol, volume, sl, tp):
    """Returns a dict describing the outcome -- never a bare None -- so the
    caller can report exactly why a copy failed."""
    tick = ensure_symbol(symbol)
    if not tick:
        return {"ok": False, "retcode": 0, "comment": "no tick data / symbol not available",
                "attempted": f"symbol={symbol}", "volume": volume}

    norm_volume, vol_note = normalize_volume(symbol, volume)
    order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL
    price = tick.ask if action == "BUY" else tick.bid

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": float(norm_volume),
        "type": order_type,
        "price": price,
        "sl": float(sl),
        "tp": float(tp),
        "deviation": 20,
        "magic": COPIER_MAGIC,
        "comment": "",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = _send_with_fallbacks(request)
    attempted = f"volume={norm_volume} {vol_note} sl={sl} tp={tp}"

    if result is None:
        err = mt5.last_error()
        print(f"[CONSUMER] Order failed: order_send returned None ({err})")
        return {"ok": False, "retcode": 0, "comment": f"order_send returned None {err}",
                "attempted": attempted, "volume": norm_volume}

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"[CONSUMER] Order failed: {result.comment} (Retcode: {result.retcode})")
        # If stops were the problem, retry once bare so at least the exposure
        # matches the master -- a mirror with no SL beats no mirror at all, and
        # the reconciler raises MISSING_SL so it can't pass unnoticed.
        if result.retcode == mt5.TRADE_RETCODE_INVALID_STOPS and (sl or tp):
            request["sl"] = 0.0
            request["tp"] = 0.0
            retry = _send_with_fallbacks(request)
            if retry is not None and retry.retcode == mt5.TRADE_RETCODE_DONE:
                print(f"[CONSUMER] Order executed WITHOUT stops: Ticket {retry.order}")
                return {"ok": True, "ticket": retry.order, "retcode": retry.retcode,
                        "comment": "filled without SL/TP (invalid stops)",
                        "volume": norm_volume, "price": retry.price,
                        "attempted": attempted, "no_stops": True}
        return {"ok": False, "retcode": result.retcode, "comment": result.comment,
                "attempted": attempted, "volume": norm_volume}

    print(f"[CONSUMER] Order executed successfully: Ticket {result.order}")
    return {"ok": True, "ticket": result.order, "retcode": result.retcode,
            "comment": result.comment, "volume": norm_volume, "price": result.price,
            "attempted": attempted}


def close_trade(ticket, volume):
    position = mt5.positions_get(ticket=ticket)
    if not position:
        print(f"[CONSUMER] Position {ticket} not found for closure.")
        return {"ok": False, "retcode": 0, "comment": "position not found"}

    position = position[0]
    tick = ensure_symbol(position.symbol)
    if not tick:
        return {"ok": False, "retcode": 0, "comment": "no tick data"}

    close_volume = min(float(volume or position.volume), position.volume)
    order_type = mt5.ORDER_TYPE_SELL if position.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
    price = tick.bid if position.type == mt5.POSITION_TYPE_BUY else tick.ask

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": position.symbol,
        "volume": close_volume,
        "type": order_type,
        "position": ticket,
        "price": price,
        "deviation": 20,
        "magic": COPIER_MAGIC,
        "comment": "",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = _send_with_fallbacks(request)
    if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"[CONSUMER] Trade Closed: {ticket} ({close_volume})")
        return {"ok": True, "ticket": ticket, "volume": close_volume,
                "retcode": result.retcode, "comment": result.comment}

    code = result.retcode if result is not None else 0
    comment = result.comment if result is not None else f"order_send returned None {mt5.last_error()}"
    print(f"[CONSUMER] Close Failed: {code} {comment}")
    return {"ok": False, "retcode": code, "comment": comment,
            "attempted": f"close volume={close_volume} of {position.volume}"}


def modify_trade(ticket, sl, tp):
    position = mt5.positions_get(ticket=ticket)
    if not position:
        print(f"[CONSUMER] Position {ticket} not found for modification.")
        return {"ok": False, "retcode": 0, "comment": "position not found"}

    position = position[0]
    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "symbol": position.symbol,
        "position": ticket,
        "sl": float(sl),
        "tp": float(tp)
    }

    result = mt5.order_send(request)
    if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"[CONSUMER] Trade Modified: {ticket} (SL: {sl}, TP: {tp})")
        return {"ok": True, "ticket": ticket, "retcode": result.retcode}

    code = result.retcode if result is not None else 0
    comment = result.comment if result is not None else f"order_send returned None {mt5.last_error()}"
    print(f"[CONSUMER] Modify Failed: {code} {comment}")
    return {"ok": False, "retcode": code, "comment": comment,
            "attempted": f"sl={sl} tp={tp}"}


def fetch_missed_signals(instance_id):
    """Signals published while this worker was restarting.

    ZeroMQ PUB drops messages to subscribers that aren't connected yet, and
    copier_manager_thread respawns a worker on *any* config edit -- so an edit
    made while the master was entering a trade lost that trade permanently, on
    that consumer only. This closes that window on startup.
    """
    try:
        url = (f"http://127.0.0.1:5000/api/copier/signals?consumer_id={instance_id}"
               f"&since={int(time.time() - REPLAY_WINDOW_SEC)}")
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.loads(resp.read().decode()).get("signals", [])
    except Exception as e:
        print(f"[CONSUMER] Could not fetch missed signals: {e}")
        return []


def consumer_loop(sub_socket, args):
    print(f"[CONSUMER] Subscribed and waiting for signals. Risk: {args.risk_type}")
    ticket_map = load_ticket_map(args.id)
    is_propfirm = args.account_type == "PROPFIRM"
    news_cache = {}

    def check_blocked(symbol):
        """Only touched for PropFirm instances. Returns a human-readable
        block reason, or None if not currently blocked."""
        windows_payload = news_calendar.get_cached_windows(news_cache)
        blocked, window = news_calendar.is_blocked_now(
            symbol, windows_payload,
            before_sec=args.news_before_min * 60, after_sec=args.news_after_min * 60
        )
        if not blocked:
            return None
        if window is None:
            return "news feed FAILED (fail-closed)"
        return f"{window['currency']} news blackout: {window['title']}"

    def handle(msg):
        mtype = msg.get("type")
        sid = msg.get("signal_id")
        pt = str(msg.get("provider_ticket"))
        sent_at = msg.get("sent_at")
        latency_ms = int((time.time() - sent_at) * 1000) if sent_at else None

        if mtype == "NEW_TRADE":
            print(f"[CONSUMER] Received Signal: {msg}")

            # Dedupe: a provider restart can re-announce a trade, and without
            # this the second copy overwrote the ticket map entry and orphaned
            # the first position -- one the copier could then never close.
            if pt in ticket_map:
                print(f"[CONSUMER] Duplicate NEW_TRADE for provider ticket {pt}, ignoring.")
                report_execution(args, "SKIPPED", sid, msg.get("provider_ticket"),
                                 reason="duplicate signal (already mirrored)",
                                 symbol=msg.get("symbol"))
                return

            if args.trade_locked:
                print(f"[CONSUMER] BLOCKED NEW_TRADE {msg.get('symbol')}: instance is trade-locked")
                notify_ui(f"🔒 BLOCKED (Trade Locked): NEW {msg.get('action')} {msg.get('symbol')} — instance is locked from trading.")
                report_execution(args, "SKIPPED", sid, msg.get("provider_ticket"),
                                 reason="instance trade-locked (profit ceiling)",
                                 symbol=msg.get("symbol"))
                return

            symbol = msg["symbol"]

            # Apply symbol mapping
            mapping = {}
            try:
                if getattr(args, 'symbol_mapping', None):
                    mapping = json.loads(args.symbol_mapping)
            except Exception as e:
                print(f"[CONSUMER] Error parsing symbol mapping: {e}")

            if symbol in mapping:
                print(f"[CONSUMER] Mapping symbol {symbol} -> {mapping[symbol]}")
                symbol = mapping[symbol]

            if is_propfirm:
                reason = check_blocked(symbol)
                if reason:
                    print(f"[CONSUMER] BLOCKED NEW_TRADE {symbol}: {reason}")
                    notify_ui(f"🚫 BLOCKED (PropFirm News Blackout): NEW {msg.get('action')} {symbol} — {reason}")
                    report_execution(args, "SKIPPED", sid, msg.get("provider_ticket"),
                                     reason=reason, symbol=symbol)
                    return

            action = msg["action"]
            provider_volume = msg["volume"]
            provider_price = msg["price"]
            provider_sl = msg["sl"]

            # Determine local volume
            calc_volume = provider_volume

            if args.risk_type == "FIXED":
                calc_volume = args.fixed_lot
            elif args.risk_type == "MULTIPLIER":
                calc_volume = provider_volume * args.risk_mult
            elif args.risk_type == "USD":
                # Dynamic USD risk calculation
                if provider_sl > 0:
                    sym_info = mt5.symbol_info(symbol)
                    if sym_info and sym_info.trade_tick_size > 0 and sym_info.trade_tick_value > 0:
                        dist_ticks = abs(provider_price - provider_sl) / sym_info.trade_tick_size
                        if dist_ticks > 0:
                            calc_volume = args.risk_usd / (dist_ticks * sym_info.trade_tick_value)

            # Clamping happens inside execute_trade for every mode now.
            res = execute_trade(action, symbol, calc_volume, msg["sl"], msg["tp"])

            if res.get("ok"):
                ticket_map[pt] = res["ticket"]
                save_ticket_map(args.id, ticket_map)
                report_execution(args, "FILLED", sid, msg.get("provider_ticket"),
                                 local_ticket=res["ticket"], filled_volume=res.get("volume"),
                                 fill_price=res.get("price"), latency_ms=latency_ms,
                                 symbol=symbol, retcode=res.get("retcode"),
                                 broker_comment=res.get("comment"))
                if res.get("no_stops"):
                    notify_ui(f"⚠️ Mirror opened WITHOUT SL/TP on {symbol} (broker rejected the stops) — ticket {res['ticket']}")
            else:
                report_execution(args, "REJECTED", sid, msg.get("provider_ticket"),
                                 retcode=res.get("retcode"), broker_comment=res.get("comment"),
                                 attempted=res.get("attempted"), symbol=symbol,
                                 latency_ms=latency_ms)

        elif mtype == "CLOSE_TRADE":
            print(f"[CONSUMER] Received Close Signal: {msg}")
            if pt not in ticket_map:
                print(f"[CONSUMER] Close ignored: provider_ticket {pt} not in map.")
                return
            sub_ticket = ticket_map[pt]
            pos = mt5.positions_get(ticket=sub_ticket)
            if not pos:
                # Already gone: drop the mapping so it can't linger as a false match.
                ticket_map.pop(pt, None)
                save_ticket_map(args.id, ticket_map)
                return

            if is_propfirm:
                reason = check_blocked(pos[0].symbol)
                if reason:
                    print(f"[CONSUMER] BLOCKED CLOSE_TRADE {pos[0].symbol} ticket {sub_ticket}: {reason}")
                    notify_ui(
                        f"🚫 BLOCKED (PropFirm News Blackout): CLOSE {pos[0].symbol} ticket {sub_ticket} — {reason}. "
                        f"⚠️ Provider closed this position but the mirror stays OPEN — resolve it from the Blocked Actions panel."
                    )
                    report_blocked_action(args, "CLOSE", sub_ticket, pos[0].symbol, reason, volume=pos[0].volume)
                    report_execution(args, "SKIPPED", sid, msg.get("provider_ticket"),
                                     reason=reason, symbol=pos[0].symbol)
                    return

            # Mirror a PARTIAL close proportionally: the provider tells us how
            # much of its position remains, so we close the same fraction rather
            # than dumping the whole mirror on a partial exit.
            closed_vol = msg.get("volume") or 0
            remaining = msg.get("remaining_volume") or 0
            total = closed_vol + remaining
            if remaining > 0 and total > 0:
                target = pos[0].volume * (closed_vol / total)
                target, _ = normalize_volume(pos[0].symbol, target)
            else:
                target = pos[0].volume

            res = close_trade(sub_ticket, target)
            if res.get("ok"):
                if remaining <= 0:
                    ticket_map.pop(pt, None)
                    save_ticket_map(args.id, ticket_map)
                report_execution(args, "FILLED", sid, msg.get("provider_ticket"),
                                 local_ticket=sub_ticket, filled_volume=res.get("volume"),
                                 latency_ms=latency_ms, symbol=pos[0].symbol)
            else:
                report_execution(args, "REJECTED", sid, msg.get("provider_ticket"),
                                 retcode=res.get("retcode"), broker_comment=res.get("comment"),
                                 attempted=res.get("attempted"), symbol=pos[0].symbol,
                                 local_ticket=sub_ticket, latency_ms=latency_ms)

        elif mtype == "MODIFY_TRADE":
            print(f"[CONSUMER] Received Modify Signal: {msg}")
            if pt not in ticket_map:
                print(f"[CONSUMER] Modify ignored: provider_ticket {pt} not in map.")
                return
            sub_ticket = ticket_map[pt]
            if is_propfirm:
                pos = mt5.positions_get(ticket=sub_ticket)
                if pos:
                    reason = check_blocked(pos[0].symbol)
                    if reason:
                        print(f"[CONSUMER] BLOCKED MODIFY_TRADE {pos[0].symbol} ticket {sub_ticket}: {reason}")
                        notify_ui(
                            f"🚫 BLOCKED (PropFirm News Blackout): MODIFY {pos[0].symbol} ticket {sub_ticket} — {reason}. "
                            f"Resolve it from the Blocked Actions panel once the window has passed."
                        )
                        report_blocked_action(args, "MODIFY", sub_ticket, pos[0].symbol, reason, sl=msg["sl"], tp=msg["tp"])
                        report_execution(args, "SKIPPED", sid, msg.get("provider_ticket"),
                                         reason=reason, symbol=pos[0].symbol)
                        return
            res = modify_trade(sub_ticket, msg["sl"], msg["tp"])
            if not res.get("ok"):
                report_execution(args, "REJECTED", sid, msg.get("provider_ticket"),
                                 retcode=res.get("retcode"), broker_comment=res.get("comment"),
                                 attempted=res.get("attempted"), local_ticket=sub_ticket)

    # Replay anything published while this worker was starting up.
    for missed in fetch_missed_signals(args.id):
        try:
            print(f"[CONSUMER] Replaying missed signal {missed.get('signal_id')}")
            handle(missed)
        except Exception as e:
            print(f"[CONSUMER] Error replaying signal: {e}")

    while True:
        try:
            msg = sub_socket.recv_json()
            handle(msg)
        except Exception as e:
            print(f"[CONSUMER] Error processing signal: {e}")
            # Report the crash rather than swallowing it, so a consumer that is
            # throwing on every signal is visible instead of merely quiet.
            try:
                report_execution(args, "REJECTED", None, None,
                                 broker_comment=f"worker exception: {e}")
            except Exception:
                pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", type=int, required=True)
    parser.add_argument("--path", type=str, required=True)
    parser.add_argument("--role", type=str, required=True, choices=["PROVIDER", "CONSUMER"])
    parser.add_argument("--risk_type", type=str, default="FIXED")
    parser.add_argument("--fixed_lot", type=float, default=0.01)
    parser.add_argument("--risk_usd", type=float, default=100.0)
    parser.add_argument("--risk_mult", type=float, default=1.0)
    parser.add_argument("--symbol_mapping", type=str, default='{}')
    parser.add_argument("--account_type", type=str, default="PERSONAL", choices=["PERSONAL", "PROPFIRM"])
    parser.add_argument("--news_before_min", type=float, default=2.0)
    parser.add_argument("--news_after_min", type=float, default=2.0)
    parser.add_argument("--trade_locked", type=int, default=0)

    args = parser.parse_args()

    if mt5 is None:
        print("MetaTrader5 python module not installed in this environment.")
        exit(1)

    print(f"[{args.role}] Initializing MT5 at {args.path}")
    if not mt5.initialize(path=args.path):
        print(f"[{args.role}] Failed to initialize MT5: {mt5.last_error()}")
        exit(1)

    context = zmq.Context()

    if args.role == "PROVIDER":
        # Connect PUSH socket to Router's PULL port 5555
        push_socket = context.socket(zmq.PUSH)
        push_socket.connect("tcp://127.0.0.1:5555")
        provider_loop(push_socket, args)

    elif args.role == "CONSUMER":
        # Connect SUB socket to Router's PUB port 5556
        sub_socket = context.socket(zmq.SUB)
        sub_socket.connect("tcp://127.0.0.1:5556")
        sub_socket.setsockopt_string(zmq.SUBSCRIBE, "")  # Subscribe to everything
        consumer_loop(sub_socket, args)
