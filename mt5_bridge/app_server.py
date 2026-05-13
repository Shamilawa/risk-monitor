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
global_mt5_status = '{"online": false, "text": "Checking..."}'

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
def calculate_volume(symbol, entry_price, sl_price, risk_usd, instance_path=None, symbol_suffix=""):
    actual_symbol = symbol + symbol_suffix
    if instance_path:
        initialized = mt5.initialize(path=instance_path)
    else:
        initialized = mt5.initialize()
        
    if not initialized:
        return 0.01
        
    symbol_info = mt5.symbol_info(actual_symbol)
    if symbol_info is None:
        logging.error(f"Error: {actual_symbol} not found in MT5")
        return 0.01
        
    mt5.symbol_select(actual_symbol, True)
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

def execute_trade(symbol, action_type, sl, tp, volume, entry_price, instance_path=None, magic=999111, comment="TradingView Signal", symbol_suffix=""):
    actual_symbol = symbol + symbol_suffix
    if instance_path:
        initialized = mt5.initialize(path=instance_path)
    else:
        initialized = mt5.initialize()
        
    if not initialized:
        logging.error(f"MT5 initialization failed: {mt5.last_error()}")
        return None
        
    tick = mt5.symbol_info_tick(actual_symbol)
    if tick is None:
        logging.error(f"Failed to get tick for {actual_symbol}")
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
        "symbol": actual_symbol,
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
    
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='trade_groups'")
    has_old = c.fetchone()
    
    is_migrated = False
    if has_old:
        c.execute("PRAGMA table_info(trade_groups)")
        columns = [col[1] for col in c.fetchall()]
        if 'id' in columns:
            is_migrated = True
            
    if has_old and not is_migrated:
        logging.info("Migrating trade_groups to new schema...")
        c.execute("ALTER TABLE trade_groups RENAME TO trade_groups_v1")
        
    c.execute('''
        CREATE TABLE IF NOT EXISTS instances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            path TEXT,
            risk_usd REAL DEFAULT 100.0,
            symbol_suffix TEXT DEFAULT ''
        )
    ''')
    
    try:
        c.execute('ALTER TABLE instances ADD COLUMN risk_usd REAL DEFAULT 100.0')
    except sqlite3.OperationalError:
        pass
        
    try:
        c.execute("ALTER TABLE instances ADD COLUMN symbol_suffix TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS trade_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id INTEGER,
            magic_number INTEGER,
            symbol TEXT,
            action TEXT,
            entry_price REAL,
            sl REAL,
            tp1 REAL,
            tp2 REAL,
            vol1 REAL,
            vol2 REAL,
            split_trade INTEGER,
            trade_1_ticket INTEGER,
            trade_2_ticket INTEGER,
            recovery_ticket INTEGER,
            rec_action TEXT,
            rec_entry REAL,
            rec_sl REAL,
            rec_tp REAL,
            rec_volume REAL,
            status TEXT
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS trading_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id INTEGER,
            ticket INTEGER,
            symbol TEXT,
            type INTEGER,
            volume REAL,
            profit REAL,
            time INTEGER,
            magic INTEGER,
            comment TEXT,
            UNIQUE(instance_id, ticket)
        )
    ''')
    
    # Add columns for tooltip if they don't exist
    try:
        c.execute("ALTER TABLE trading_log ADD COLUMN commission REAL DEFAULT 0")
    except Exception: pass
    try:
        c.execute("ALTER TABLE trading_log ADD COLUMN swap REAL DEFAULT 0")
    except Exception: pass
    try:
        c.execute("ALTER TABLE trading_log ADD COLUMN raw_profit REAL DEFAULT 0")
    except Exception: pass
    
    conn.commit()
    conn.close()

def check_trade_group(group, instance_path=None, inst_name="Default", symbol_suffix=""):
    group_id, magic, symbol, t1_ticket, t2_ticket, rec_ticket, rec_action, rec_entry, rec_sl, rec_tp, rec_volume, status = group
    
    prefix = f"[{inst_name}] [Magic {magic}]"
    
    if status == 'PENDING_ORIGINAL':
        pos = mt5.positions_get(ticket=t1_ticket)
        if pos and len(pos) > 0:
            logging.info(f"{prefix} Original trade filled! Placing Recovery Pending Order...")
            new_rec_ticket = execute_trade(symbol, rec_action, rec_sl, rec_tp, rec_volume, rec_entry, instance_path, magic, "Recovery", symbol_suffix)
            
            conn = sqlite3.connect('trades.db')
            c = conn.cursor()
            if new_rec_ticket:
                c.execute("UPDATE trade_groups SET recovery_ticket = ?, status = 'ACTIVE' WHERE id = ?", (new_rec_ticket, group_id))
                send_telegram_message(f"🔄 {prefix} Original {symbol} Trade Filled!\nPlacing Recovery {rec_action} Order at {rec_entry} (Ticket: {new_rec_ticket})")
            else:
                logging.error(f"{prefix} Failed to place Recovery Trade.")
                send_telegram_message(f"⚠️ {prefix} Original {symbol} Trade Filled, but FAILED to place Recovery Trade!")
                c.execute("UPDATE trade_groups SET status = 'ACTIVE' WHERE id = ?", (group_id,))
            conn.commit()
            conn.close()
            notify_clients("tracker_update", "update")
        else:
            # Check for trade invalidation
            orders = mt5.orders_get(ticket=t1_ticket)
            if orders and len(orders) > 0:
                order = orders[0]
                sl = order.sl
                tp = order.tp
                order_type = order.type
                
                tick = mt5.symbol_info_tick(symbol)
                if tick:
                    current_price = tick.ask if order_type in (mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP) else tick.bid
                    
                    invalid = False
                    reason = ""
                    
                    # Condition 1: Hit SL without filling
                    if order_type in (mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP):
                        if current_price <= sl and sl != 0:
                            invalid = True
                            reason = "Price reached SL without filling"
                    elif order_type in (mt5.ORDER_TYPE_SELL_LIMIT, mt5.ORDER_TYPE_SELL_STOP):
                        if current_price >= sl and sl != 0:
                            invalid = True
                            reason = "Price reached SL without filling"
                            
                    # Condition 2: Reach TP1 level without filling
                    if not invalid:
                        if order_type in (mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP):
                            if current_price >= tp and tp != 0:
                                invalid = True
                                reason = "Price reached TP1 without filling"
                        elif order_type in (mt5.ORDER_TYPE_SELL_LIMIT, mt5.ORDER_TYPE_SELL_STOP):
                            if current_price <= tp and tp != 0:
                                invalid = True
                                reason = "Price reached TP1 without filling"
                                
                    if invalid:
                        logging.info(f"{prefix} {reason}. Cancelling pending orders...")
                        mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": t1_ticket})
                        if t2_ticket:
                            mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": t2_ticket})
                            
                        conn = sqlite3.connect('trades.db')
                        c = conn.cursor()
                        c.execute("UPDATE trade_groups SET status = 'CANCELLED' WHERE id = ?", (group_id,))
                        conn.commit()
                        conn.close()
                        
                        send_telegram_message(f"❌ {prefix} {symbol} Pending Trade Invalidated: {reason}.")
                        notify_clients("tracker_update", "update")
                        return
            
            # Fallback check if cancelled
            history_orders = mt5.history_orders_get(ticket=t1_ticket)
            if history_orders and len(history_orders) > 0:
                h_order = history_orders[0]
                if h_order.state in (mt5.ORDER_STATE_CANCELED, mt5.ORDER_STATE_REJECTED):
                    conn = sqlite3.connect('trades.db')
                    c = conn.cursor()
                    c.execute("UPDATE trade_groups SET status = 'CANCELLED' WHERE id = ?", (group_id,))
                    conn.commit()
                    conn.close()
                    send_telegram_message(f"❌ {prefix} {symbol} Original Pending Order cancelled. Aborting recovery setup.")
                    notify_clients("tracker_update", "update")
        return
        
    if status == 'RECOVERY_TRIGGERED':
        pos = mt5.positions_get(ticket=rec_ticket)
        if pos and len(pos) > 0:
            return
            
        deals = mt5.history_deals_get(position=rec_ticket)
        if deals and len(deals) > 0:
            out_deals = [d for d in deals if d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_INOUT)]
            if len(out_deals) > 0:
                out_deal = out_deals[-1]
                profit = out_deal.profit
                
                conn = sqlite3.connect('trades.db')
                c = conn.cursor()
                
                if profit > 0:
                    logging.info(f"{prefix} Recovery Trade Hit TP!")
                    send_telegram_message(f"✅ {prefix} {symbol} Recovery Trade hit TP!")
                    c.execute("UPDATE trade_groups SET status = 'RECOVERY_SUCCESS' WHERE id = ?", (group_id,))
                else:
                    logging.info(f"{prefix} Recovery Trade Hit SL!")
                    send_telegram_message(f"🛑 {prefix} {symbol} Recovery Trade hit SL!")
                    c.execute("UPDATE trade_groups SET status = 'RECOVERY_FAILED' WHERE id = ?", (group_id,))
                conn.commit()
                conn.close()
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
                logging.info(f"{prefix} TP1 Hit for Original Trade. Cancelling Recovery...")
                if rec_ticket:
                    res = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": rec_ticket})
                    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                        logging.info(f"{prefix} Recovery Trade {rec_ticket} cancelled.")
                        send_telegram_message(f"✅ {prefix} {symbol} TP1 Hit!\nRecovery Trade (Ticket: {rec_ticket}) has been CANCELLED.")
                    else:
                        send_telegram_message(f"⚠️ {prefix} {symbol} TP1 Hit!\nWARNING: Failed to cancel Recovery Trade (Ticket: {rec_ticket}). Please cancel manually!")
                else:
                    send_telegram_message(f"✅ {prefix} {symbol} TP1 Hit!\n(No recovery trade to cancel)")
                c.execute("UPDATE trade_groups SET status = 'SUCCESS_TP1_HIT' WHERE id = ?", (group_id,))
            else:
                logging.info(f"{prefix} SL Hit for Original Trade. Recovery Triggered.")
                send_telegram_message(f"🛑 {prefix} {symbol} SL Hit!\nRecovery Trade (Ticket: {rec_ticket}) has been TRIGGERED.")
                c.execute("UPDATE trade_groups SET status = 'RECOVERY_TRIGGERED' WHERE id = ?", (group_id,))
            conn.commit()
            conn.close()
            notify_clients("tracker_update", "update")

def poller_thread():
    global global_mt5_status
    while True:
        try:
            conn = sqlite3.connect('trades.db')
            c = conn.cursor()
            c.execute("SELECT id, name, path, symbol_suffix FROM instances")
            instances = c.fetchall()
            
            if not instances:
                # Fallback to default single instance
                if mt5.initialize():
                    status_data = json.dumps({"online": True, "text": "MT5 Connected"})
                    c.execute("SELECT id, magic_number, symbol, trade_1_ticket, trade_2_ticket, recovery_ticket, rec_action, rec_entry, rec_sl, rec_tp, rec_volume, status FROM trade_groups WHERE status IN ('ACTIVE', 'PENDING_ORIGINAL', 'RECOVERY_TRIGGERED')")
                    active_groups = c.fetchall()
                    for group in active_groups:
                        check_trade_group(group, None, "Default")
                else:
                    status_data = json.dumps({"online": False, "text": "MT5 Offline"})
            else:
                total_count = len(instances)
                online_count = 0
                for inst in instances:
                    inst_id, inst_name, inst_path, symbol_suffix = inst
                    if mt5.initialize(path=inst_path):
                        online_count += 1
                        c.execute("SELECT id, magic_number, symbol, trade_1_ticket, trade_2_ticket, recovery_ticket, rec_action, rec_entry, rec_sl, rec_tp, rec_volume, status FROM trade_groups WHERE status IN ('ACTIVE', 'PENDING_ORIGINAL', 'RECOVERY_TRIGGERED') AND instance_id = ?", (inst_id,))
                        active_groups = c.fetchall()
                        for group in active_groups:
                            check_trade_group(group, inst_path, inst_name, symbol_suffix)
                
                is_any_online = online_count > 0
                status_text = f"MT5: {online_count}/{total_count} Online" if total_count > 0 else "No Instances"
                status_data = json.dumps({"online": is_any_online, "text": status_text})
            
            if status_data != global_mt5_status:
                global_mt5_status = status_data
                notify_clients("mt5_status", status_data)
            
            conn.close()
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
    c.execute("SELECT id, magic_number, symbol, trade_1_ticket, trade_2_ticket, recovery_ticket, rec_action, rec_entry, rec_sl, rec_tp, rec_volume, status FROM trade_groups WHERE status IN ('ACTIVE', 'PENDING_ORIGINAL', 'RECOVERY_TRIGGERED')")
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
    q.put({"event": "mt5_status", "data": str(global_mt5_status)})
    
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

@flask_app.route('/api/instances', methods=['GET', 'POST', 'DELETE'])
def api_instances():
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    
    if request.method == 'GET':
        c.execute("SELECT id, name, path, risk_usd, symbol_suffix FROM instances ORDER BY id ASC")
        rows = c.fetchall()
        instances = [{"id": r[0], "name": r[1], "path": r[2], "risk_usd": r[3], "symbol_suffix": r[4]} for r in rows]
        conn.close()
        return jsonify(instances)
        
    elif request.method == 'POST':
        data = request.json
        name = data.get('name')
        path = data.get('path')
        risk_usd = float(data.get('risk_usd', 100.0))
        symbol_suffix = data.get('symbol_suffix', '')
        if not name or not path:
            conn.close()
            return jsonify({"error": "Name and path required"}), 400
            
        c.execute("INSERT INTO instances (name, path, risk_usd, symbol_suffix) VALUES (?, ?, ?, ?)", (name, path, risk_usd, symbol_suffix))
        conn.commit()
        new_id = c.lastrowid
        conn.close()
        return jsonify({"id": new_id, "name": name, "path": path, "risk_usd": risk_usd, "symbol_suffix": symbol_suffix}), 201
        
    elif request.method == 'DELETE':
        data = request.json
        instance_id = data.get('id')
        if not instance_id:
            conn.close()
            return jsonify({"error": "ID required"}), 400
            
        c.execute("DELETE FROM instances WHERE id = ?", (instance_id,))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})

@flask_app.route('/api/browse_file', methods=['GET'])
def api_browse_file():
    import subprocess
    import sys
    cmd = [
        sys.executable, '-c', 
        "import tkinter as tk; from tkinter import filedialog; root = tk.Tk(); root.withdraw(); root.attributes('-topmost', True); print(filedialog.askopenfilename(title='Select MT5 terminal64.exe', filetypes=[('Executable files', '*.exe'), ('All files', '*.*')]))"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    file_path = result.stdout.strip()
    return jsonify({"path": file_path})

@flask_app.route('/api/tracker')
def api_tracker():
    try:
        conn = sqlite3.connect('trades.db')
        c = conn.cursor()
        
        tab = request.args.get('tab', 'active')
        query_base = """
            SELECT t.id, t.instance_id, i.name, t.magic_number, t.symbol, 
                   t.trade_1_ticket, t.trade_2_ticket, t.recovery_ticket, t.status 
            FROM trade_groups t
            LEFT JOIN instances i ON t.instance_id = i.id
        """
        if tab == 'active':
            c.execute(f"{query_base} WHERE t.status IN ('PENDING_ORIGINAL', 'ACTIVE', 'RECOVERY_TRIGGERED', 'FAILED_EXECUTION') ORDER BY t.symbol ASC, t.id DESC LIMIT 100")
        else:
            c.execute(f"{query_base} WHERE t.status IN ('SUCCESS_TP1_HIT', 'RECOVERY_SUCCESS', 'RECOVERY_FAILED', 'CANCELLED') ORDER BY t.symbol ASC, t.id DESC LIMIT 100")
            
        rows = c.fetchall()
        conn.close()
        
        data = []
        for r in rows:
            data.append({
                "id": r[0],
                "instance_id": r[1],
                "instance_name": r[2] or "Unknown",
                "magic_number": r[3],
                "symbol": r[4],
                "trade_1_ticket": r[5],
                "trade_2_ticket": r[6],
                "recovery_ticket": r[7],
                "status": r[8]
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
    
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    c.execute("SELECT id, name, path, risk_usd, symbol_suffix FROM instances ORDER BY id ASC")
    instances = c.fetchall()
    conn.close()
    
    if not instances:
        instances = [(None, "Default", None, 100.0, "")]
        
    instance_executions = []
    
    for inst in instances:
        inst_id, inst_name, inst_path, risk_usd, symbol_suffix = inst
        
        calculated_volume = calculate_volume(symbol, entry, sl, risk_usd, inst_path, symbol_suffix)
        
        step = 0.01
        min_vol = 0.01
        actual_entry = entry
        
        actual_symbol = symbol + symbol_suffix
        if mt5.initialize(path=inst_path):
            symbol_info = mt5.symbol_info(actual_symbol)
            if symbol_info:
                step = symbol_info.volume_step
                min_vol = symbol_info.volume_min
            tick = mt5.symbol_info_tick(actual_symbol)
            if tick:
                actual_entry = entry if entry > 0 else (tick.ask if action == "BUY" else tick.bid)
                
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
            
        rec_action = "SELL" if action == "BUY" else "BUY"
        rec_entry = sl
        rec_sl = actual_entry
        r_amount = abs(rec_entry - rec_sl)
        
        if rec_action == "BUY":
            rec_tp = rec_entry + (r_amount * 0.5)
        else:
            rec_tp = rec_entry - (r_amount * 0.5)
            
        rec_volume = calculate_volume(symbol, rec_entry, rec_sl, risk_usd, inst_path, symbol_suffix)
        
        instance_executions.append({
            "id": inst_id,
            "name": inst_name,
            "path": inst_path,
            "risk_usd": risk_usd,
            "symbol_suffix": symbol_suffix,
            "calculated_volume": calculated_volume,
            "vol1": vol1,
            "vol2": vol2,
            "split_trade": split_trade,
            "split_reason": split_reason,
            "rec_action": rec_action,
            "rec_entry": rec_entry,
            "rec_sl": rec_sl,
            "rec_tp": rec_tp,
            "rec_volume": rec_volume
        })
        
    logging.info(f"Signal received for {symbol}. Calculated volumes for {len(instance_executions)} instances. Waiting for confirmation in UI...")
    
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
        msg += f"Take Profit 2: {tp2}\n\n"
        
    for exec_data in instance_executions:
        msg += f"Broker: {exec_data['name']}\n"
        msg += f"Risk: ${exec_data['risk_usd']}\n"
        if exec_data['split_trade']:
            msg += f"Lot Size: {exec_data['calculated_volume']} (Split: {exec_data['vol1']} / {exec_data['vol2']})\n"
        else:
            msg += f"Lot Size: {exec_data['calculated_volume']} (Single)\n"
        msg += "\n"
        
    msg += f"Do you want to execute this now?"
    send_telegram_message(msg)
    
    # Enhance data for the UI
    data['instance_executions'] = instance_executions
    
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
    
    instance_executions = data.get('instance_executions', [])
    
    logging.info(f"User clicked EXECUTE for {symbol}.")
    
    magic_number = random.randint(100000, 999999)
    
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    
    for exec_data in instance_executions:
        inst_id = exec_data.get('id')
        inst_name = exec_data.get('name')
        inst_path = exec_data.get('path')
        symbol_suffix = exec_data.get('symbol_suffix', '')
        vol1 = exec_data.get('vol1')
        vol2 = exec_data.get('vol2')
        split_trade = exec_data.get('split_trade')
        split_int = 1 if split_trade else 0
        rec_action = exec_data.get('rec_action')
        rec_entry = exec_data.get('rec_entry')
        rec_sl = exec_data.get('rec_sl')
        rec_tp = exec_data.get('rec_tp')
        rec_volume = exec_data.get('rec_volume')
        
        t1_ticket = None
        t2_ticket = None
        
        if split_trade:
            t1_ticket = execute_trade(symbol, action, sl, tp1, vol1, entry, inst_path, magic_number, "Orig_TP1", symbol_suffix)
            t2_ticket = execute_trade(symbol, action, sl, tp2, vol2, entry, inst_path, magic_number, "Orig_TP2", symbol_suffix)
        else:
            t1_ticket = execute_trade(symbol, action, sl, tp1, vol1, entry, inst_path, magic_number, "Orig_TP1", symbol_suffix)
            
        status = 'PENDING_ORIGINAL' if t1_ticket else 'FAILED_EXECUTION'
        
        c.execute('''
            INSERT INTO trade_groups (
                instance_id, magic_number, symbol, action, entry_price, sl, tp1, tp2, vol1, vol2, split_trade,
                trade_1_ticket, trade_2_ticket, recovery_ticket, rec_action, rec_entry, rec_sl, rec_tp, rec_volume, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            inst_id, magic_number, symbol, action, entry, sl, tp1, tp2, vol1, vol2, split_int,
            t1_ticket, t2_ticket, None, rec_action, rec_entry, rec_sl, rec_tp, rec_volume, status
        ))
        
        if status == 'FAILED_EXECUTION':
            logging.error(f"Failed to execute on instance {inst_name}. Marked for retry.")
        else:
            logging.info(f"Trade Group [Magic {magic_number}] saved on {inst_name} (Status: {status}).")
            
    conn.commit()
    conn.close()
    notify_clients("tracker_update", "update")
        
    return jsonify({"status": "success"})

