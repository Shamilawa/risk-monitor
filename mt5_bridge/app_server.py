import threading
import queue
import logging
import subprocess
import urllib.request
import json
import MetaTrader5 as mt5
from flask import Flask, request, jsonify, render_template, Response
import os
import requests
from dotenv import load_dotenv
import sqlite3
import random
import time
import webbrowser

load_dotenv()

# --- GLOBALS & STATE ---
clients = []
global_ngrok_url = "Starting Ngrok tunnel..."
global_mt5_status = False

recent_logs = []
MAX_RECENT_LOGS = 100

def notify_clients(event, data):
    for q in clients:
        q.put({"event": event, "data": data})

# --- LOGGING HANDLER ---
class SSEHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        recent_logs.append(msg)
        if len(recent_logs) > MAX_RECENT_LOGS:
            recent_logs.pop(0)
        notify_clients("log", msg)

# Setup Logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')

ch = logging.StreamHandler()
ch.setFormatter(formatter)
logger.addHandler(ch)

sse_handler = SSEHandler()
sse_handler.setFormatter(formatter)
logger.addHandler(sse_handler)

# --- FLASK APP ---
# Specify static and template folders to be in the current directory
flask_app = Flask(__name__, static_folder='static', template_folder='templates')
werk_log = logging.getLogger('werkzeug')
werk_log.setLevel(logging.ERROR)

# --- MT5 LOGIC ---
def calculate_volume(symbol, entry_price, sl_price, risk_usd):
    if not mt5.initialize():
        return 0.01
        
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        logging.error(f"Error: {symbol} not found in MT5")
        return 0.01
        
    mt5.symbol_select(symbol, True)
    tick_size = symbol_info.trade_tick_size
    tick_value = symbol_info.trade_tick_value
    
    points_to_sl = abs(entry_price - sl_price) / tick_size
    if points_to_sl == 0 or tick_value == 0:
        return 0.01
        
    risk_for_1_lot = points_to_sl * tick_value
    if risk_for_1_lot == 0:
        return 0.01
        
    volume = risk_usd / risk_for_1_lot
    step = symbol_info.volume_step
    min_vol = symbol_info.volume_min
    max_vol = symbol_info.volume_max
    
    volume = round(volume / step) * step
    if volume < min_vol: volume = min_vol
    if volume > max_vol: volume = max_vol
    
    return round(volume, 2)

def execute_trade(symbol, action_type, sl, tp, volume, entry_price, magic=999111, comment="TradingView Signal"):
    if not mt5.initialize():
        logging.error(f"MT5 initialization failed: {mt5.last_error()}")
        return None
        
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        logging.error(f"Failed to get tick for {symbol}")
        return None

    ask = tick.ask
    bid = tick.bid
    entry_price = float(entry_price)

    # Determine order type and price
    if action_type.lower() == 'buy':
        if entry_price > 0 and entry_price != ask:
            if ask > entry_price:
                order_type = mt5.ORDER_TYPE_BUY_LIMIT
            else:
                order_type = mt5.ORDER_TYPE_BUY_STOP
            price = entry_price
        else:
            order_type = mt5.ORDER_TYPE_BUY
            price = ask
            
    elif action_type.lower() == 'sell':
        if entry_price > 0 and entry_price != bid:
            if bid > entry_price:
                order_type = mt5.ORDER_TYPE_SELL_STOP
            else:
                order_type = mt5.ORDER_TYPE_SELL_LIMIT
            price = entry_price
        else:
            order_type = mt5.ORDER_TYPE_SELL
            price = bid
    else:
        logging.error(f"Unknown action type: {action_type}")
        return None
        
    is_pending = order_type in [mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP, mt5.ORDER_TYPE_SELL_LIMIT, mt5.ORDER_TYPE_SELL_STOP]
    action_req = mt5.TRADE_ACTION_PENDING if is_pending else mt5.TRADE_ACTION_DEAL

    request = {
        "action": action_req,
        "symbol": symbol,
        "volume": float(volume),
        "type": order_type,
        "price": price,
        "sl": float(sl),
        "tp": float(tp),
        "deviation": 20,
        "magic": magic,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
    }
    
    if not is_pending:
        request["type_filling"] = mt5.ORDER_FILLING_IOC
        
    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logging.error(f"Order failed, retcode={result.retcode}")
        logging.error(f"Error Description: {result.comment}")
        return None
        
    logging.info(f"Trade Executed Successfully! Ticket: {result.order}")
    return result.order

