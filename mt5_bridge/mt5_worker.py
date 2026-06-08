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
    # Get current time to ignore old deals
    # Subtracting 1 second just to be safe on bounds
    last_deal_time = datetime.now() - timedelta(seconds=1)
    seen_tickets = set()
    
    while True:
        # Polling history deals
        now = datetime.now() + timedelta(seconds=1)
        deals = mt5.history_deals_get(last_deal_time, now)
        
        if deals:
            for deal in deals:
                if deal.ticket not in seen_tickets:
                    seen_tickets.add(deal.ticket)
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
                            "provider_ticket": deal.ticket
                        }
                        push_socket.send_json(payload)
                        print(f"[PROVIDER] Detected & Routed Trade: {payload['action']} {payload['symbol']} (Vol: {payload['volume']})")
                        
                        # Update last deal time so we don't query huge histories
                        # mt5 times are in posix timestamp (seconds)
                        dt = datetime.fromtimestamp(deal.time)
                        if dt > last_deal_time:
                            last_deal_time = dt
        
        # 10ms sleep for ultra-low latency without 100% CPU lock
        time.sleep(0.01)

def execute_trade(action, symbol, volume, sl, tp):
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        print(f"[CONSUMER] Failed to get tick for {symbol}")
        return
        
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
        print(f"[CONSUMER] Order failed: {result.comment}")
    else:
        print(f"[CONSUMER] Order executed successfully: Ticket {result.order}")

def consumer_loop(sub_socket, args):
    print(f"[CONSUMER] Subscribed and waiting for signals. Risk: {args.risk_type}")
    while True:
        try:
            msg = sub_socket.recv_json()
            if msg.get("type") == "NEW_TRADE":
                print(f"[CONSUMER] Received Signal: {msg}")
                
                symbol = msg["symbol"]
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
                execute_trade(action, symbol, calc_volume, msg["sl"], msg["tp"])
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