@flask_app.route('/api/retry_trade', methods=['POST'])
def api_retry_trade():
    data = request.json
    trade_id = data.get('id')
    if not trade_id:
        return jsonify({"error": "Trade ID required"}), 400
        
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    c.execute("""
        SELECT t.magic_number, t.symbol, t.action, t.entry_price, t.sl, t.tp1, t.tp2, t.vol1, t.vol2, t.split_trade, i.path, i.symbol_suffix
        FROM trade_groups t
        LEFT JOIN instances i ON t.instance_id = i.id
        WHERE t.id = ? AND t.status = 'FAILED_EXECUTION'
    """, (trade_id,))
    row = c.fetchone()
    
    if not row:
        conn.close()
        return jsonify({"error": "Trade not found or not in failed state"}), 404
        
    magic_number, symbol, action, entry, sl, tp1, tp2, vol1, vol2, split_trade, inst_path, symbol_suffix = row
    
    t1_ticket = None
    t2_ticket = None
    
    if split_trade:
        t1_ticket = execute_trade(symbol, action, sl, tp1, vol1, entry, inst_path, magic_number, "Orig_TP1", symbol_suffix)
        t2_ticket = execute_trade(symbol, action, sl, tp2, vol2, entry, inst_path, magic_number, "Orig_TP2", symbol_suffix)
    else:
        t1_ticket = execute_trade(symbol, action, sl, tp1, vol1, entry, inst_path, magic_number, "Orig_TP1", symbol_suffix)
        
    if t1_ticket:
        c.execute("UPDATE trade_groups SET trade_1_ticket=?, trade_2_ticket=?, status='PENDING_ORIGINAL' WHERE id=?", 
                 (t1_ticket, t2_ticket, trade_id))
        conn.commit()
        logging.info(f"Retry successful for Trade ID {trade_id}")
        res = {"status": "success"}
    else:
        logging.error(f"Retry failed for Trade ID {trade_id}")
        res = {"status": "failed", "error": "Execution failed again"}
        
    conn.close()
    notify_clients("tracker_update", "update")
    return jsonify(res)