def send_telegram_message(message):
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id or chat_id == "YOUR_CHAT_ID_HERE":
        logging.warning("Telegram credentials not fully set. Skipping Telegram notification.")
        return False
        
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message
    }
    
    try:
        response = requests.post(url, json=payload, timeout=5)
        if response.status_code == 200:
            logging.info("Telegram message sent successfully.")
            return True
        else:
            logging.error(f"Failed to send Telegram message: {response.text}")
            return False
    except Exception as e:
        logging.error(f"Exception while sending Telegram message: {e}")
        return False

def init_db():
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS trade_groups (
            magic_number INTEGER PRIMARY KEY,
            symbol TEXT,
            trade_1_ticket INTEGER,
            trade_2_ticket INTEGER,
            recovery_ticket INTEGER,
            status TEXT
        )
    ''')
    try:
        c.execute('ALTER TABLE trade_groups ADD COLUMN rec_action TEXT')
        c.execute('ALTER TABLE trade_groups ADD COLUMN rec_entry REAL')
        c.execute('ALTER TABLE trade_groups ADD COLUMN rec_sl REAL')
        c.execute('ALTER TABLE trade_groups ADD COLUMN rec_tp REAL')
        c.execute('ALTER TABLE trade_groups ADD COLUMN rec_volume REAL')
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()

def check_trade_group(group):
    magic, symbol, t1_ticket, t2_ticket, rec_ticket, rec_action, rec_entry, rec_sl, rec_tp, rec_volume, status = group
    
    if status == 'PENDING_ORIGINAL':
        pos = mt5.positions_get(ticket=t1_ticket)
        if pos and len(pos) > 0:
            logging.info(f"[Magic {magic}] Original trade filled! Placing Recovery Pending Order...")
            new_rec_ticket = execute_trade(symbol, rec_action, rec_sl, rec_tp, rec_volume, rec_entry, magic, "Recovery")
            
            conn = sqlite3.connect('trades.db')
            c = conn.cursor()
            if new_rec_ticket:
                c.execute("UPDATE trade_groups SET recovery_ticket = ?, status = 'ACTIVE' WHERE magic_number = ?", (new_rec_ticket, magic))
                send_telegram_message(f"🔄 [Magic {magic}] Original {symbol} Trade Filled!\nPlacing Recovery {rec_action} Order at {rec_entry} (Ticket: {new_rec_ticket})")
            else:
                logging.error(f"[Magic {magic}] Failed to place Recovery Trade.")
                send_telegram_message(f"⚠️ [Magic {magic}] Original {symbol} Trade Filled, but FAILED to place Recovery Trade!")
                c.execute("UPDATE trade_groups SET status = 'ACTIVE' WHERE magic_number = ?", (magic,))
            conn.commit()
            conn.close()
            notify_clients("tracker_update", "update")
        else:
            history_orders = mt5.history_orders_get(ticket=t1_ticket)
            if history_orders and len(history_orders) > 0:
                h_order = history_orders[0]
                if h_order.state in (mt5.ORDER_STATE_CANCELED, mt5.ORDER_STATE_REJECTED):
                    conn = sqlite3.connect('trades.db')
                    c = conn.cursor()
                    c.execute("UPDATE trade_groups SET status = 'CANCELLED' WHERE magic_number = ?", (magic,))
                    conn.commit()
                    conn.close()
                    send_telegram_message(f"❌ [Magic {magic}] {symbol} Original Pending Order cancelled. Aborting recovery setup.")
                    notify_clients("tracker_update", "update")
        return
        
    pos = mt5.positions_get(ticket=t1_ticket)
    if pos and len(pos) > 0:
        return
        
    deals = mt5.history_deals_get(position=t1_ticket)
    if deals and len(deals) > 0:
        out_deals = [d for d in deals if d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_INOUT)]
        if len(out_deals) > 0:
            out_deal = out_deals[-1]
            profit = out_deal.profit
            
            conn = sqlite3.connect('trades.db')
            c = conn.cursor()
            
            if profit > 0:
                logging.info(f"[Magic {magic}] TP1 Hit for Original Trade. Cancelling Recovery...")
                if rec_ticket:
                    res = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": rec_ticket})
                    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                        logging.info(f"[Magic {magic}] Recovery Trade {rec_ticket} cancelled.")
                        send_telegram_message(f"✅ [Magic {magic}] {symbol} TP1 Hit!\nRecovery Trade (Ticket: {rec_ticket}) has been CANCELLED.")
                    else:
                        send_telegram_message(f"⚠️ [Magic {magic}] {symbol} TP1 Hit!\nWARNING: Failed to cancel Recovery Trade (Ticket: {rec_ticket}). Please cancel manually!")
                else:
                    send_telegram_message(f"✅ [Magic {magic}] {symbol} TP1 Hit!\n(No recovery trade to cancel)")
                c.execute("UPDATE trade_groups SET status = 'SUCCESS_TP1_HIT' WHERE magic_number = ?", (magic,))
            else:
                logging.info(f"[Magic {magic}] SL Hit for Original Trade. Recovery Triggered.")
                send_telegram_message(f"🛑 [Magic {magic}] {symbol} SL Hit!\nRecovery Trade (Ticket: {rec_ticket}) has been TRIGGERED.")
                c.execute("UPDATE trade_groups SET status = 'RECOVERY_TRIGGERED' WHERE magic_number = ?", (magic,))
            conn.commit()
            conn.close()
            notify_clients("tracker_update", "update")

def poller_thread():
    global global_mt5_status
    while True:
        try:
            if not mt5.initialize():
                if global_mt5_status:
                    global_mt5_status = False
                    notify_clients("mt5_status", "false")
                time.sleep(5)
                continue
            
            if not global_mt5_status:
                global_mt5_status = True
                notify_clients("mt5_status", "true")
                
            conn = sqlite3.connect('trades.db')
            c = conn.cursor()
            c.execute("SELECT magic_number, symbol, trade_1_ticket, trade_2_ticket, recovery_ticket, rec_action, rec_entry, rec_sl, rec_tp, rec_volume, status FROM trade_groups WHERE status IN ('ACTIVE', 'PENDING_ORIGINAL')")
            active_groups = c.fetchall()
            conn.close()
            
            for group in active_groups:
                check_trade_group(group)
        except Exception as e:
            logging.error(f"Poller thread error: {e}")
        time.sleep(3)

def reconcile_on_boot():
    init_db()
    logging.info("Running reconciliation flow on boot...")
    if not mt5.initialize():
        logging.error("MT5 init failed during reconciliation.")
        return
        
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    c.execute("SELECT magic_number, symbol, trade_1_ticket, trade_2_ticket, recovery_ticket, rec_action, rec_entry, rec_sl, rec_tp, rec_volume, status FROM trade_groups WHERE status IN ('ACTIVE', 'PENDING_ORIGINAL')")
    active_groups = c.fetchall()
    conn.close()
    
    for group in active_groups:
        check_trade_group(group)

def start_ngrok():
    logging.info("Starting Ngrok silently...")
    subprocess.Popen(['ngrok', 'http', '5000'], creationflags=0x08000000)
    threading.Thread(target=fetch_ngrok_url, daemon=True).start()
    
def fetch_ngrok_url():
    global global_ngrok_url
    for _ in range(10): # try 10 times
        time.sleep(2)
        try:
            req = urllib.request.Request("http://127.0.0.1:4040/api/tunnels")
            response = urllib.request.urlopen(req, timeout=3)
            data = json.loads(response.read().decode('utf-8'))
            tunnels = data.get('tunnels', [])
            if tunnels:
                public_url = tunnels[0]['public_url']
                for t in tunnels:
                    if t['public_url'].startswith('https'):
                        public_url = t['public_url']
                        break
                
                global_ngrok_url = public_url + "/webhook"
                notify_clients("ngrok_url", global_ngrok_url)
                logging.info(f"Ngrok connected successfully: {public_url}")
                return
        except Exception:
            pass
    logging.error("Failed to fetch Ngrok URL after multiple attempts.")

# --- FLASK ENDPOINTS ---
@flask_app.route('/')
def index():
    return render_template('index.html')

@flask_app.route('/api/stream')
def stream():
    q = queue.Queue()
    clients.append(q)
    
    # Send initial state
    q.put({"event": "ngrok_url", "data": global_ngrok_url})
    q.put({"event": "mt5_status", "data": str(global_mt5_status).lower()})
    
    # Send log history so UI isn't blank on refresh
    for log_msg in recent_logs:
        q.put({"event": "log", "data": log_msg})
    
    def generate():
        try:
            while True:
                item = q.get()
                # SSE specification requires multi-line data to be prefixed with 'data: ' on each line
                data_string = str(item['data']).replace('\n', '\ndata: ')
                yield f"event: {item['event']}\ndata: {data_string}\n\n"
        finally:
            if q in clients:
                clients.remove(q)
            
    return Response(generate(), mimetype='text/event-stream')

@flask_app.route('/api/tracker')
def api_tracker():
    try:
        conn = sqlite3.connect('trades.db')
        c = conn.cursor()
        c.execute("SELECT magic_number, symbol, trade_1_ticket, trade_2_ticket, recovery_ticket, status FROM trade_groups WHERE status != 'CANCELLED' ORDER BY symbol ASC, magic_number DESC LIMIT 100")
        rows = c.fetchall()
        conn.close()
        
        data = []
        for r in rows:
            data.append({
                "magic_number": r[0],
                "symbol": r[1],
                "trade_1_ticket": r[2],
                "trade_2_ticket": r[3],
                "recovery_ticket": r[4],
                "status": r[5]
            })
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@flask_app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json(force=True)
    logging.info(f"RAW JSON from TV: {data}")
    if not data:
        return jsonify({"error": "Invalid payload"}), 400
        
    process_signal(data)
    return jsonify({"status": "signal received"}), 200

def process_signal(data):
    # This replaces the logic that was inside show_trade_popup in app_gui.py
    action = data.get('action', '').upper()
    symbol = data.get('symbol', '')
    try:
        entry = float(data.get('entry', 0))
    except:
        entry = 0.0
    sl = float(data.get('sl', 0))
    tp1 = float(data.get('tp1', 0))
    tp2 = float(data.get('tp2', 0))
    risk_usd = float(data.get('risk_usd', 100.0))
    
    calculated_volume = calculate_volume(symbol, entry, sl, risk_usd)
    symbol_info = mt5.symbol_info(symbol)
    step = symbol_info.volume_step if symbol_info else 0.01
    min_vol = symbol_info.volume_min if symbol_info else 0.01
    
    vol1 = round((calculated_volume / 2) / step) * step
    vol2 = calculated_volume - vol1
    vol1 = round(vol1, 2)
    vol2 = round(vol2, 2)
    
    split_trade = False
    split_reason = ""
    if tp2 == 0:
        split_reason = "No TP2 provided."
    elif calculated_volume < (min_vol * 2):
        split_reason = f"Calculated volume ({calculated_volume}) is too small to split (Minimum required: {min_vol * 2})."
    else:
        split_trade = True
        
    # calculate recovery
    if mt5.initialize():
        tick = mt5.symbol_info_tick(symbol)
        actual_entry = entry if entry > 0 else (tick.ask if action == "BUY" else tick.bid)
    else:
        actual_entry = entry
    
    rec_action = "SELL" if action == "BUY" else "BUY"
    rec_entry = sl
    rec_sl = actual_entry
    r_amount = abs(rec_entry - rec_sl)
    
    if rec_action == "BUY":
        rec_tp = rec_entry + (r_amount * 0.5)
    else:
        rec_tp = rec_entry - (r_amount * 0.5)
        
    rec_volume = calculate_volume(symbol, rec_entry, rec_sl, risk_usd)
        
    logging.info(f"Signal received for {symbol}. Waiting for confirmation in UI...")
    
    # Build message and send Telegram notification
    msg = f"NEW TRADINGVIEW SIGNAL\n\n"
    msg += f"Symbol: {symbol}\n"
    msg += f"Action: {action}\n"
    if entry > 0:
        msg += f"Entry Level: {entry} (Will place Limit/Stop Order)\n"
    else:
        msg += f"Entry Level: Market\n"
    msg += f"Stop Loss: {sl}\n"
    msg += f"Take Profit 1: {tp1}\n"
    if tp2 != 0:
        msg += f"Take Profit 2: {tp2}\n"
    msg += f"Risk Amount: ${risk_usd}\n"
    msg += f"Total Lot Size: {calculated_volume} Lots\n\n"
    
    if split_trade:
        msg += f"Will execute TWO trades:\n"
        msg += f"- Trade 1: {vol1} Lots targeting TP1\n"
        msg += f"- Trade 2: {vol2} Lots targeting TP2\n\n"
    else:
        msg += f"Will execute ONE trade: {calculated_volume} Lots targeting TP1\n"
        msg += f"(Trade not split because: {split_reason})\n\n"
        
    msg += f"Recovery Trade (Pending):\n"
    msg += f"- Action: {rec_action}\n"
    msg += f"- Entry: {rec_entry}\n"
    msg += f"- SL: {rec_sl} | TP: {rec_tp}\n"
    msg += f"- Volume: {rec_volume}\n\n"
        
    msg += f"Do you want to execute this now?"
    
    send_telegram_message(msg)
    
    # Enhance data for the UI
    data['calculated_volume'] = calculated_volume
    data['split_trade'] = split_trade
    data['split_reason'] = split_reason
    data['vol1'] = vol1
    data['vol2'] = vol2
    data['rec_action'] = rec_action
    data['rec_entry'] = rec_entry
    data['rec_sl'] = rec_sl
    data['rec_tp'] = rec_tp
    data['rec_volume'] = rec_volume
    
    # Send to UI via SSE
    notify_clients("trade_signal", json.dumps(data))

@flask_app.route('/api/execute_trade', methods=['POST'])
def api_execute_trade():
    data = request.json
    symbol = data.get('symbol')
    action = data.get('action')
    sl = float(data.get('sl', 0))
    tp1 = float(data.get('tp1', 0))
    tp2 = float(data.get('tp2', 0))
    entry = float(data.get('entry', 0))
    split_trade = data.get('split_trade', False)
    vol1 = data.get('vol1')
    vol2 = data.get('vol2')
    calculated_volume = data.get('calculated_volume')
    
    rec_action = data.get('rec_action')
    rec_entry = data.get('rec_entry')
    rec_sl = data.get('rec_sl')
    rec_tp = data.get('rec_tp')
    rec_volume = data.get('rec_volume')
    
    logging.info(f"User clicked EXECUTE for {symbol}.")
    
    magic_number = random.randint(100000, 999999)
    t1_ticket = None
    t2_ticket = None
    
    if split_trade:
        t1_ticket = execute_trade(symbol, action, sl, tp1, vol1, entry, magic_number, "Orig_TP1")
        t2_ticket = execute_trade(symbol, action, sl, tp2, vol2, entry, magic_number, "Orig_TP2")
    else:
        t1_ticket = execute_trade(symbol, action, sl, tp1, calculated_volume, entry, magic_number, "Orig_TP1")
        
    if t1_ticket:
        conn = sqlite3.connect('trades.db')
        c = conn.cursor()
        c.execute('''
            INSERT INTO trade_groups (magic_number, symbol, trade_1_ticket, trade_2_ticket, recovery_ticket, rec_action, rec_entry, rec_sl, rec_tp, rec_volume, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (magic_number, symbol, t1_ticket, t2_ticket, None, rec_action, rec_entry, rec_sl, rec_tp, rec_volume, 'PENDING_ORIGINAL'))
        conn.commit()
        conn.close()
        logging.info(f"Trade Group [Magic {magic_number}] saved to DB (Status: PENDING_ORIGINAL).")
        notify_clients("tracker_update", "update")
        
    return jsonify({"status": "success"})

@flask_app.route('/api/abort_trade', methods=['POST'])
def api_abort_trade():
    logging.info("User clicked ABORT.")
    return jsonify({"status": "aborted"})

def main():
    logging.info("Starting Premium MT5 Bridge Server...")
    
    # DB Reconcile and Poller
    reconcile_on_boot()
    threading.Thread(target=poller_thread, daemon=True).start()
    
    # Setup Ngrok
    start_ngrok()
    
    send_telegram_message("✅ MT5 Bridge Server Started & Web UI Ready!")
    
    # Auto-open browser
    threading.Thread(target=lambda: (time.sleep(1), webbrowser.open("http://127.0.0.1:5000")), daemon=True).start()

    # Run Flask
    flask_app.run(host='0.0.0.0', port=5000, use_reloader=False)

if __name__ == "__main__":
    main()
