import argparse
import time
import json
from datetime import datetime, timezone, timedelta
import zmq

# Attempt to import mt5, handle gracefully if not available in this env
try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

def provider_loop(push_socket):
    print("[PROVIDER] Starting polling loop...")
    
    # Initialize last_deal_time using integer timestamp to completely bypass datetime timezone drift bugs
    deals = mt5.history_deals_get(0, 2147483647)
    if deals:
        deals = sorted(deals, key=lambda x: x.time)
        last_deal_time = deals[-1].time
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
                        
    seen_tickets = set()
    active_positions_cache = {}
    
    while True:
        # Polling using integers (broker time posix timestamps) is 100% robust
        current_deals = mt5.history_deals_get(last_deal_time, 2147483647)
        
        if current_deals:
            # Sort deals by time to process in order
            current_deals = sorted(current_deals, key=lambda x: x.time)
            for deal in current_deals:
                if deal.ticket not in seen_tickets:
                    seen_tickets.add(deal.ticket)
                    
                    if deal.time > last_deal_time:
                        last_deal_time = deal.time
                        
                    # We only care about new position entries
                    if deal.entry == mt5.DEAL_ENTRY_IN:
                        # Fetch the active position to get the SL and TP 
                        # (since market execution deals often don't have SL/TP at execution time, but the position might)
                        positions = mt5.positions_get(ticket=deal.position_id)
                        sl = positions[0].sl if positions and len(positions)>0 else 0.0
                        tp = positions[0].tp if positions and len(positions)>0 else 0.0
                        
                        payload = {
                            "type": "NEW_TRADE",
                            "symbol": deal.symbol,
                            "action": "BUY" if deal.type == mt5.DEAL_TYPE_BUY else "SELL",
                            "volume": deal.volume,
                            "price": deal.price,
                            "sl": sl,
                            "tp": tp,
                            "provider_ticket": deal.position_id
                        }
                        push_socket.send_json(payload)
                        print(f"[PROVIDER] Detected & Routed Trade: {payload['action']} {payload['symbol']} (Vol: {payload['volume']})")
                    elif deal.entry in [mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY]:
                        payload = {
                            "type": "CLOSE_TRADE",
                            "symbol": deal.symbol,
                            "action": "BUY" if deal.type == mt5.DEAL_TYPE_BUY else "SELL", # OUT deal for BUY position is SELL
                            "volume": deal.volume,
                            "provider_ticket": deal.position_id
                        }
                        push_socket.send_json(payload)
                        print(f"[PROVIDER] Detected & Routed Close: {deal.symbol} (Vol: {deal.volume}, PosID: {deal.position_id})")
        
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
                        payload = {
                            "type": "MODIFY_TRADE",
                            "provider_ticket": p.ticket,
                            "sl": p.sl,
                            "tp": p.tp
                        }
                        push_socket.send_json(payload)
                        print(f"[PROVIDER] Detected & Routed Modification: PosID {p.ticket} (SL: {p.sl}, TP: {p.tp})")
        
        active_positions_cache = current_positions
        
        # 10ms sleep for ultra-low latency without 100% CPU lock
        time.sleep(0.01)

def load_ticket_map(instance_id):
    import os
    file_path = f"ticket_map_{instance_id}.json"
    if os.path.exists(file_path):
        try:
            with open(file_path, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_ticket_map(instance_id, mapping):
    with open(f"ticket_map_{instance_id}.json", "w") as f:
        json.dump(mapping, f)

def execute_trade(action, symbol, volume, sl, tp):
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        print(f"[CONSUMER] Failed to get tick for {symbol}")
        return None
        
    order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL
    price = tick.ask if action == "BUY" else tick.bid
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": float(volume),
        "type": order_type,
        "price": price,
        "sl": float(sl),
        "tp": float(tp),
        "deviation": 20,
        "magic": 777888, # Copier Magic
        "comment": "",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        # Retry with FOK
        request["type_filling"] = mt5.ORDER_FILLING_FOK
        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            # Retry with RETURN
            request["type_filling"] = mt5.ORDER_FILLING_RETURN
            result = mt5.order_send(request)

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"[CONSUMER] Order failed: {result.comment} (Retcode: {result.retcode})")
        return None
    else:
        print(f"[CONSUMER] Order executed successfully: Ticket {result.order}")
        
        def notify_ui():
            try:
                import urllib.request
                import urllib.parse
                data = urllib.parse.urlencode({"msg": f"✅ Copier Trade Executed!\nSymbol: {symbol}\nAction: {action.upper()}\nVolume: {volume}\nTicket: {result.order}"}).encode()
                req = urllib.request.Request("http://127.0.0.1:5000/api/internal_notify", data=data)
                urllib.request.urlopen(req, timeout=2)
            except Exception as e:
                pass
                
        import threading
        threading.Thread(target=notify_ui).start()
        
        return result.order