@flask_app.route('/api/abort_trade', methods=['POST'])
def api_abort_trade():
    logging.info("User clicked ABORT.")
    return jsonify({"status": "aborted"})

@flask_app.route('/api/sync_log', methods=['POST'])
def api_sync_log():
    logging.info("Syncing trading log from MT5 instances...")
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    c.execute("SELECT id, name, path FROM instances")
    instances = c.fetchall()
    
    if not instances:
        instances = [(None, "Default", None)]
        
    total_synced = 0
    for inst in instances:
        inst_id, inst_name, inst_path = inst
        
        if inst_path:
            initialized = mt5.initialize(path=inst_path)
        else:
            initialized = mt5.initialize()
            
        if not initialized:
            logging.error(f"Failed to initialize MT5 for instance {inst_name}")
            continue
            
        import datetime
        from_date = datetime.datetime(2000, 1, 1)
        to_date = datetime.datetime.now() + datetime.timedelta(days=1)
        
        deals = mt5.history_deals_get(from_date, to_date)
        if deals is None:
            logging.error(f"Failed to get history deals for {inst_name}: {mt5.last_error()}")
            continue
            
        logging.info(f"Fetched {len(deals)} deals from {inst_name}")
        
        # Clear existing logs for this instance to ensure a clean sync
        c.execute("DELETE FROM trading_log WHERE instance_id = ?", (inst_id,))
        
        for deal in deals:
            # Filter for deals that are trades (buy/sell)
            if deal.type not in (0, 1):
                continue
                
            # Filter for deals that are exits (OUT/INOUT/OUT_BY)
            # entry: 0=IN, 1=OUT, 2=INOUT, 3=OUT_BY
            # We only want the closing deals because they carry the profit and represent a completed trade.
            if deal.entry == 0:
                continue
                
            # Fetch ALL deals for this position to sum up profit/commission/swap
            # This handles cases where commission is charged on entry and exit separately.
            pos_deals = mt5.history_deals_get(position=deal.position_id)
            if pos_deals:
                total_profit = sum(d.profit for d in pos_deals)
                total_comm = sum(d.commission for d in pos_deals)
                total_swap = sum(d.swap for d in pos_deals)
                net_profit = total_profit + total_comm + total_swap
                logging.info(f"Position {deal.position_id}: Profit={total_profit}, Comm={total_comm}, Swap={total_swap}, Net={net_profit}")
            else:
                total_profit = deal.profit
                total_comm = deal.commission
                total_swap = deal.swap
                net_profit = deal.profit + deal.commission + deal.swap
                logging.info(f"Deal {deal.ticket} (no pos deals): Profit={deal.profit}, Comm={deal.commission}, Swap={deal.swap}, Net={net_profit}")
            
            try:
                c.execute('''
                    INSERT INTO trading_log (
                        instance_id, ticket, symbol, type, volume, profit, time, magic, comment, commission, swap, raw_profit
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    inst_id, deal.ticket, deal.symbol, deal.type, deal.volume, net_profit, deal.time, deal.magic, deal.comment, total_comm, total_swap, total_profit
                ))
                total_synced += 1
            except Exception as e:
                logging.error(f"Error inserting deal {deal.ticket}: {e}")
                
    conn.commit()
    conn.close()
    logging.info(f"Sync complete. Synced {total_synced} new deals.")
    return jsonify({"status": "success", "synced": total_synced})

@flask_app.route('/api/performance', methods=['GET'])
def api_performance():
    inst_id = request.args.get('instance_id')
    
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    
    query = "SELECT l.id, l.instance_id, i.name, l.ticket, l.symbol, l.type, l.volume, l.profit, l.time, l.magic, l.comment, l.commission, l.swap, l.raw_profit FROM trading_log l LEFT JOIN instances i ON l.instance_id = i.id"
    params = []
    
    if inst_id and inst_id != 'all':
        query += " WHERE l.instance_id = ?"
        params.append(inst_id)
        
    query += " ORDER BY l.time DESC"
    
    c.execute(query, params)
    rows = c.fetchall()
    
    trades = []
    total_profit = 0
    profitable_trades = 0
    total_trades = 0
    
    for r in rows:
        trades.append({
            "id": r[0],
            "instance_id": r[1],
            "instance_name": r[2] or "Default",
            "ticket": r[3],
            "symbol": r[4],
            # Invert type because we are showing exit deals!
            # If exit is BUY (0), the trade was SELL.
            # If exit is SELL (1), the trade was BUY.
            "type": "SELL" if r[5] == 0 else "BUY" if r[5] == 1 else "BALANCE" if r[5] == 2 else str(r[5]),
            "volume": r[6],
            "profit": r[7],
            "time": r[8],
            "magic": r[9],
            "comment": r[10],
            "commission": r[11],
            "swap": r[12],
            "raw_profit": r[13]
        })
        
        # Only count deals with non-zero profit for metrics to avoid counting double
        # In MT5, profit is only non-zero on deals that close a position.
        if r[7] != 0:
            total_profit += r[7]
            if r[7] > 0:
                profitable_trades += 1
            total_trades += 1
        
    win_rate = (profitable_trades / total_trades * 100) if total_trades > 0 else 0
    
    conn.close()
    
    return jsonify({
        "metrics": {
            "total_profit": round(total_profit, 2),
            "win_rate": round(win_rate, 2),
            "total_trades": total_trades
        },
        "trades": trades
    })

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
