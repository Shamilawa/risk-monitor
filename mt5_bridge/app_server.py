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
from datetime import datetime

load_dotenv()

# --- GLOBALS & STATE ---
clients = []
global_ngrok_url = "Starting Ngrok tunnel..."
global_mt5_status = '{"online": false, "text": "Checking..."}'

recent_logs = []
global_was_time_disabled = False

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
def get_unrealized_profit(instance_path=None):
    """Calculates the total floating profit of all open positions on the MT5 instance."""
    if instance_path:
        initialized = mt5.initialize(path=instance_path)
    else:
        initialized = mt5.initialize()
        
    if not initialized:
        return 0.0
        
    positions = mt5.positions_get()
    if positions is None or len(positions) == 0:
        return 0.0
        
    total_unrealized = 0.0
    for pos in positions:
        total_unrealized += pos.profit + getattr(pos, 'swap', 0.0)
        
    return total_unrealized
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

def calculate_atr_sl(symbol, timeframe_str, instance_path=None):
    """Calculates Wilder's Smoothing ATR(3) from MT5 data"""
    if instance_path:
        initialized = mt5.initialize(path=instance_path)
    else:
        initialized = mt5.initialize()
        
    if not initialized:
        return 0.0
        
    # Map timeframe
    tf_map = {
        "1": mt5.TIMEFRAME_M1, "3": mt5.TIMEFRAME_M3, "5": mt5.TIMEFRAME_M5,
        "15": mt5.TIMEFRAME_M15, "30": mt5.TIMEFRAME_M30, "60": mt5.TIMEFRAME_H1,
        "120": mt5.TIMEFRAME_H2, "240": mt5.TIMEFRAME_H4, "D": mt5.TIMEFRAME_D1,
        "1D": mt5.TIMEFRAME_D1, "W": mt5.TIMEFRAME_W1, "1W": mt5.TIMEFRAME_W1
    }
    mt5_tf = tf_map.get(str(timeframe_str).upper(), mt5.TIMEFRAME_H1) # fallback H1
    
    rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, 100)
    if rates is None or len(rates) < 10:
        return 0.0
        
    # Calculate True Range
    tr = []
    for i in range(1, len(rates)):
        high = rates[i]['high']
        low = rates[i]['low']
        prev_close = rates[i-1]['close']
        tr_val = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr.append(tr_val)
        
    # Wilder's Smoothing (RMA) for period 21
    period = 21
    if len(tr) < period:
        return 0.0
        
    rma = sum(tr[:period]) / period
    for i in range(period, len(tr)):
        rma = (tr[i] + (period - 1) * rma) / period
        
    return rma

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
        
    try:
        c.execute("ALTER TABLE instances ADD COLUMN symbol_mapping TEXT DEFAULT '{}'")
    except sqlite3.OperationalError:
        pass
        
    try:
        c.execute("ALTER TABLE instances ADD COLUMN auto_trade INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
        
    try:
        c.execute("ALTER TABLE instances ADD COLUMN accepted_timeframe TEXT DEFAULT 'all'")
    except sqlite3.OperationalError:
        pass
        
    try:
        c.execute("ALTER TABLE instances ADD COLUMN profit_limit REAL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
        
    try:
        c.execute("ALTER TABLE instances ADD COLUMN profit_limit_start_time INTEGER DEFAULT 0")
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

    try:
        c.execute("ALTER TABLE trading_log ADD COLUMN local_start_time INTEGER")
    except Exception: pass

    try:
        c.execute("ALTER TABLE trading_log ADD COLUMN local_time INTEGER")
    except Exception: pass
    
    # Add columns for Story Notes if they don't exist
    try:
        c.execute("ALTER TABLE trade_groups ADD COLUMN created_at TIMESTAMP")
    except Exception: pass
    try:
        c.execute("ALTER TABLE trade_groups ADD COLUMN signal_timeframe TEXT")
    except Exception: pass
    try:
        c.execute("ALTER TABLE trade_groups ADD COLUMN execution_mode TEXT")
    except Exception: pass
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS global_settings (
            id INTEGER PRIMARY KEY,
            trade_disable INTEGER DEFAULT 0,
            disable_time_start TEXT DEFAULT '',
            disable_time_end TEXT DEFAULT ''
        )
    ''')
    c.execute("INSERT OR IGNORE INTO global_settings (id, trade_disable, disable_time_start, disable_time_end) VALUES (1, 0, '', '')")
    
    conn.commit()
    conn.close()

def check_trade_group(group, instance_path=None, inst_name="Default", symbol_suffix=""):
    group_id, magic, symbol, t1_ticket, t2_ticket, action, entry_price, sl, tp1, tp2, status = group
    
    prefix = f"[{inst_name}] [Magic {magic}]"
    
    if status == 'PENDING_ORIGINAL':
        pos = mt5.positions_get(ticket=t1_ticket)
        if pos and len(pos) > 0:
            logging.info(f"{prefix} Original trade filled! Tracking active trade...")
            conn = sqlite3.connect('trades.db')
            c = conn.cursor()
            c.execute("UPDATE trade_groups SET status = 'ACTIVE' WHERE id = ?", (group_id,))
            conn.commit()
            conn.close()
            send_telegram_message(f"🔄 {prefix} {symbol} Trade Filled! Tracking for TP1.")
            notify_clients("tracker_update", "update")
            return
        else:
            # Check for trade invalidation
            orders = mt5.orders_get(ticket=t1_ticket)
            if orders and len(orders) > 0:
                order = orders[0]
                order_sl = order.sl
                order_tp = order.tp
                order_type = order.type
                
                tick = mt5.symbol_info_tick(symbol)
                if tick:
                    current_price = tick.ask if order_type in (mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP) else tick.bid
                    
                    invalid = False
                    reason = ""
                    
                    # Condition 1: Hit SL without filling
                    if order_type in (mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP):
                        if current_price <= order_sl and order_sl != 0:
                            invalid = True
                            reason = "Price reached SL without filling"
                    elif order_type in (mt5.ORDER_TYPE_SELL_LIMIT, mt5.ORDER_TYPE_SELL_STOP):
                        if current_price >= order_sl and order_sl != 0:
                            invalid = True
                            reason = "Price reached SL without filling"
                            
                    # Condition 2: Reach TP1 level without filling
                    if not invalid:
                        if order_type in (mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP):
                            if current_price >= order_tp and order_tp != 0:
                                invalid = True
                                reason = "Price reached TP1 without filling"
                        elif order_type in (mt5.ORDER_TYPE_SELL_LIMIT, mt5.ORDER_TYPE_SELL_STOP):
                            if current_price <= order_tp and order_tp != 0:
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
                    send_telegram_message(f"❌ {prefix} {symbol} Original Pending Order cancelled.")
                    notify_clients("tracker_update", "update")
        return

    if status == 'ACTIVE':
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
                    logging.info(f"{prefix} TP1 Hit! T2 is now running.")
                    send_telegram_message(f"✅ {prefix} {symbol} TP1 Hit! Taking 50% off. Leaving T2 running.")
                    c.execute("UPDATE trade_groups SET status = 'ACTIVE_T2_SL_ORIGINAL' WHERE id = ?", (group_id,))
                else:
                    logging.info(f"{prefix} SL Hit. Trade closed.")
                    
                    # Fetch extra context for recovery trade
                    c.execute("SELECT signal_timeframe, instance_id FROM trade_groups WHERE id = ?", (group_id,))
                    row_extra = c.fetchone()
                    signal_tf = row_extra[0] if row_extra and row_extra[0] else 'all'
                    inst_id = row_extra[1] if row_extra else None
                    
                    risk_usd = 100.0
                    if inst_id is not None:
                        c.execute("SELECT risk_usd FROM instances WHERE id = ?", (inst_id,))
                        i_row = c.fetchone()
                        if i_row: risk_usd = i_row[0]
                        
                    # Calculate ATR for recovery
                    actual_symbol = symbol + symbol_suffix
                    atr_val = calculate_atr_sl(actual_symbol, signal_tf, instance_path)
                    
                    if atr_val > 0:
                        sl_dist = atr_val * 5.0
                        rec_action = 'SELL' if action.upper() == 'BUY' else 'BUY'
                        
                        tick = mt5.symbol_info_tick(actual_symbol)
                        if tick:
                            rec_entry = tick.bid if rec_action == 'SELL' else tick.ask
                            
                            # Round SL distance to nearest tick size to prevent invalid prices
                            symbol_info = mt5.symbol_info(actual_symbol)
                            if symbol_info:
                                tick_size = symbol_info.trade_tick_size
                                sl_dist = round(sl_dist / tick_size) * tick_size
                            
                            if rec_action == 'SELL':
                                rec_sl = rec_entry + sl_dist
                                rec_tp = rec_entry - (sl_dist * 0.5)
                            else:
                                rec_sl = rec_entry - sl_dist
                                rec_tp = rec_entry + (sl_dist * 0.5)
                                
                            rec_volume = calculate_volume(actual_symbol, rec_entry, rec_sl, risk_usd, instance_path, "")
                            rec_ticket = execute_trade(actual_symbol, rec_action, rec_sl, rec_tp, rec_volume, rec_entry, instance_path, magic, "Recovery Trade", "")
                            
                            if rec_ticket:
                                send_telegram_message(f"🛑 {prefix} {symbol} SL Hit! \n🔄 Automatically opened RECOVERY {rec_action} (Ticket: {rec_ticket}).")
                                c.execute("UPDATE trade_groups SET status = 'CLOSED_SL', recovery_ticket = ?, rec_action = ?, rec_entry = ?, rec_sl = ?, rec_tp = ?, rec_volume = ? WHERE id = ?", (rec_ticket, rec_action, rec_entry, rec_sl, rec_tp, rec_volume, group_id))
                            else:
                                send_telegram_message(f"🛑 {prefix} {symbol} SL Hit! \n❌ Failed to open Recovery Trade (Execution error).")
                                c.execute("UPDATE trade_groups SET status = 'CLOSED_SL' WHERE id = ?", (group_id,))
                        else:
                            send_telegram_message(f"🛑 {prefix} {symbol} SL Hit! \n❌ Failed to open Recovery (No tick data).")
                            c.execute("UPDATE trade_groups SET status = 'CLOSED_SL' WHERE id = ?", (group_id,))
                    else:
                        send_telegram_message(f"🛑 {prefix} {symbol} SL Hit! \n❌ Failed to open Recovery (ATR calc error).")
                        c.execute("UPDATE trade_groups SET status = 'CLOSED_SL' WHERE id = ?", (group_id,))
                conn.commit()
                conn.close()
                notify_clients("tracker_update", "update")
        return

    if status == 'ACTIVE_T2_SL_ORIGINAL':
        pos = mt5.positions_get(ticket=t2_ticket)
        if not pos or len(pos) == 0:
            deals = mt5.history_deals_get(position=t2_ticket)
            if deals and len(deals) > 0:
                out_deals = [d for d in deals if d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_INOUT)]
                if len(out_deals) > 0:
                    out_deal = out_deals[-1]
                    profit = out_deal.profit
                    comment = out_deal.comment.lower()
                    conn = sqlite3.connect('trades.db')
                    c = conn.cursor()
                    
                    if profit > 0 and 'tp' in comment:
                        c.execute("UPDATE trade_groups SET status = 'SUCCESS_TP2_HIT' WHERE id = ?", (group_id,))
                        send_telegram_message(f"🎯 {prefix} {symbol} TP2 (1.75R) Hit! Trade fully closed.")
                    else:
                        c.execute("UPDATE trade_groups SET status = 'CLOSED_T2_SL' WHERE id = ?", (group_id,))
                        send_telegram_message(f"🛡️ {prefix} {symbol} T2 Stopped Out at Original SL.")
                    conn.commit()
                    conn.close()
                    notify_clients("tracker_update", "update")
            return
            
        # T2 Trailing SL logic has been fully removed. T2 will run until original SL or TP.
        return


def poller_thread():
    global global_mt5_status, global_was_time_disabled
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
                    c.execute("SELECT id, magic_number, symbol, trade_1_ticket, trade_2_ticket, action, entry_price, sl, tp1, tp2, status FROM trade_groups WHERE status IN ('ACTIVE', 'PENDING_ORIGINAL', 'ACTIVE_T2_SL_ORIGINAL', 'ACTIVE_T2_SL_MINUS_0_5', 'ACTIVE_T2_SL_PLUS_0_25')")
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
                        c.execute("SELECT id, magic_number, symbol, trade_1_ticket, trade_2_ticket, action, entry_price, sl, tp1, tp2, status FROM trade_groups WHERE status IN ('ACTIVE', 'PENDING_ORIGINAL', 'ACTIVE_T2_SL_ORIGINAL', 'ACTIVE_T2_SL_MINUS_0_5', 'ACTIVE_T2_SL_PLUS_0_25') AND instance_id = ?", (inst_id,))
                        active_groups = c.fetchall()
                        for group in active_groups:
                            check_trade_group(group, inst_path, inst_name, symbol_suffix)
                
                is_any_online = online_count > 0
                status_text = f"MT5: {online_count}/{total_count} Online" if total_count > 0 else "No Instances"
                status_data = json.dumps({"online": is_any_online, "text": status_text})
            
            if status_data != global_mt5_status:
                global_mt5_status = status_data
                notify_clients("mt5_status", status_data)
            
            c.execute("SELECT disable_time_start, disable_time_end FROM global_settings WHERE id = 1")
            global_row = c.fetchone()
            if global_row:
                disable_time_start = global_row[0]
                disable_time_end = global_row[1]
                if disable_time_start and disable_time_end:
                    is_time_disabled = is_time_in_range(disable_time_start, disable_time_end)
                    if is_time_disabled and not global_was_time_disabled:
                        global_was_time_disabled = True
                        send_telegram_message(f"🛑 Stop trading for the day. Trade Disable Time Period ({disable_time_start} - {disable_time_end}) has started.")
                        logging.info("Entered Trade Disable Time Period.")
                    elif not is_time_disabled and global_was_time_disabled:
                        global_was_time_disabled = False
                        send_telegram_message("▶️ Starting again. Trade Disable Time Period has ended.")
                        logging.info("Exited Trade Disable Time Period.")
                else:
                    global_was_time_disabled = False
                    
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
    c.execute("SELECT id, magic_number, symbol, trade_1_ticket, trade_2_ticket, action, entry_price, sl, tp1, tp2, status FROM trade_groups WHERE status IN ('ACTIVE', 'PENDING_ORIGINAL', 'ACTIVE_T2_SL_ORIGINAL', 'ACTIVE_T2_SL_MINUS_0_5', 'ACTIVE_T2_SL_PLUS_0_25')")
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

@flask_app.route('/api/global_settings', methods=['GET', 'POST'])
def api_global_settings():
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    if request.method == 'GET':
        c.execute("SELECT trade_disable, disable_time_start, disable_time_end FROM global_settings WHERE id = 1")
        row = c.fetchone()
        conn.close()
        if row:
            return jsonify({"trade_disable": bool(row[0]), "disable_time_start": row[1], "disable_time_end": row[2]})
        return jsonify({"trade_disable": False, "disable_time_start": "", "disable_time_end": ""})
    else:
        data = request.json
        trade_disable = int(data.get('trade_disable', 0))
        disable_time_start = data.get('disable_time_start', '')
        disable_time_end = data.get('disable_time_end', '')
        c.execute("SELECT id FROM global_settings WHERE id = 1")
        if c.fetchone():
            c.execute("UPDATE global_settings SET trade_disable=?, disable_time_start=?, disable_time_end=? WHERE id=1", 
                      (trade_disable, disable_time_start, disable_time_end))
        else:
            c.execute("INSERT INTO global_settings (id, trade_disable, disable_time_start, disable_time_end) VALUES (1, ?, ?, ?)", 
                      (trade_disable, disable_time_start, disable_time_end))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})

@flask_app.route('/api/instances', methods=['GET', 'POST', 'DELETE', 'PUT'])
def api_instances():
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    
    if request.method == 'GET':
        try:
            c.execute("SELECT id, name, path, risk_usd, symbol_mapping, auto_trade, accepted_timeframe, profit_limit, profit_limit_start_time FROM instances ORDER BY id ASC")
        except sqlite3.OperationalError:
            c.execute("SELECT id, name, path, risk_usd, symbol_mapping, auto_trade, accepted_timeframe FROM instances ORDER BY id ASC")
            
        rows = c.fetchall()
        instances = []
        for r in rows:
            inst_id = r[0]
            profit_limit = r[7] if len(r) > 7 else 0
            profit_limit_start_time = r[8] if len(r) > 8 else 0
            current_profit = 0
            
            if profit_limit and profit_limit > 0 and profit_limit_start_time > 0:
                c.execute("SELECT SUM(profit) FROM trading_log WHERE instance_id = ? AND COALESCE(local_time, time) >= ?", (inst_id, profit_limit_start_time))
                res = c.fetchone()
                closed_profit = res[0] if res and res[0] else 0
                unrealized_profit = get_unrealized_profit(r[2])
                current_profit = closed_profit + unrealized_profit
                
            instances.append({
                "id": inst_id, "name": r[1], "path": r[2], "risk_usd": r[3], 
                "symbol_mapping": r[4], "auto_trade": r[5], "accepted_timeframe": r[6] or 'all',
                "profit_limit": profit_limit or 0, "profit_limit_start_time": profit_limit_start_time or 0,
                "current_profit": current_profit
            })
        conn.close()
        return jsonify(instances)
        
    elif request.method == 'POST':
        data = request.json
        name = data.get('name')
        path = data.get('path')
        risk_usd = float(data.get('risk_usd', 100.0))
        symbol_mapping = data.get('symbol_mapping', '{}')
        auto_trade = int(data.get('auto_trade', 0))
        accepted_timeframe = data.get('accepted_timeframe', 'all')
        profit_limit = float(data.get('profit_limit', 0))
        import time
        profit_limit_start_time = int(time.time())
        
        if not name or not path:
            conn.close()
            return jsonify({"error": "Name and path required"}), 400
            
        try:
            c.execute("INSERT INTO instances (name, path, risk_usd, symbol_mapping, auto_trade, accepted_timeframe, profit_limit, profit_limit_start_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (name, path, risk_usd, symbol_mapping, auto_trade, accepted_timeframe, profit_limit, profit_limit_start_time))
        except sqlite3.OperationalError:
            c.execute("INSERT INTO instances (name, path, risk_usd, symbol_mapping, auto_trade, accepted_timeframe) VALUES (?, ?, ?, ?, ?, ?)", (name, path, risk_usd, symbol_mapping, auto_trade, accepted_timeframe))
            
        conn.commit()
        new_id = c.lastrowid
        conn.close()
        return jsonify({"id": new_id, "name": name, "path": path, "risk_usd": risk_usd, "symbol_mapping": symbol_mapping, "auto_trade": auto_trade, "accepted_timeframe": accepted_timeframe, "profit_limit": profit_limit}), 201
        
    elif request.method == 'PUT':
        data = request.json
        instance_id = data.get('id')
        name = data.get('name')
        path = data.get('path')
        risk_usd = float(data.get('risk_usd', 100.0))
        symbol_mapping = data.get('symbol_mapping', '{}')
        auto_trade = int(data.get('auto_trade', 0))
        accepted_timeframe = data.get('accepted_timeframe', 'all')
        profit_limit = float(data.get('profit_limit', 0))
        
        if not instance_id or not name or not path:
            conn.close()
            return jsonify({"error": "ID, name and path required"}), 400
            
        try:
            c.execute("UPDATE instances SET name=?, path=?, risk_usd=?, symbol_mapping=?, auto_trade=?, accepted_timeframe=?, profit_limit=? WHERE id=?", (name, path, risk_usd, symbol_mapping, auto_trade, accepted_timeframe, profit_limit, instance_id))
        except sqlite3.OperationalError:
            c.execute("UPDATE instances SET name=?, path=?, risk_usd=?, symbol_mapping=?, auto_trade=?, accepted_timeframe=? WHERE id=?", (name, path, risk_usd, symbol_mapping, auto_trade, accepted_timeframe, instance_id))
            
        conn.commit()
        conn.close()
        return jsonify({"status": "success"}), 200
        
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

@flask_app.route('/api/instances/reset_profit', methods=['POST'])
def api_instances_reset_profit():
    data = request.json
    instance_id = data.get('id')
    if not instance_id:
        return jsonify({"error": "ID required"}), 400
        
    import time
    profit_limit_start_time = int(time.time())
    
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    try:
        c.execute("UPDATE instances SET profit_limit_start_time=? WHERE id=?", (profit_limit_start_time, instance_id))
        conn.commit()
    except sqlite3.OperationalError:
        pass
    finally:
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
            c.execute(f"{query_base} WHERE t.status IN ('PENDING_ORIGINAL', 'ACTIVE', 'ACTIVE_T2_SL_ORIGINAL', 'ACTIVE_T2_SL_MINUS_0_5', 'ACTIVE_T2_SL_PLUS_0_25', 'FAILED_EXECUTION') ORDER BY t.symbol ASC, t.id DESC LIMIT 100")
        else:
            c.execute(f"{query_base} WHERE t.status IN ('SUCCESS_TP1_HIT', 'SUCCESS_TP2_HIT', 'CLOSED_SL', 'CLOSED_T2_SL', 'CANCELLED') ORDER BY t.symbol ASC, t.id DESC LIMIT 100")
            
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

def is_trade_allowed(instance_id, symbol, action):
    """
    Checks if a trade signal in 'action' (BUY/SELL) direction is allowed.
    Rule: If there is an active trade group for this symbol on this instance
    in the same direction (action), the new trade is ignored.
    Opposite direction trades are always allowed even if not hit TP1.
    
    NOTE: As soon as a trade hits TP1, the bridge updates its status to 'SUCCESS_TP1_HIT'.
    Therefore, by querying only 'PENDING_ORIGINAL' and 'ACTIVE', 
    we ensure that once TP1 is hit (or if a recovery trade is running), the existing trade 
    group is no longer considered blocking, and a new same-side signal is allowed to execute.
    """
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    if instance_id is None:
        c.execute("""
            SELECT COUNT(*) FROM trade_groups 
            WHERE instance_id IS NULL AND symbol = ? AND action = ? 
              AND status IN ('PENDING_ORIGINAL', 'ACTIVE')
        """, (symbol, action.upper()))
    else:
        c.execute("""
            SELECT COUNT(*) FROM trade_groups 
            WHERE instance_id = ? AND symbol = ? AND action = ? 
              AND status IN ('PENDING_ORIGINAL', 'ACTIVE')
        """, (instance_id, symbol, action.upper()))
    count = c.fetchone()[0]
    conn.close()
    return count == 0

def is_time_in_range(start_str, end_str):
    if not start_str or not end_str:
        return False
    try:
        now = datetime.now().time()
        start = datetime.strptime(start_str, '%H:%M').time()
        end = datetime.strptime(end_str, '%H:%M').time()
        if start <= end:
            return start <= now <= end
        else:
            return start <= now or now <= end
    except Exception as e:
        return False

def check_global_disabled():
    try:
        conn = sqlite3.connect('trades.db')
        c = conn.cursor()
        c.execute("SELECT trade_disable, disable_time_start, disable_time_end FROM global_settings WHERE id = 1")
        row = c.fetchone()
        conn.close()
        if not row:
            return False, ""
        
        trade_disable = bool(row[0])
        disable_time_start = row[1]
        disable_time_end = row[2]
        
        if trade_disable:
            return True, "Global trade is disabled manually."
            
        if disable_time_start and disable_time_end:
            if is_time_in_range(disable_time_start, disable_time_end):
                return True, f"Current time is within Trade Disable Time Period ({disable_time_start} - {disable_time_end})."
                
        return False, ""
    except Exception as e:
        return False, ""

def process_signal(data):
    is_disabled, reason = check_global_disabled()
    if is_disabled:
        symbol = data.get('symbol', '')
        msg = f"⚠️ Signal received for {symbol} but not executing: {reason}"
        logging.info(msg)
        send_telegram_message(msg)
        return {"status": "skipped", "message": msg}
        
    action = data.get('action', '').upper()
    symbol = data.get('symbol', '')
    try:
        entry = float(data.get('entry', 0))
    except:
        entry = 0.0
    sl = float(data.get('sl', 0))
    tp1 = float(data.get('tp1', 0))
    tp2 = float(data.get('tp2', 0))
    signal_timeframe = str(data.get('timeframe', 'all'))
    
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    try:
        c.execute("SELECT id, name, path, risk_usd, symbol_mapping, auto_trade, accepted_timeframe, profit_limit, profit_limit_start_time FROM instances ORDER BY id ASC")
    except sqlite3.OperationalError:
        c.execute("SELECT id, name, path, risk_usd, symbol_mapping, auto_trade, accepted_timeframe FROM instances ORDER BY id ASC")
    instances = c.fetchall()
    conn.close()
    
    if not instances:
        instances = [(None, "Default", None, 100.0, "{}", 0, "all", 0, 0)]
        
    auto_results = []
    manual_executions = []
    
    for inst in instances:
        inst_id = inst[0]
        inst_name = inst[1]
        inst_path = inst[2]
        risk_usd = inst[3]
        symbol_mapping = inst[4]
        auto_trade = inst[5]
        accepted_timeframe = inst[6]
        profit_limit = inst[7] if len(inst) > 7 else 0
        profit_limit_start_time = inst[8] if len(inst) > 8 else 0
        
        if not accepted_timeframe:
            accepted_timeframe = 'all'
            
        if profit_limit and profit_limit > 0 and profit_limit_start_time > 0:
            conn2 = sqlite3.connect('trades.db')
            c2 = conn2.cursor()
            c2.execute("SELECT SUM(profit) FROM trading_log WHERE instance_id = ? AND COALESCE(local_time, time) >= ?", (inst_id, profit_limit_start_time))
            res = c2.fetchone()
            closed_profit = res[0] if res and res[0] else 0
            conn2.close()
            
            unrealized_profit = get_unrealized_profit(inst_path)
            current_profit = closed_profit + unrealized_profit
            
            if current_profit >= profit_limit:
                msg = f"⚠️ {inst_name} has reached its Profit Limit of ${profit_limit}. Current Session Profit: ${current_profit:.2f}. No new trades will be executed."
                logging.info(msg)
                send_telegram_message(msg)
                continue
        
        # Apply symbol mapping if exists
        actual_symbol = symbol
        if symbol_mapping:
            try:
                import json
                mapping = json.loads(symbol_mapping)
                if symbol in mapping:
                    actual_symbol = mapping[symbol]
            except Exception as e:
                logging.error(f"Error parsing symbol mapping for {inst_name}: {e}")
                
        calculated_volume = calculate_volume(actual_symbol, entry, sl, risk_usd, inst_path, "")
        
        step = 0.01
        min_vol = 0.01
        actual_entry = entry
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
            
        rec_action, rec_entry, rec_sl, rec_tp, rec_volume = None, None, None, None, None
        
        exec_payload = {
            "id": inst_id,
            "name": inst_name,
            "path": inst_path,
            "risk_usd": risk_usd,
            "symbol_mapping": symbol_mapping,
            "actual_symbol": actual_symbol,
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
        }
        
        # Determine if Auto Trade Mode is active for this specific timeframe
        is_auto = (auto_trade == 1) and (accepted_timeframe == 'all' or accepted_timeframe == signal_timeframe)
        
        if auto_trade and not is_auto:
            logging.info(f"[{inst_name}] Timeframe mismatch (Signal: {signal_timeframe}, Accepted: {accepted_timeframe}). Falling back to manual confirmation.")
            
        if is_auto:
            # Check same-side rule
            allowed = is_trade_allowed(inst_id, symbol, action)
            if not allowed:
                logging.info(f"[{inst_name}] Ignored same-side signal for {symbol} {action} (Active trade exists)")
                auto_results.append({
                    "name": inst_name,
                    "status": "ignored",
                    "reason": "Active same-side trade exists"
                })
                continue
                
            # Execute trade automatically
            magic_number = random.randint(100000, 999999)
            t1_ticket = None
            t2_ticket = None
            
            if split_trade:
                t1_ticket = execute_trade(actual_symbol, action, sl, tp1, vol1, entry, inst_path, magic_number, "Orig_TP1", "")
                t2_ticket = execute_trade(actual_symbol, action, sl, tp2, vol2, entry, inst_path, magic_number, "Orig_TP2", "")
            else:
                t1_ticket = execute_trade(actual_symbol, action, sl, tp1, vol1, entry, inst_path, magic_number, "Orig_TP1", "")
                
            status = 'PENDING_ORIGINAL' if t1_ticket else 'FAILED_EXECUTION'
            
            conn_db = sqlite3.connect('trades.db')
            c_db = conn_db.cursor()
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            c_db.execute('''
                INSERT INTO trade_groups (
                    instance_id, magic_number, symbol, action, entry_price, sl, tp1, tp2, vol1, vol2, split_trade,
                    trade_1_ticket, trade_2_ticket, recovery_ticket, rec_action, rec_entry, rec_sl, rec_tp, rec_volume, status, created_at, signal_timeframe, execution_mode
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                inst_id, magic_number, symbol, action, entry, sl, tp1, tp2, vol1, vol2, 1 if split_trade else 0,
                t1_ticket, t2_ticket, None, rec_action, rec_entry, rec_sl, rec_tp, rec_volume, status, now_str, signal_timeframe, 'Auto'
            ))
            conn_db.commit()
            conn_db.close()
            
            if status == 'FAILED_EXECUTION':
                logging.error(f"[{inst_name}] Failed to auto-execute. Marked as failed.")
                auto_results.append({
                    "name": inst_name,
                    "status": "failed",
                    "reason": "MT5 execution failed"
                })
            else:
                logging.info(f"[{inst_name}] Auto-Executed trade group [Magic {magic_number}] (Status: {status}).")
                auto_results.append({
                    "name": inst_name,
                    "status": "executed",
                    "ticket1": t1_ticket,
                    "ticket2": t2_ticket,
                    "success": True
                })
                # Trigger Web UI tracker refresh
                notify_clients("tracker_update", "update")
        else:
            # Manual execution required
            manual_executions.append(exec_payload)
            
    logging.info(f"Signal received for {symbol}. Processed executions. Waiting for UI signal routing...")
    
    # Build message and send Telegram notification
    msg = f"🔔 NEW TRADINGVIEW SIGNAL\n\n"
    msg += f"Symbol: {symbol}\n"
    msg += f"Action: {action}\n"
    if entry > 0:
        msg += f"Entry Level: {entry} (Limit/Stop Order)\n"
    else:
        msg += f"Entry Level: Market\n"
    msg += f"Stop Loss: {sl}\n"
    msg += f"Take Profit 1: {tp1}\n"
    if tp2 != 0:
        msg += f"Take Profit 2: {tp2}\n\n"
        
    if auto_results:
        msg += "🤖 AUTO EXECUTIONS:\n"
        for res in auto_results:
            if res['status'] == 'executed':
                t_str = f"Ticket {res['ticket1']}"
                if res.get('ticket2'):
                    t_str += f" / {res['ticket2']}"
                msg += f"✅ {res['name']}: Auto-Executed ({t_str})\n"
            elif res['status'] == 'ignored':
                msg += f"⚠️ {res['name']}: Ignored ({res['reason']})\n"
            else:
                msg += f"❌ {res['name']}: FAILED ({res['reason']})\n"
        msg += "\n"
        
    if manual_executions:
        msg += "✍️ PENDING MANUAL CONFIRMATION:\n"
        for exec_data in manual_executions:
            msg += f"Broker: {exec_data['name']}\n"
            msg += f"Risk: ${exec_data['risk_usd']}\n"
            if exec_data['split_trade']:
                msg += f"Lot Size: {exec_data['calculated_volume']} (Split: {exec_data['vol1']} / {exec_data['vol2']})\n"
            else:
                msg += f"Lot Size: {exec_data['calculated_volume']} (Single)\n"
            msg += "\n"
        msg += f"Do you want to execute these now?"
        
    send_telegram_message(msg)
    
    # Enhance data for the UI
    ui_data = {
        'action': action,
        'symbol': symbol,
        'entry': entry,
        'sl': sl,
        'tp1': tp1,
        'tp2': tp2,
        'timeframe': signal_timeframe,
        'auto_results': auto_results,
        'manual_executions': manual_executions
    }
    
    # Send to UI via SSE
    notify_clients("trade_signal", json.dumps(ui_data))

@flask_app.route('/api/execute_trade', methods=['POST'])
def api_execute_trade():
    data = request.json
    symbol = data.get('symbol')
    action = data.get('action')
    sl = float(data.get('sl', 0))
    tp1 = float(data.get('tp1', 0))
    tp2 = float(data.get('tp2', 0))
    entry = float(data.get('entry', 0))
    timeframe = data.get('timeframe', 'Unknown')
    
    instance_executions = data.get('instance_executions', [])
    
    logging.info(f"User clicked EXECUTE for {symbol}.")
    
    magic_number = random.randint(100000, 999999)
    
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    
    for exec_data in instance_executions:
        inst_id = exec_data.get('id')
        inst_name = exec_data.get('name')
        inst_path = exec_data.get('path')
        actual_symbol = exec_data.get('actual_symbol', symbol)
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
            t1_ticket = execute_trade(actual_symbol, action, sl, tp1, vol1, entry, inst_path, magic_number, "Orig_TP1", "")
            t2_ticket = execute_trade(actual_symbol, action, sl, tp2, vol2, entry, inst_path, magic_number, "Orig_TP2", "")
        else:
            t1_ticket = execute_trade(actual_symbol, action, sl, tp1, vol1, entry, inst_path, magic_number, "Orig_TP1", "")
            
        status = 'PENDING_ORIGINAL' if t1_ticket else 'FAILED_EXECUTION'
        
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute('''
            INSERT INTO trade_groups (
                instance_id, magic_number, symbol, action, entry_price, sl, tp1, tp2, vol1, vol2, split_trade,
                trade_1_ticket, trade_2_ticket, recovery_ticket, rec_action, rec_entry, rec_sl, rec_tp, rec_volume, status, created_at, signal_timeframe, execution_mode
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            inst_id, magic_number, symbol, action, entry, sl, tp1, tp2, vol1, vol2, split_int,
            t1_ticket, t2_ticket, None, rec_action, rec_entry, rec_sl, rec_tp, rec_volume, status, now_str, timeframe, 'Manual'
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
        SELECT t.magic_number, t.symbol, t.action, t.entry_price, t.sl, t.tp1, t.tp2, t.vol1, t.vol2, t.split_trade, i.path, i.symbol_mapping
        FROM trade_groups t
        LEFT JOIN instances i ON t.instance_id = i.id
        WHERE t.id = ? AND t.status = 'FAILED_EXECUTION'
    """, (trade_id,))
    row = c.fetchone()
    
    if not row:
        conn.close()
        return jsonify({"error": "Trade not found or not in failed state"}), 404
        
    magic_number, symbol, action, entry, sl, tp1, tp2, vol1, vol2, split_trade, inst_path, symbol_mapping = row
    
    # Apply symbol mapping if exists
    actual_symbol = symbol
    if symbol_mapping:
        try:
            import json
            mapping = json.loads(symbol_mapping)
            if symbol in mapping:
                actual_symbol = mapping[symbol]
        except Exception as e:
            logging.error(f"Error parsing symbol mapping for retry: {e}")
            
    t1_ticket = None
    t2_ticket = None
    
    if split_trade:
        t1_ticket = execute_trade(actual_symbol, action, sl, tp1, vol1, entry, inst_path, magic_number, "Orig_TP1", "")
        t2_ticket = execute_trade(actual_symbol, action, sl, tp2, vol2, entry, inst_path, magic_number, "Orig_TP2", "")
    else:
        t1_ticket = execute_trade(actual_symbol, action, sl, tp1, vol1, entry, inst_path, magic_number, "Orig_TP1", "")
        
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

@flask_app.route('/api/place_recovery_trade', methods=['POST'])
def api_place_recovery_trade():
    data = request.json
    trade_id = data.get('id')
    if not trade_id:
        return jsonify({"error": "Trade ID required"}), 400
        
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    c.execute("""
        SELECT t.magic_number, t.symbol, t.rec_action, t.rec_entry, t.rec_sl, t.rec_tp, t.rec_volume, i.path, i.symbol_mapping, i.symbol_suffix
        FROM trade_groups t
        LEFT JOIN instances i ON t.instance_id = i.id
        WHERE t.id = ? AND t.status = 'ACTIVE' AND (t.recovery_ticket IS NULL OR t.recovery_ticket = 0)
    """, (trade_id,))
    row = c.fetchone()
    
    if not row:
        conn.close()
        return jsonify({"error": "Trade not found, not active, or recovery already placed"}), 404
        
    magic_number, symbol, rec_action, rec_entry, rec_sl, rec_tp, rec_volume, inst_path, symbol_mapping, symbol_suffix = row
    
    # Apply symbol mapping if exists
    actual_symbol = symbol
    if symbol_mapping:
        try:
            import json
            mapping = json.loads(symbol_mapping)
            if symbol in mapping:
                actual_symbol = mapping[symbol]
        except Exception as e:
            logging.error(f"Error parsing symbol mapping for recovery: {e}")
            
    new_rec_ticket = execute_trade(actual_symbol, rec_action, rec_sl, rec_tp, rec_volume, rec_entry, inst_path, magic_number, "Recovery", symbol_suffix)
    
    if new_rec_ticket:
        c.execute("UPDATE trade_groups SET recovery_ticket=? WHERE id=?", (new_rec_ticket, trade_id))
        conn.commit()
        logging.info(f"Recovery trade placed successfully for Trade ID {trade_id}, Ticket: {new_rec_ticket}")
        res = {"status": "success", "ticket": new_rec_ticket}
    else:
        logging.error(f"Failed to place recovery trade for Trade ID {trade_id}")
        res = {"status": "failed", "error": "Execution failed"}
        
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
        
        # Calculate MT5 to Local Time Offset
        time_offset = 0
        if len(deals) > 0:
            import time
            for d in reversed(deals):
                if d.symbol:
                    mt5.symbol_select(d.symbol, True)
                    tick = mt5.symbol_info_tick(d.symbol)
                    if tick and tick.time > 0:
                        time_offset = int(time.time()) - tick.time
                        logging.info(f"Calculated time offset for {inst_name}: {time_offset} seconds (using {d.symbol})")
                        break
        
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
                local_start_time = pos_deals[0].time + time_offset
            else:
                total_profit = deal.profit
                total_comm = deal.commission
                total_swap = deal.swap
                net_profit = deal.profit + deal.commission + deal.swap
                logging.info(f"Deal {deal.ticket} (no pos deals): Profit={deal.profit}, Comm={deal.commission}, Swap={deal.swap}, Net={net_profit}")
                local_start_time = deal.time + time_offset
            
            local_close_time = deal.time + time_offset
            
            try:
                c.execute('''
                    INSERT INTO trading_log (
                        instance_id, ticket, symbol, type, volume, profit, time, magic, comment, commission, swap, raw_profit, local_start_time, local_time
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    inst_id, deal.ticket, deal.symbol, deal.type, deal.volume, net_profit, deal.time, deal.magic, deal.comment, total_comm, total_swap, total_profit, local_start_time, local_close_time
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
    start_time = request.args.get('start_time')
    end_time = request.args.get('end_time')
    
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    
    query = "SELECT l.id, l.instance_id, i.name, l.ticket, l.symbol, l.type, l.volume, l.profit, l.time, l.magic, l.comment, l.commission, l.swap, l.raw_profit, l.local_start_time, l.local_time FROM trading_log l LEFT JOIN instances i ON l.instance_id = i.id"
    conditions = []
    params = []
    
    if inst_id and inst_id != 'all':
        conditions.append("l.instance_id = ?")
        params.append(inst_id)
        
    if start_time:
        conditions.append("COALESCE(l.local_time, l.time) >= ?")
        params.append(int(start_time))
        
    if end_time:
        conditions.append("COALESCE(l.local_time, l.time) <= ?")
        params.append(int(end_time))
        
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
        
    query += " ORDER BY COALESCE(l.local_time, l.time) DESC"
    
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
            "raw_profit": r[13],
            "local_start_time": r[14],
            "local_time": r[15]
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

@flask_app.route('/api/story_dates', methods=['GET'])
def api_story_dates():
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    c.execute("SELECT DISTINCT date(created_at) FROM trade_groups WHERE created_at IS NOT NULL ORDER BY date(created_at) DESC")
    rows = c.fetchall()
    conn.close()
    
    dates = [r[0] for r in rows if r[0]]
    return jsonify({"dates": dates})

@flask_app.route('/api/story_notes', methods=['GET'])
def api_story_notes():
    date_str = request.args.get('date')
    instance_id = request.args.get('instance_id', 'all')
    if not date_str:
        return jsonify({"error": "date parameter is required"}), 400
        
    conn = sqlite3.connect('trades.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    if instance_id != 'all':
        c.execute("""
            SELECT * FROM trade_groups 
            WHERE date(created_at) = ? AND instance_id = ?
            ORDER BY created_at ASC
        """, (date_str, instance_id))
    else:
        c.execute("""
            SELECT * FROM trade_groups 
            WHERE date(created_at) = ? 
            ORDER BY created_at ASC
        """, (date_str,))
    trade_groups = c.fetchall()
    
    # Pre-calculate Magic Number Profits
    c.execute("""
        SELECT magic, SUM(profit) as net_profit, COUNT(*) as trades
        FROM trading_log 
        GROUP BY magic
    """)
    magic_profits = {row['magic']: row['net_profit'] for row in c.fetchall()}
    
    # Pre-calculate individual ticket profits grouped by magic (ordered by time)
    c.execute("SELECT magic, profit FROM trading_log ORDER BY time ASC")
    magic_deals = {}
    for row in c.fetchall():
        m = row['magic']
        if m not in magic_deals:
            magic_deals[m] = []
        magic_deals[m].append(row['profit'])
    
    conn.close()
    
    total_profit = 0
    total_trades = len(trade_groups)
    win_trades = 0
    loss_trades = 0
    
    stories = []
    
    for idx, tg in enumerate(trade_groups):
        magic = tg['magic_number']
        pl = magic_profits.get(magic, 0)
        
        deals = magic_deals.get(magic, [])
        t1_pl = deals[0] if len(deals) > 0 else None
        t2_pl = deals[1] if len(deals) > 1 else None
        
        if pl > 0:
            win_trades += 1
        elif pl < 0:
            loss_trades += 1
            
        total_profit += pl
        
        story = {
            'id': idx + 1,
            'magic': magic,
            'time': tg['created_at'].split(' ')[1] if tg['created_at'] else "Unknown",
            'mode': tg['execution_mode'] or "Unknown",
            'symbol': tg['symbol'],
            'action': tg['action'],
            'entry': tg['entry_price'],
            'sl': tg['sl'],
            'tp1': tg['tp1'],
            'tp2': tg['tp2'],
            'timeframe': tg['signal_timeframe'] or "Unknown",
            'status': tg['status'],
            'pl': round(pl, 2),
            't1_pl': round(t1_pl, 2) if t1_pl is not None else None,
            't2_pl': round(t2_pl, 2) if t2_pl is not None else None
        }
        stories.append(story)
        
    summary = {
        'total_profit': round(total_profit, 2),
        'total_trades': total_trades,
        'win_trades': win_trades,
        'loss_trades': loss_trades
    }
    
    return jsonify({"summary": summary, "stories": stories})

@flask_app.route('/signal_alert.wav')
def signal_alert():
    try:
        return Response(open('signal_alert.wav', 'rb').read(), mimetype='audio/wav')
    except FileNotFoundError:
        return jsonify({"error": "File not found"}), 404

@flask_app.route('/api/backtest/sessions', methods=['GET', 'POST', 'DELETE'])
def api_backtest_sessions():
    conn = sqlite3.connect('trades.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    if request.method == 'GET':
        c.execute("SELECT * FROM backtest_sessions ORDER BY created_at DESC")
        rows = c.fetchall()
        sessions = [dict(row) for row in rows]
        conn.close()
        return jsonify(sessions)
        
    elif request.method == 'POST':
        data = request.json
        name = data.get('name', 'New Session')
        starting_balance = float(data.get('starting_balance', 10000.0))
        
        c.execute("INSERT INTO backtest_sessions (name, starting_balance) VALUES (?, ?)", (name, starting_balance))
        conn.commit()
        session_id = c.lastrowid
        conn.close()
        return jsonify({"status": "success", "id": session_id})
        
    elif request.method == 'DELETE':
        data = request.json
        session_id = data.get('id')
        if not session_id:
            conn.close()
            return jsonify({"error": "ID required"}), 400
            
        c.execute("DELETE FROM backtest_sessions WHERE id = ?", (session_id,))
        c.execute("DELETE FROM backtest_trades WHERE session_id = ?", (session_id,))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})

@flask_app.route('/api/backtest/trades', methods=['GET', 'POST', 'DELETE'])
def api_backtest_trades():
    conn = sqlite3.connect('trades.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    if request.method == 'GET':
        session_id = request.args.get('session_id')
        if not session_id:
            conn.close()
            return jsonify({"error": "session_id required"}), 400
            
        c.execute("SELECT starting_balance FROM backtest_sessions WHERE id = ?", (session_id,))
        session = c.fetchone()
        if not session:
            conn.close()
            return jsonify({"error": "Session not found"}), 404
            
        current_balance = session['starting_balance']
        
        c.execute("SELECT * FROM backtest_trades WHERE session_id = ? ORDER BY id ASC", (session_id,))
        rows = c.fetchall()
        trades = []
        for row in rows:
            t = dict(row)
            
            # Recalculate breakdown details
            r_usd = t['risk_value'] if t['risk_type'] == '$' else (current_balance * (t['risk_value'] / 100.0))
            r_lot = r_usd / (t['sl_pips'] * 10) if t['sl_pips'] > 0 else 0
            step = 0.01
            lot = round(r_lot / step) * step
            
            if lot >= (step * 2):
                v1 = round((lot / 2) / step) * step
                v2 = lot - v1
            else:
                v1 = lot
                v2 = 0
                
            orig_pl1 = v1 * 10 * t['tp1_pips']
            orig_pl2 = v2 * 10 * t['tp2_pips']
            orig_comm = (v1 + v2) * 7
            
            rec_pl = 0
            rec_comm = 0
            rec_v = 0
            
            if t['recovery_sl_pips'] is not None and t['recovery_tp_pips'] is not None:
                rr_lot = r_usd / (t['recovery_sl_pips'] * 10) if t['recovery_sl_pips'] > 0 else 0
                rec_v = round(rr_lot / step) * step
                rec_pl = rec_v * 10 * t['recovery_tp_pips']
                rec_comm = rec_v * 7
                
            t['breakdown'] = {
                'vol1': round(v1, 2),
                'vol2': round(v2, 2),
                'orig_pl1': orig_pl1,
                'orig_pl2': orig_pl2,
                'orig_comm': orig_comm,
                'rec_vol': round(rec_v, 2),
                'rec_pl': rec_pl,
                'rec_comm': rec_comm
            }
            
            current_balance += t['net_pl']
            trades.append(t)
            
        conn.close()
        return jsonify(trades)
        
    elif request.method == 'POST':
        data = request.json
        session_id = data.get('session_id')
        risk_type = data.get('risk_type', '$')
        risk_value = float(data.get('risk_value', 100))
        sl_pips = float(data.get('sl_pips', 0))
        tp1_pips = float(data.get('tp1_pips', 0))
        tp2_pips = float(data.get('tp2_pips', 0))
        recovery_sl_pips = data.get('recovery_sl_pips')
        recovery_tp_pips = data.get('recovery_tp_pips')
        
        if recovery_sl_pips is not None and recovery_sl_pips != "": recovery_sl_pips = float(recovery_sl_pips)
        else: recovery_sl_pips = None
        if recovery_tp_pips is not None and recovery_tp_pips != "": recovery_tp_pips = float(recovery_tp_pips)
        else: recovery_tp_pips = None
        
        c.execute("SELECT starting_balance FROM backtest_sessions WHERE id = ?", (session_id,))
        session = c.fetchone()
        if not session:
            conn.close()
            return jsonify({"error": "Session not found"}), 404
            
        c.execute("SELECT balance_after FROM backtest_trades WHERE session_id = ? ORDER BY id DESC LIMIT 1", (session_id,))
        last_trade = c.fetchone()
        
        current_balance = last_trade['balance_after'] if last_trade else session['starting_balance']
        
        risk_usd = risk_value if risk_type == '$' else (current_balance * (risk_value / 100.0))
        
        raw_lot_size = risk_usd / (sl_pips * 10) if sl_pips > 0 else 0
        step = 0.01
        
        lot_size = round(raw_lot_size / step) * step
        
        if lot_size >= (step * 2):
            vol1 = round((lot_size / 2) / step) * step
            vol2 = lot_size - vol1
            vol1 = round(vol1, 2)
            vol2 = round(vol2, 2)
        else:
            vol1 = lot_size
            vol2 = 0
        
        gross_pl = (vol1 * 10 * tp1_pips) + (vol2 * 10 * tp2_pips)
        commission = (vol1 + vol2) * 7
        
        if recovery_sl_pips is not None and recovery_tp_pips is not None:
            raw_rec_lot = risk_usd / (recovery_sl_pips * 10) if recovery_sl_pips > 0 else 0
            rec_lot_size = round(raw_rec_lot / step) * step
            
            rec_gross = rec_lot_size * 10 * recovery_tp_pips
            rec_commission = rec_lot_size * 7
            
            gross_pl += rec_gross
            commission += rec_commission
            
        net_pl = gross_pl - commission
        balance_after = current_balance + net_pl
        
        c.execute('''
            INSERT INTO backtest_trades (
                session_id, risk_type, risk_value, sl_pips, tp1_pips, tp2_pips, 
                recovery_sl_pips, recovery_tp_pips, net_pl, balance_after
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (session_id, risk_type, risk_value, sl_pips, tp1_pips, tp2_pips, recovery_sl_pips, recovery_tp_pips, net_pl, balance_after))
        
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "net_pl": net_pl, "balance_after": balance_after})

    elif request.method == 'DELETE':
        data = request.json
        trade_id = data.get('trade_id')
        clear_session_id = data.get('clear_session_id')
        
        if clear_session_id:
            c.execute("DELETE FROM backtest_trades WHERE session_id = ?", (clear_session_id,))
            conn.commit()
            conn.close()
            return jsonify({"status": "success"})
            
        if trade_id:
            c.execute("SELECT session_id FROM backtest_trades WHERE id = ?", (trade_id,))
            row = c.fetchone()
            if not row:
                conn.close()
                return jsonify({"error": "Trade not found"}), 404
                
            session_id = row['session_id']
            c.execute("DELETE FROM backtest_trades WHERE id = ?", (trade_id,))
            
            # Recalculate remaining trades
            c.execute("SELECT starting_balance FROM backtest_sessions WHERE id = ?", (session_id,))
            session = c.fetchone()
            if session:
                current_balance = session['starting_balance']
                c.execute("SELECT * FROM backtest_trades WHERE session_id = ? ORDER BY id ASC", (session_id,))
                trades = c.fetchall()
                
                for t in trades:
                    r_usd = t['risk_value'] if t['risk_type'] == '$' else (current_balance * (t['risk_value'] / 100.0))
                    
                    r_lot = r_usd / (t['sl_pips'] * 10) if t['sl_pips'] > 0 else 0
                    step = 0.01
                    lot = round(r_lot / step) * step
                    
                    if lot >= (step * 2):
                        v1 = round((lot / 2) / step) * step
                        v2 = lot - v1
                    else:
                        v1 = lot
                        v2 = 0
                        
                    g_pl = (v1 * 10 * t['tp1_pips']) + (v2 * 10 * t['tp2_pips'])
                    comm = (v1 + v2) * 7
                    
                    if t['recovery_sl_pips'] is not None and t['recovery_tp_pips'] is not None:
                        rr_lot = r_usd / (t['recovery_sl_pips'] * 10) if t['recovery_sl_pips'] > 0 else 0
                        rl = round(rr_lot / step) * step
                        g_pl += (rl * 10 * t['recovery_tp_pips'])
                        comm += (rl * 7)
                        
                    n_pl = g_pl - comm
                    current_balance += n_pl
                    
                    c.execute("UPDATE backtest_trades SET net_pl = ?, balance_after = ? WHERE id = ?", (n_pl, current_balance, t['id']))
                    
            conn.commit()
            conn.close()
            return jsonify({"status": "success"})
            
        conn.close()
        return jsonify({"error": "No ID provided"}), 400

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