def close_trade(ticket, volume):
    position = mt5.positions_get(ticket=ticket)
    if not position:
        print(f"[CONSUMER] Position {ticket} not found for closure.")
        return
        
    position = position[0]
    tick = mt5.symbol_info_tick(position.symbol)
    if not tick:
        return
        
    order_type = mt5.ORDER_TYPE_SELL if position.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
    price = tick.bid if position.type == mt5.POSITION_TYPE_BUY else tick.ask
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": position.symbol,
        "volume": float(volume),
        "type": order_type,
        "position": ticket,
        "price": price,
        "deviation": 20,
        "magic": 777888,
        "comment": "",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        request["type_filling"] = mt5.ORDER_FILLING_FOK
        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            request["type_filling"] = mt5.ORDER_FILLING_RETURN
            result = mt5.order_send(request)
            
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"[CONSUMER] Trade Closed: {ticket}")
    else:
        print(f"[CONSUMER] Close Failed: {result.retcode}")

def modify_trade(ticket, sl, tp):
    position = mt5.positions_get(ticket=ticket)
    if not position:
        print(f"[CONSUMER] Position {ticket} not found for modification.")
        return
        
    position = position[0]
    
    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "symbol": position.symbol,
        "position": ticket,
        "sl": float(sl),
        "tp": float(tp)
    }
    
    result = mt5.order_send(request)
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"[CONSUMER] Trade Modified: {ticket} (SL: {sl}, TP: {tp})")
    else:
        print(f"[CONSUMER] Modify Failed: {result.retcode}")

def consumer_loop(sub_socket, args):
    print(f"[CONSUMER] Subscribed and waiting for signals. Risk: {args.risk_type}")
    ticket_map = load_ticket_map(args.id)
    
    while True:
        try:
            msg = sub_socket.recv_json()
            if msg.get("type") == "NEW_TRADE":
                print(f"[CONSUMER] Received Signal: {msg}")
                
                symbol = msg["symbol"]
                
                # Apply symbol mapping
                mapping = {}
                try:
                    if hasattr(args, 'symbol_mapping') and args.symbol_mapping:
                        mapping = json.loads(args.symbol_mapping)
                except Exception as e:
                    print(f"[CONSUMER] Error parsing symbol mapping: {e}")
                
                if symbol in mapping:
                    print(f"[CONSUMER] Mapping symbol {symbol} -> {mapping[symbol]}")
                    symbol = mapping[symbol]
                    
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
                                raw_vol = args.risk_usd / (dist_ticks * sym_info.trade_tick_value)
                                # Round to lot step
                                step = sym_info.volume_step
                                calc_volume = round(raw_vol / step) * step
                                if calc_volume < sym_info.volume_min:
                                    calc_volume = sym_info.volume_min
                                if calc_volume > sym_info.volume_max:
                                    calc_volume = sym_info.volume_max
                                    
                # Execute
                # We round to 2 decimals for MT5 standard volume
                calc_volume = round(calc_volume, 2)
                new_ticket = execute_trade(action, symbol, calc_volume, msg["sl"], msg["tp"])
                
                if new_ticket and "provider_ticket" in msg:
                    ticket_map[str(msg["provider_ticket"])] = new_ticket
                    save_ticket_map(args.id, ticket_map)
                    
            elif msg.get("type") == "CLOSE_TRADE":
                print(f"[CONSUMER] Received Close Signal: {msg}")
                pt = str(msg.get("provider_ticket"))
                if pt in ticket_map:
                    sub_ticket = ticket_map[pt]
                    pos = mt5.positions_get(ticket=sub_ticket)
                    if pos:
                        close_trade(sub_ticket, pos[0].volume)
                else:
                    print(f"[CONSUMER] Close ignored: provider_ticket {pt} not in map.")
                    
            elif msg.get("type") == "MODIFY_TRADE":
                print(f"[CONSUMER] Received Modify Signal: {msg}")
                pt = str(msg.get("provider_ticket"))
                if pt in ticket_map:
                    sub_ticket = ticket_map[pt]
                    modify_trade(sub_ticket, msg["sl"], msg["tp"])
                else:
                    print(f"[CONSUMER] Modify ignored: provider_ticket {pt} not in map.")
                    
        except Exception as e:
            print(f"[CONSUMER] Error processing signal: {e}")

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
        provider_loop(push_socket)
        
    elif args.role == "CONSUMER":
        # Connect SUB socket to Router's PUB port 5556
        sub_socket = context.socket(zmq.SUB)
        sub_socket.connect("tcp://127.0.0.1:5556")
        sub_socket.setsockopt_string(zmq.SUBSCRIBE, "") # Subscribe to everything
        consumer_loop(sub_socket, args)
