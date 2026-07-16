import threading
import queue
import logging
import subprocess
import urllib.request
import json
import MetaTrader5 as mt5
from flask import Flask, request, jsonify, render_template, Response
from flask_socketio import SocketIO, emit
import os
import requests
from dotenv import load_dotenv
import sqlite3
import random
import secrets
import time
import webbrowser
import concurrent.futures
from datetime import datetime, timedelta, timezone
import news_calendar

load_dotenv()

# --- GLOBALS & STATE ---
clients = []
global_mt5_status = '{"online": false, "text": "Checking..."}'

recent_logs = []
mt5_history_cache = {}

MAX_RECENT_LOGS = 100

def notify_clients(event, data):
    socketio.emit(event, data)

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
import os
from flask import send_from_directory

basedir = os.path.abspath(os.path.dirname(__file__))
frontend_dist = os.path.join(basedir, 'frontend', 'dist')

# Specify static and template folders to point to the Vite build
flask_app = Flask(__name__, static_folder=frontend_dist, static_url_path='/', template_folder=frontend_dist)
flask_app.config['TEMPLATES_AUTO_RELOAD'] = True
flask_app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(flask_app, cors_allowed_origins="*", async_mode='threading')
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

def send_telegram_message_with_buttons(message, buttons):
    """buttons: list of (label, callback_data) tuples, rendered as a single row of inline buttons.
    Returns the sent message's message_id (needed later to edit it), or None."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id or chat_id == "YOUR_CHAT_ID_HERE":
        logging.warning("Telegram credentials not fully set. Skipping Telegram notification.")
        return None

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "reply_markup": {
            "inline_keyboard": [[{"text": label, "callback_data": data} for label, data in buttons]]
        }
    }

    try:
        response = requests.post(url, json=payload, timeout=5)
        if response.status_code == 200:
            return response.json().get("result", {}).get("message_id")
        else:
            logging.error(f"Failed to send Telegram message with buttons: {response.text}")
            return None
    except Exception as e:
        logging.error(f"Exception while sending Telegram message with buttons: {e}")
        return None

def telegram_edit_message(message_id, new_text):
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id or not message_id:
        return False
    url = f"https://api.telegram.org/bot{bot_token}/editMessageText"
    payload = {"chat_id": chat_id, "message_id": message_id, "text": new_text}
    try:
        response = requests.post(url, json=payload, timeout=5)
        return response.status_code == 200
    except Exception as e:
        logging.error(f"Exception while editing Telegram message: {e}")
        return False

def telegram_answer_callback(callback_query_id, text=""):
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        return
    url = f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery"
    try:
        requests.post(url, json={"callback_query_id": callback_query_id, "text": text}, timeout=5)
    except Exception as e:
        logging.error(f"Exception while answering Telegram callback: {e}")

def telegram_delete_webhook():
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        return
    try:
        requests.post(f"https://api.telegram.org/bot{bot_token}/deleteWebhook", timeout=5)
    except Exception as e:
        logging.error(f"Exception while deleting Telegram webhook: {e}")

def telegram_get_updates(offset, timeout=30):
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        return []
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    try:
        response = requests.get(
            url,
            params={"offset": offset, "timeout": timeout, "allowed_updates": json.dumps(["callback_query"])},
            timeout=timeout + 10
        )
        if response.status_code == 200:
            return response.json().get("result", [])
        else:
            logging.error(f"Failed to poll Telegram getUpdates: {response.text}")
    except Exception as e:
        logging.error(f"Exception while polling Telegram getUpdates: {e}")
    return []

def init_db():
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    
        
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
        
    try:
        c.execute("ALTER TABLE instances ADD COLUMN copier_role TEXT DEFAULT 'NONE'")
    except sqlite3.OperationalError: pass
    try:
        c.execute("ALTER TABLE instances ADD COLUMN copier_risk_type TEXT DEFAULT 'FIXED'")
    except sqlite3.OperationalError: pass
    try:
        c.execute("ALTER TABLE instances ADD COLUMN copier_fixed_lot REAL DEFAULT 0.01")
    except sqlite3.OperationalError: pass
    try:
        c.execute("ALTER TABLE instances ADD COLUMN copier_risk_usd REAL DEFAULT 100.0")
    except sqlite3.OperationalError: pass
    try:
        c.execute("ALTER TABLE instances ADD COLUMN copier_risk_multiplier REAL DEFAULT 1.0")
    except sqlite3.OperationalError: pass
    try:
        c.execute("ALTER TABLE instances ADD COLUMN alert_drawdown_limit REAL DEFAULT 2.0")
    except sqlite3.OperationalError: pass
    try:
        c.execute("ALTER TABLE instances ADD COLUMN alert_daily_profit_target REAL DEFAULT 0.0")
    except sqlite3.OperationalError: pass
    try:
        c.execute("ALTER TABLE instances ADD COLUMN account_type TEXT DEFAULT 'PERSONAL'")
    except sqlite3.OperationalError: pass
    try:
        c.execute("ALTER TABLE instances ADD COLUMN alert_profit_lock_pct REAL DEFAULT 0")
    except sqlite3.OperationalError: pass

    try:
        c.execute("ALTER TABLE instances ADD COLUMN alert_drawdown_levels TEXT DEFAULT '2,4,6,8,10'")
    except sqlite3.OperationalError: pass

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
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS global_settings (
            id INTEGER PRIMARY KEY,
            trade_disable INTEGER DEFAULT 0,
            disable_time_start TEXT DEFAULT '',
            disable_time_end TEXT DEFAULT ''
        )
    ''')
    c.execute("INSERT OR IGNORE INTO global_settings (id, trade_disable, disable_time_start, disable_time_end) VALUES (1, 0, '', '')")

    try:
        c.execute("ALTER TABLE global_settings ADD COLUMN telegram_last_update_id INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass
    try:
        c.execute("ALTER TABLE global_settings ADD COLUMN auto_close_enabled INTEGER DEFAULT 1")
    except sqlite3.OperationalError: pass

    c.execute('''
        CREATE TABLE IF NOT EXISTS daily_equity_baseline (
            instance_id INTEGER,
            date TEXT,
            start_equity REAL,
            PRIMARY KEY (instance_id, date)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS risk_snapshots (
            instance_id INTEGER,
            date TEXT,
            peak_drawdown_pct REAL DEFAULT 0,
            max_risk_usd REAL DEFAULT 0,
            no_sl_count INTEGER DEFAULT 0,
            PRIMARY KEY (instance_id, date)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS blocked_copier_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id INTEGER,
            instance_name TEXT,
            action_type TEXT,
            ticket INTEGER,
            symbol TEXT,
            volume REAL,
            sl REAL,
            tp REAL,
            reason TEXT,
            blocked_at INTEGER,
            status TEXT DEFAULT 'PENDING',
            resolved_at INTEGER
        )
    ''')

    conn.commit()
    conn.close()


def get_historical_equity_curve(current_balance, current_equity):
    import datetime
    today = datetime.datetime.now(tz=datetime.timezone.utc)
    start_date = today - datetime.timedelta(days=14)
    
    deals = mt5.history_deals_get(start_date, today)
    
    daily_profits = {}
    if deals:
        for d in deals:
            dt = datetime.datetime.fromtimestamp(d.time, tz=datetime.timezone.utc)
            date_str = dt.strftime('%m/%d')
            if date_str not in daily_profits:
                daily_profits[date_str] = 0.0
            daily_profits[date_str] += d.profit + getattr(d, 'commission', 0.0) + getattr(d, 'swap', 0.0)
            
    dates = []
    # 14 days ago to today (15 points total, today will be equity)
    for i in range(14, -1, -1):
        d = today - datetime.timedelta(days=i)
        dates.append(d.strftime('%m/%d'))
        
    total_profit_14d = sum(daily_profits.values())
    start_balance = current_balance - total_profit_14d
    
    labels = []
    data = []
    
    running_bal = start_balance
    for i, date_str in enumerate(dates):
        labels.append(date_str)
        if i == len(dates) - 1:
            # Last point is live equity
            data.append(current_equity)
        else:
            running_bal += daily_profits.get(date_str, 0.0)
            data.append(running_bal)
            
    return {"labels": labels, "data": data}


mt5_lock = threading.Lock()

def execute_trade(symbol, action_type, sl, tp, volume, entry_price, instance_path=None, magic=999111, 
                  comment="TradingView Signal", symbol_suffix=""):
    actual_symbol = symbol + symbol_suffix
    with mt5_lock:
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
        if result.retcode != mt5.TRADE_RETCODE_DONE and not is_pending:
            # Retry with FOK
            request["type_filling"] = mt5.ORDER_FILLING_FOK
            result = mt5.order_send(request)
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                # Retry with RETURN
                request["type_filling"] = mt5.ORDER_FILLING_RETURN
                result = mt5.order_send(request)

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logging.error(f"Order failed, retcode={result.retcode}")
            logging.error(f"Error Description: {result.comment}")
            return None
            
        msg = f"Trade Executed Successfully!\nSymbol: {actual_symbol}\nAction: {action_type.upper()}\nVolume: {volume}\nTicket: {result.order}\nPrice: {price}"

        def notify_async():
            logging.info(msg)
            notify_clients("trade_sound", "play")

        threading.Thread(target=notify_async).start()
        
        return result.order

def fetch_instance_data(inst):
    inst_id = inst[0]
    inst_name = inst[1]
    inst_path = inst[2]
    symbol_suffix = inst[3]
    group_name = inst[4]
    
    copier_role = inst[5] if len(inst) > 5 else 'NONE'
    copier_risk_type = inst[6] if len(inst) > 6 else 'FIXED'
    copier_fixed_lot = inst[7] if len(inst) > 7 else 0.01
    copier_risk_usd = inst[8] if len(inst) > 8 else 100.0
    copier_risk_multiplier = inst[9] if len(inst) > 9 else 1.0
    alert_drawdown_limit = inst[10] if len(inst) > 10 else 2.0
    alert_daily_profit_target = inst[11] if len(inst) > 11 else 0.0
    account_type = inst[12] if len(inst) > 12 else 'PERSONAL'
    alert_profit_lock_pct = inst[13] if len(inst) > 13 else 0.0
    alert_drawdown_levels = inst[14] if len(inst) > 14 else '2,4,6,8,10'

    try:
        with mt5_lock:
            if not mt5.initialize(path=inst_path):
                return None
                
            acc = mt5.account_info()
            positions = mt5.positions_get()
            
            inst_risk = {
                "id": inst_id,
                "name": inst_name,
                "group_name": group_name,
                "balance": 0,
                "equity": 0,
                "margin_level": 0,
                "total_risk_usd": 0,
                "drawdown_pct": 0,
                "copier_role": copier_role,
                "copier_risk_type": copier_risk_type,
                "copier_fixed_lot": copier_fixed_lot,
                "copier_risk_usd": copier_risk_usd,
                "copier_risk_multiplier": copier_risk_multiplier,
                "alert_drawdown_limit": alert_drawdown_limit,
                "alert_daily_profit_target": alert_daily_profit_target,
                "account_type": account_type,
                "alert_profit_lock_pct": alert_profit_lock_pct,
                "alert_drawdown_levels": alert_drawdown_levels,
                "positions": [],
                "historical_equity": {"labels": [], "data": []}
            }
            
            if acc:
                inst_risk["balance"] = acc.balance
                inst_risk["equity"] = acc.equity
                inst_risk["margin_level"] = acc.margin_level
                if acc.balance > 0:
                    inst_risk["drawdown_pct"] = max(0, ((acc.balance - acc.equity) / acc.balance) * 100)
                inst_risk["historical_equity"] = get_historical_equity_curve(acc.balance, acc.equity)
                    
            if positions:
                for p in positions:
                    risk_usd = 0
                    if p.sl != 0:
                        calc = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY if p.type == 0 else mt5.ORDER_TYPE_SELL, p.symbol, p.volume, p.price_open, p.sl)
                        if calc is not None:
                            risk_usd = abs(calc)
                        else:
                            sym_info = mt5.symbol_info(p.symbol)
                            if sym_info and sym_info.trade_tick_size and sym_info.trade_tick_value:
                                ticks_lost = abs(p.price_open - p.sl) / sym_info.trade_tick_size
                                risk_usd = ticks_lost * sym_info.trade_tick_value * p.volume
                    inst_risk["total_risk_usd"] += risk_usd
                    
                    tick = mt5.symbol_info_tick(p.symbol)
                    current_price = (tick.bid if p.type == 0 else tick.ask) if tick else p.price_current
                    
                    sym_info = mt5.symbol_info(p.symbol)
                    point = sym_info.point if sym_info else 0.00001
                    dist_sl = abs(current_price - p.sl) / point if p.sl != 0 and point != 0 else -1
                    
                    inst_risk["positions"].append({
                        "ticket": p.ticket,
                        "symbol": p.symbol,
                        "type": "BUY" if p.type == 0 else "SELL",
                        "volume": p.volume,
                        "price_open": p.price_open,
                        "price_current": current_price,
                        "sl": p.sl,
                        "tp": p.tp,
                        "profit": p.profit,
                        "risk_usd": risk_usd,
                        "dist_sl": dist_sl
                    })
                    
            current_time = time.time()
            if inst_id not in mt5_history_cache or (current_time - mt5_history_cache[inst_id]["timestamp"] > 60):
                now_dt = datetime.utcnow()
                today_start_dt = datetime(now_dt.year, now_dt.month, now_dt.day)
                yesterday_start_dt = today_start_dt - timedelta(days=1)
                this_week_start_dt = today_start_dt - timedelta(days=now_dt.weekday())
                last_week_start_dt = this_week_start_dt - timedelta(days=7)
                this_month_start_dt = datetime(now_dt.year, now_dt.month, 1)
                last_month_start_dt = (this_month_start_dt - timedelta(days=1)).replace(day=1)

                deals = mt5.history_deals_get(0, 2147483647)
                gains = {"today": 0.0, "yesterday": 0.0, "week": 0.0, "last_week": 0.0, "month": 0.0, "last_month": 0.0}
                
                if deals:
                    for d in deals:
                        # Ensure we only count deal entries that closed positions (DEAL_ENTRY_OUT / DEAL_ENTRY_OUT_BY)
                        if d.type in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL) and d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY):
                            # Treat the MT5 integer as a raw date without local timezone corruption
                            deal_time = datetime.fromtimestamp(d.time, timezone.utc).replace(tzinfo=None)
                            profit = d.profit + d.commission + d.swap
                            
                            if deal_time >= today_start_dt:
                                gains["today"] += profit
                            elif deal_time >= yesterday_start_dt and deal_time < today_start_dt:
                                gains["yesterday"] += profit
                                
                            if deal_time >= this_week_start_dt:
                                gains["week"] += profit
                            elif deal_time >= last_week_start_dt and deal_time < this_week_start_dt:
                                gains["last_week"] += profit
                                
                            if deal_time >= this_month_start_dt:
                                gains["month"] += profit
                            elif deal_time >= last_month_start_dt and deal_time < this_month_start_dt:
                                gains["last_month"] += profit
                                
                mt5_history_cache[inst_id] = {"timestamp": current_time, "gains": gains}
            
            inst_risk["realized_gains"] = mt5_history_cache[inst_id]["gains"]
            
            return inst_risk
    except Exception as e:
        logging.error(f"Error fetching data for instance {inst_name}: {e}")
        return None

active_positions_cache = {}
drawdown_alert_state = {}
connection_fail_count = {}
last_summary_date = ""

# Profit-lock state machine: inst_id -> {"status": IDLE|APPROACHING|ARMED|MISSED,
# "token": str|None, "date": "YYYY-MM-DD", "message_id": int|None}
# In-memory only (not persisted) so an app restart always reverts to IDLE and
# re-evaluates fresh, rather than risking a stale ARM firing an unattended close.
profit_lock_state = {}
profit_lock_lock = threading.Lock()


def _query_risk_range(c, inst_id, date_from, date_to):
    c.execute(
        "SELECT MAX(peak_drawdown_pct), MAX(max_risk_usd), SUM(no_sl_count) FROM risk_snapshots WHERE instance_id = ? AND date BETWEEN ? AND ?",
        (inst_id, date_from, date_to)
    )
    row = c.fetchone()
    return {
        "peak_drawdown_pct": (row[0] or 0.0) if row else 0.0,
        "max_risk_usd": (row[1] or 0.0) if row else 0.0,
        "no_sl_count": (row[2] or 0) if row else 0,
    }


def _query_trade_stats(c, inst_id, ts_from, ts_to):
    c.execute(
        "SELECT profit FROM trading_log WHERE instance_id = ? AND COALESCE(local_time, time) >= ? AND COALESCE(local_time, time) < ? ORDER BY COALESCE(local_time, time) ASC",
        (inst_id, ts_from, ts_to)
    )
    profits = [row[0] for row in c.fetchall() if row[0] is not None]
    total = len(profits)
    wins = sum(1 for p in profits if p > 0)
    win_rate = (wins / total * 100.0) if total else None
    largest_loss = min(profits) if profits else 0.0
    total_realized = sum(profits)

    max_streak = 0
    cur_streak = 0
    for p in profits:
        if p < 0:
            cur_streak += 1
            max_streak = max(max_streak, cur_streak)
        else:
            cur_streak = 0

    return {
        "total_trades": total, "win_rate": win_rate, "largest_loss": largest_loss,
        "max_loss_streak": max_streak, "total_realized": total_realized,
    }


def _parse_drawdown_levels(raw):
    """Comma-separated ascending drawdown %% thresholds, e.g. '2,4,6,8,10'.
    Blank/unparseable/non-positive entries are dropped silently; result is sorted+deduped."""
    if not raw:
        return []
    levels = []
    for part in str(raw).split(','):
        part = part.strip()
        if not part:
            continue
        try:
            v = float(part)
        except ValueError:
            continue
        if v > 0:
            levels.append(v)
    return sorted(set(levels))


def _format_drawdown_levels(levels):
    return ",".join(("%g" % v) for v in levels)


def build_risk_report(period, risk_payload, c, date_from, date_to, ts_from=None, ts_to=None, title_suffix=""):
    title = {"daily": "Daily Risk Report", "weekly": "Weekly Risk Report", "monthly": "Monthly Risk Report"}[period]
    lines = [f"🛡️ **{title}**{title_suffix}"]

    for r in risk_payload:
        inst_id = r["id"]
        inst_name = r["name"]
        dd_levels = _parse_drawdown_levels(r.get("alert_drawdown_levels", ""))
        dd_limit = dd_levels[0] if dd_levels else 0

        risk = _query_risk_range(c, inst_id, date_from, date_to)
        breach_flag = " ⚠️ breached limit" if dd_limit > 0 and risk["peak_drawdown_pct"] >= dd_limit else ""

        lines.append(f"\n{inst_name}")
        lines.append(f"  Peak drawdown: {risk['peak_drawdown_pct']:.2f}% (limit {dd_limit:.1f}%){breach_flag}")
        lines.append(f"  Max risk exposed: ${risk['max_risk_usd']:.2f}")
        lines.append(f"  Trades without SL: {risk['no_sl_count']}")

        if period in ("weekly", "monthly") and ts_from is not None:
            stats = _query_trade_stats(c, inst_id, ts_from, ts_to)
            if stats["total_trades"] > 0:
                wr = f"{stats['win_rate']:.0f}%" if stats["win_rate"] is not None else "n/a"
                lines.append(f"  Win rate: {wr} ({stats['total_trades']} trades)")
                lines.append(f"  Largest single loss: ${stats['largest_loss']:.2f}")
                lines.append(f"  Max consecutive losses: {stats['max_loss_streak']}")
                lines.append(f"  Realized (context only): ${stats['total_realized']:.2f}")

    return "\n".join(lines)


def poller_thread():
    global global_mt5_status
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)
    
    while True:
        try:
            conn = sqlite3.connect('trades.db')
            c = conn.cursor()
            try:
                c.execute("SELECT id, name, path, symbol_suffix, group_name, copier_role, copier_risk_type, copier_fixed_lot, copier_risk_usd, copier_risk_multiplier, alert_drawdown_limit, alert_daily_profit_target, account_type, alert_profit_lock_pct, alert_drawdown_levels FROM instances")
            except sqlite3.OperationalError:
                try:
                    c.execute("SELECT id, name, path, symbol_suffix, group_name FROM instances")
                except sqlite3.OperationalError:
                    c.execute("SELECT id, name, path, symbol_suffix, 'Ungrouped' as group_name FROM instances")
            instances = c.fetchall()
            inst_path_by_id = {inst[0]: inst[2] for inst in instances}

            risk_payload = []
            
            if not instances:
                if mt5.initialize():
                    status_data = json.dumps({"online": True, "text": "MT5 Connected"})
                else:
                    status_data = json.dumps({"online": False, "text": "MT5 Offline"})
            else:
                total_count = len(instances)
                
                # Fetch all instances concurrently
                futures = [executor.submit(fetch_instance_data, inst) for inst in instances]
                results = [f.result() for f in concurrent.futures.as_completed(futures)]
                
                risk_payload = [r for r in results if r is not None]
                risk_payload.sort(key=lambda x: x.get('id', 0))
                online_count = len(risk_payload)
                
                is_any_online = online_count > 0
                status_text = f"MT5: {online_count}/{total_count} Online" if total_count > 0 else "No Instances"
                status_data = json.dumps({"online": is_any_online, "text": status_text})
            
            if status_data != global_mt5_status:
                global_mt5_status = status_data
                notify_clients("mt5_status", status_data)
                
            if instances:
                notify_clients("risk_data", json.dumps(risk_payload))
                
                global last_summary_date
                current_date_str = datetime.utcnow().strftime("%Y-%m-%d")
                online_ids = set()

                c.execute("SELECT auto_close_enabled FROM global_settings WHERE id = 1")
                auto_close_row = c.fetchone()
                auto_close_enabled = bool(auto_close_row[0]) if auto_close_row and auto_close_row[0] is not None else True

                for r in risk_payload:
                    inst_id = r["id"]
                    inst_name = r["name"]
                    online_ids.add(inst_id)
                    
                    drawdown_pct = r.get("drawdown_pct", 0.0)
                    dd_levels = _parse_drawdown_levels(r.get("alert_drawdown_levels", ""))

                    current_tickets = set(p["ticket"] for p in r.get("positions", []))
                    previous_tickets = active_positions_cache.get(inst_id, set())
                    active_positions_cache[inst_id] = current_tickets

                    newly_opened_tickets = current_tickets - previous_tickets
                    no_sl_opened = 0
                    if newly_opened_tickets:
                        for p in r.get("positions", []):
                            if p["ticket"] in newly_opened_tickets and not p.get("sl"):
                                no_sl_opened += 1
                    
                    for level in dd_levels:
                        state_key = (inst_id, level)
                        if drawdown_pct >= level:
                            if not drawdown_alert_state.get(state_key, False):
                                send_telegram_message(f"⚠️ Drawdown Warning: {inst_name} reached {drawdown_pct:.2f}% (Level: {level:g}%)")
                                drawdown_alert_state[state_key] = True
                        elif drawdown_pct < level - 0.5:
                            drawdown_alert_state[state_key] = False
                            
                    # --- Daily risk snapshot (peak drawdown / max risk exposure / no-SL opens) ---
                    total_risk_usd = r.get("total_risk_usd", 0.0)
                    c.execute("SELECT peak_drawdown_pct, max_risk_usd, no_sl_count FROM risk_snapshots WHERE instance_id = ? AND date = ?", (inst_id, current_date_str))
                    snap_row = c.fetchone()
                    if snap_row is None:
                        c.execute(
                            "INSERT INTO risk_snapshots (instance_id, date, peak_drawdown_pct, max_risk_usd, no_sl_count) VALUES (?, ?, ?, ?, ?)",
                            (inst_id, current_date_str, drawdown_pct, total_risk_usd, no_sl_opened)
                        )
                    else:
                        new_peak_dd = max(snap_row[0] or 0.0, drawdown_pct)
                        new_max_risk = max(snap_row[1] or 0.0, total_risk_usd)
                        new_no_sl_count = (snap_row[2] or 0) + no_sl_opened
                        c.execute(
                            "UPDATE risk_snapshots SET peak_drawdown_pct = ?, max_risk_usd = ?, no_sl_count = ? WHERE instance_id = ? AND date = ?",
                            (new_peak_dd, new_max_risk, new_no_sl_count, inst_id, current_date_str)
                        )

                    # --- Profit-lock state machine (arm-then-auto-close on unrealized % target) ---
                    lock_target = r.get("alert_profit_lock_pct", 0.0)
                    if lock_target > 0:
                        equity = r.get("equity", 0.0)
                        balance = r.get("balance", 0.0)

                        c.execute("SELECT start_equity FROM daily_equity_baseline WHERE instance_id = ? AND date = ?", (inst_id, current_date_str))
                        baseline_row = c.fetchone()
                        if baseline_row is None:
                            c.execute("INSERT OR IGNORE INTO daily_equity_baseline (instance_id, date, start_equity) VALUES (?, ?, ?)", (inst_id, current_date_str, equity))
                            start_equity = equity
                        else:
                            start_equity = baseline_row[0] or equity

                        unrealized_pct = ((equity - balance) / start_equity * 100) if start_equity > 0 else 0.0
                        pre_alert_level = lock_target * 0.75
                        disarm_level = lock_target * 0.5

                        with profit_lock_lock:
                            state = profit_lock_state.get(inst_id)
                            if state is None or state.get("date") != current_date_str:
                                state = {"status": "IDLE", "token": None, "date": current_date_str, "message_id": None}
                                profit_lock_state[inst_id] = state

                            if not current_tickets and state["status"] in ("APPROACHING", "ARMED"):
                                state["status"] = "IDLE"
                                state["token"] = None

                            status = state["status"]

                            if status == "IDLE":
                                if unrealized_pct >= lock_target:
                                    send_telegram_message(
                                        f"ℹ️ {inst_name} hit +{unrealized_pct:.2f}% unrealized. I sent an alert earlier "
                                        f"that wasn't armed — this is just a confirmation, closing is on you from here."
                                    )
                                    state["status"] = "MISSED"
                                elif unrealized_pct >= pre_alert_level:
                                    token = secrets.token_hex(4)
                                    state["token"] = token
                                    state["status"] = "APPROACHING"
                                    msg_id = send_telegram_message_with_buttons(
                                        f"🔔 {inst_name} approaching +{lock_target:.2f}% (now +{unrealized_pct:.2f}%). "
                                        f"Tap ARM to auto-close the moment it hits +{lock_target:.2f}%.",
                                        [("ARM", f"arm:{inst_id}:{token}")]
                                    )
                                    state["message_id"] = msg_id
                            elif status == "APPROACHING":
                                if unrealized_pct >= lock_target:
                                    send_telegram_message(
                                        f"ℹ️ {inst_name} hit +{unrealized_pct:.2f}% unrealized. I sent an alert earlier "
                                        f"that wasn't armed — this is just a confirmation, closing is on you from here."
                                    )
                                    state["status"] = "MISSED"
                                    state["token"] = None
                                elif unrealized_pct <= disarm_level:
                                    state["status"] = "IDLE"
                                    state["token"] = None
                            elif status == "ARMED":
                                if unrealized_pct >= lock_target:
                                    if auto_close_enabled:
                                        close_res = close_instance_positions((inst_id, inst_name, inst_path_by_id.get(inst_id)))
                                        send_telegram_message(
                                            f"✅ Closed {inst_name} — unrealized hit +{unrealized_pct:.2f}% as you confirmed. "
                                            f"Closed {close_res.get('closed', 0)} position(s)."
                                        )
                                    else:
                                        send_telegram_message(
                                            f"⚠️ {inst_name} hit +{unrealized_pct:.2f}% and was armed, but auto-close is "
                                            f"currently disabled. Please close manually."
                                        )
                                    state["status"] = "IDLE"
                                    state["token"] = None
                                elif unrealized_pct <= disarm_level:
                                    state["status"] = "IDLE"
                                    state["token"] = None
                            elif status == "MISSED":
                                if unrealized_pct < pre_alert_level:
                                    state["status"] = "IDLE"


                for inst in instances:
                    inst_id = inst[0]
                    inst_name = inst[1]
                    if inst_id not in online_ids:
                        connection_fail_count[inst_id] = connection_fail_count.get(inst_id, 0) + 1
                        if connection_fail_count[inst_id] == 240:
                            send_telegram_message(f"🔌 Connection Issue: {inst_name} has been offline for 2 minutes.")
                    else:
                        if connection_fail_count.get(inst_id, 0) >= 240:
                            send_telegram_message(f"✅ Connection Restored: {inst_name} is back online.")
                        connection_fail_count[inst_id] = 0
                        
                if last_summary_date and last_summary_date != current_date_str:
                    yesterday_date_str = last_summary_date
                    daily_report = build_risk_report("daily", risk_payload, c, yesterday_date_str, yesterday_date_str)
                    send_telegram_message(daily_report)

                    if datetime.utcnow().weekday() == 5:
                        # Saturday: report the trading week just finished (Monday -> yesterday/Friday)
                        today_dt = datetime.utcnow()
                        week_start_dt = today_dt - timedelta(days=5)
                        week_start_str = week_start_dt.strftime("%Y-%m-%d")
                        ts_from = int(datetime(week_start_dt.year, week_start_dt.month, week_start_dt.day, tzinfo=timezone.utc).timestamp())
                        ts_to = int(datetime(today_dt.year, today_dt.month, today_dt.day, tzinfo=timezone.utc).timestamp())
                        weekly_report = build_risk_report("weekly", risk_payload, c, week_start_str, yesterday_date_str, ts_from, ts_to)
                        send_telegram_message(weekly_report)

                    if datetime.utcnow().day == 1:
                        today_dt = datetime.utcnow()
                        this_month_start_dt = datetime(today_dt.year, today_dt.month, 1)
                        last_month_end_dt = this_month_start_dt - timedelta(days=1)
                        last_month_start_dt = last_month_end_dt.replace(day=1)
                        date_from = last_month_start_dt.strftime("%Y-%m-%d")
                        date_to = last_month_end_dt.strftime("%Y-%m-%d")
                        ts_from = int(last_month_start_dt.replace(tzinfo=timezone.utc).timestamp())
                        ts_to = int(this_month_start_dt.replace(tzinfo=timezone.utc).timestamp())
                        monthly_report = build_risk_report("monthly", risk_payload, c, date_from, date_to, ts_from, ts_to)
                        send_telegram_message(monthly_report)

                if last_summary_date != current_date_str:
                    last_summary_date = current_date_str

            conn.close()
        except Exception as e:
            logging.error(f"Poller thread error: {e}")
        time.sleep(0.5)

def reconcile_on_boot():
    init_db()
    logging.info("Running initialization flow on boot...")
    with mt5_lock:
        if not mt5.initialize():
            logging.error("MT5 init failed during boot.")
            return

# --- FLASK ROUTES ---


@flask_app.route('/api/internal_notify', methods=['POST'])
def internal_notify():
    msg = request.form.get('msg', 'Copier Trade Executed')
    
    def _notify():
        logging.info(msg)
        notify_clients("trade_sound", "play")
        send_telegram_message(msg)
        
    threading.Thread(target=_notify).start()
    return "ok"


@flask_app.route('/api/stream')
def stream():
    q = queue.Queue()
    clients.append(q)
    
    # Send initial state
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
        try:
            c.execute("SELECT trade_disable, disable_time_start, disable_time_end, auto_close_enabled FROM global_settings WHERE id = 1")
            row = c.fetchone()
            conn.close()
            if row:
                return jsonify({"trade_disable": bool(row[0]), "disable_time_start": row[1], "disable_time_end": row[2], "auto_close_enabled": bool(row[3]) if row[3] is not None else True})
            return jsonify({"trade_disable": False, "disable_time_start": "", "disable_time_end": "", "auto_close_enabled": True})
        except sqlite3.OperationalError:
            c.execute("SELECT trade_disable, disable_time_start, disable_time_end FROM global_settings WHERE id = 1")
            row = c.fetchone()
            conn.close()
            if row:
                return jsonify({"trade_disable": bool(row[0]), "disable_time_start": row[1], "disable_time_end": row[2], "auto_close_enabled": True})
            return jsonify({"trade_disable": False, "disable_time_start": "", "disable_time_end": "", "auto_close_enabled": True})
    else:
        data = request.json
        trade_disable = int(data.get('trade_disable', 0))
        disable_time_start = data.get('disable_time_start', '')
        disable_time_end = data.get('disable_time_end', '')
        c.execute("SELECT id, auto_close_enabled FROM global_settings WHERE id = 1")
        existing = c.fetchone()
        auto_close_enabled = int(data.get('auto_close_enabled', existing[1] if existing and existing[1] is not None else 1))
        if existing:
            c.execute("UPDATE global_settings SET trade_disable=?, disable_time_start=?, disable_time_end=?, auto_close_enabled=? WHERE id=1",
                      (trade_disable, disable_time_start, disable_time_end, auto_close_enabled))
        else:
            c.execute("INSERT INTO global_settings (id, trade_disable, disable_time_start, disable_time_end, auto_close_enabled) VALUES (1, ?, ?, ?, ?)",
                      (trade_disable, disable_time_start, disable_time_end, auto_close_enabled))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})

@flask_app.route('/api/instances', methods=['GET', 'POST', 'DELETE', 'PUT'])
def api_instances():
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    
    if request.method == 'GET':
        try:
            c.execute("SELECT id, name, path, risk_usd, symbol_mapping, auto_trade, accepted_timeframe, profit_limit, profit_limit_start_time, group_name, copier_role, copier_risk_type, copier_fixed_lot, copier_risk_usd, copier_risk_multiplier, alert_drawdown_limit, alert_daily_profit_target, account_type, alert_profit_lock_pct, alert_drawdown_levels FROM instances ORDER BY id ASC")
        except sqlite3.OperationalError:
            try:
                c.execute("SELECT id, name, path, risk_usd, symbol_mapping, auto_trade, accepted_timeframe, profit_limit, profit_limit_start_time, group_name FROM instances ORDER BY id ASC")
            except sqlite3.OperationalError:
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
                
            group_name = r[9] if len(r) > 9 else 'Ungrouped'
            copier_role = r[10] if len(r) > 10 else 'NONE'
            copier_risk_type = r[11] if len(r) > 11 else 'FIXED'
            copier_fixed_lot = r[12] if len(r) > 12 else 0.01
            copier_risk_usd = r[13] if len(r) > 13 else 100.0
            copier_risk_multiplier = r[14] if len(r) > 14 else 1.0
            
            instances.append({
                "id": inst_id, "name": r[1], "path": r[2], "risk_usd": r[3], 
                "symbol_mapping": r[4], "auto_trade": r[5], "accepted_timeframe": r[6] or 'all',
                "profit_limit": profit_limit or 0, "profit_limit_start_time": profit_limit_start_time or 0,
                "current_profit": current_profit,
                "group_name": group_name,
                "copier_role": copier_role,
                "copier_risk_type": copier_risk_type,
                "copier_fixed_lot": copier_fixed_lot,
                "copier_risk_usd": copier_risk_usd,
                "copier_risk_multiplier": copier_risk_multiplier,
                "alert_drawdown_limit": r[15] if len(r) > 15 else 2.0,
                "alert_daily_profit_target": r[16] if len(r) > 16 else 0.0,
                "account_type": r[17] if len(r) > 17 else 'PERSONAL',
                "alert_profit_lock_pct": r[18] if len(r) > 18 else 0.0,
                "alert_drawdown_levels": r[19] if len(r) > 19 and r[19] else '2,4,6,8,10'
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
        group_name = data.get('group_name', 'Ungrouped')
        alert_drawdown_limit = float(data.get('alert_drawdown_limit', 2.0))
        alert_daily_profit_target = float(data.get('alert_daily_profit_target', 0.0))
        account_type = data.get('account_type', 'PERSONAL')
        alert_profit_lock_pct = float(data.get('alert_profit_lock_pct', 0.0))
        alert_drawdown_levels = _format_drawdown_levels(_parse_drawdown_levels(data.get('alert_drawdown_levels', '2,4,6,8,10'))) or '2,4,6,8,10'
        import time
        profit_limit_start_time = int(time.time())

        if not name or not path:
            conn.close()
            return jsonify({"error": "Name and path required"}), 400

        try:
            c.execute("INSERT INTO instances (name, path, risk_usd, symbol_mapping, auto_trade, accepted_timeframe, profit_limit, profit_limit_start_time, group_name, alert_drawdown_limit, alert_daily_profit_target, account_type, alert_profit_lock_pct, alert_drawdown_levels) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (name, path, risk_usd, symbol_mapping, auto_trade, accepted_timeframe, profit_limit, profit_limit_start_time, group_name, alert_drawdown_limit, alert_daily_profit_target, account_type, alert_profit_lock_pct, alert_drawdown_levels))
        except sqlite3.OperationalError:
            try:
                c.execute("INSERT INTO instances (name, path, risk_usd, symbol_mapping, auto_trade, accepted_timeframe, profit_limit, profit_limit_start_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (name, path, risk_usd, symbol_mapping, auto_trade, accepted_timeframe, profit_limit, profit_limit_start_time))
            except sqlite3.OperationalError:
                c.execute("INSERT INTO instances (name, path, risk_usd, symbol_mapping, auto_trade, accepted_timeframe) VALUES (?, ?, ?, ?, ?, ?)", (name, path, risk_usd, symbol_mapping, auto_trade, accepted_timeframe))

        conn.commit()
        new_id = c.lastrowid
        conn.close()
        return jsonify({"id": new_id, "name": name, "path": path, "risk_usd": risk_usd, "symbol_mapping": symbol_mapping, "auto_trade": auto_trade, "accepted_timeframe": accepted_timeframe, "profit_limit": profit_limit, "account_type": account_type, "alert_drawdown_levels": alert_drawdown_levels}), 201
        
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
        group_name = data.get('group_name', 'Ungrouped')
        alert_drawdown_limit = float(data.get('alert_drawdown_limit', 2.0))
        alert_daily_profit_target = float(data.get('alert_daily_profit_target', 0.0))
        account_type = data.get('account_type', 'PERSONAL')
        alert_profit_lock_pct = float(data.get('alert_profit_lock_pct', 0.0))
        alert_drawdown_levels = _format_drawdown_levels(_parse_drawdown_levels(data.get('alert_drawdown_levels', '2,4,6,8,10'))) or '2,4,6,8,10'

        if not instance_id or not name or not path:
            conn.close()
            return jsonify({"error": "ID, name and path required"}), 400

        try:
            c.execute("UPDATE instances SET name=?, path=?, risk_usd=?, symbol_mapping=?, auto_trade=?, accepted_timeframe=?, profit_limit=?, group_name=?, alert_drawdown_limit=?, alert_daily_profit_target=?, account_type=?, alert_profit_lock_pct=?, alert_drawdown_levels=? WHERE id=?", (name, path, risk_usd, symbol_mapping, auto_trade, accepted_timeframe, profit_limit, group_name, alert_drawdown_limit, alert_daily_profit_target, account_type, alert_profit_lock_pct, alert_drawdown_levels, instance_id))
        except sqlite3.OperationalError:
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

@flask_app.route('/api/copier_instances', methods=['GET'])
def api_copier_instances():
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    try:
        c.execute("SELECT id, name, path, copier_role, copier_risk_type, copier_fixed_lot, copier_risk_usd, copier_risk_multiplier FROM instances ORDER BY id ASC")
        rows = c.fetchall()
    except sqlite3.OperationalError:
        rows = []
    
    instances = []
    for r in rows:
        instances.append({
            "id": r[0], "name": r[1], "path": r[2], 
            "copier_role": r[3], "copier_risk_type": r[4], 
            "copier_fixed_lot": r[5], "copier_risk_usd": r[6], "copier_risk_multiplier": r[7]
        })
    conn.close()
    return jsonify(instances)

@flask_app.route('/api/copier_instances/update', methods=['POST'])
def api_copier_instances_update():
    data = request.json
    instance_id = data.get('id')
    copier_role = data.get('copier_role', 'NONE')
    copier_risk_type = data.get('copier_risk_type', 'FIXED')
    copier_fixed_lot = float(data.get('copier_fixed_lot', 0.01))
    copier_risk_usd = float(data.get('copier_risk_usd', 100.0))
    copier_risk_multiplier = float(data.get('copier_risk_multiplier', 1.0))
    
    if not instance_id:
        return jsonify({"error": "ID required"}), 400
        
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    
    if copier_role == 'PROVIDER':
        c.execute("UPDATE instances SET copier_role = 'NONE' WHERE copier_role = 'PROVIDER'")
        
    try:
        c.execute("UPDATE instances SET copier_role=?, copier_risk_type=?, copier_fixed_lot=?, copier_risk_usd=?, copier_risk_multiplier=? WHERE id=?", 
                  (copier_role, copier_risk_type, copier_fixed_lot, copier_risk_usd, copier_risk_multiplier, instance_id))
        conn.commit()
    except sqlite3.OperationalError as e:
        conn.close()
        return jsonify({"error": str(e)}), 500
        
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

@flask_app.route('/api/tracker', methods=['GET'])
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
            t1_ticket = execute_trade(actual_symbol, action, sl, tp1, vol1, entry, inst_path, magic_number, "", "")
            t2_ticket = execute_trade(actual_symbol, action, sl, tp2, vol2, entry, inst_path, magic_number, "", "")
        else:
            t1_ticket = execute_trade(actual_symbol, action, sl, tp1, vol1, entry, inst_path, magic_number, "", "")
            
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
        t1_ticket = execute_trade(actual_symbol, action, sl, tp1, vol1, entry, inst_path, magic_number, "", "")
        t2_ticket = execute_trade(actual_symbol, action, sl, tp2, vol2, entry, inst_path, magic_number, "", "")
    else:
        t1_ticket = execute_trade(actual_symbol, action, sl, tp1, vol1, entry, inst_path, magic_number, "", "")
        
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
            
    new_rec_ticket = execute_trade(actual_symbol, rec_action, rec_sl, rec_tp, rec_volume, rec_entry, inst_path, magic_number, "", symbol_suffix)
    
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

def close_instance_positions(inst):
    inst_id, inst_name, inst_path = inst
    closed_count = 0
    try:
        with mt5_lock:
            if not mt5.initialize(path=inst_path):
                return {"name": inst_name, "closed": 0, "error": "MT5 not connected"}
                
            positions = mt5.positions_get()
            if positions:
                for p in positions:
                    tick = mt5.symbol_info_tick(p.symbol)
                    order_type = mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY
                    price = tick.bid if order_type == mt5.ORDER_TYPE_SELL else tick.ask
                    
                    req = {
                        "action": mt5.TRADE_ACTION_DEAL,
                        "symbol": p.symbol,
                        "volume": p.volume,
                        "type": order_type,
                        "position": p.ticket,
                        "price": price,
                        "deviation": 50,
                        "magic": p.magic,
                        "comment": "",
                        "type_time": mt5.ORDER_TIME_GTC,
                        "type_filling": mt5.ORDER_FILLING_IOC,
                    }
                    
                    # Check MT5 specific filling modes for compatibility if needed, but IOC is safest fallback.
                    res = mt5.order_send(req)
                    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                        closed_count += 1
                    else:
                        # Retry with FOK
                        req["type_filling"] = mt5.ORDER_FILLING_FOK
                        res = mt5.order_send(req)
                        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                            closed_count += 1
                            
            return {"name": inst_name, "closed": closed_count, "error": None}
    except Exception as e:
        return {"name": inst_name, "closed": closed_count, "error": str(e)}

@flask_app.route('/api/close_all', methods=['POST'])
def api_close_all():
    logging.info("User clicked GLOBAL CLOSE ALL.")
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    c.execute("SELECT id, name, path FROM instances")
    instances = c.fetchall()
    conn.close()
    
    if not instances:
        return jsonify({"status": "error", "message": "No instances to close"})
        
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)
    futures = [executor.submit(close_instance_positions, inst) for inst in instances]
    
    results = [f.result() for f in concurrent.futures.as_completed(futures)]
    total_closed = sum(r['closed'] for r in results)
    
    return jsonify({"status": "success", "message": f"Closed {total_closed} positions across {len(instances)} instances."})

@flask_app.route('/api/close_group', methods=['POST'])
def api_close_group():
    data = request.json
    group_name = data.get('group_name')
    if not group_name:
        return jsonify({"error": "Group name required"}), 400
        
    logging.info(f"User clicked CLOSE GROUP: {group_name}.")
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    c.execute("SELECT id, name, path FROM instances WHERE group_name = ?", (group_name,))
    instances = c.fetchall()
    conn.close()
    
    if not instances:
        return jsonify({"status": "error", "message": "No instances found in this group"})
        
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)
    futures = [executor.submit(close_instance_positions, inst) for inst in instances]
    
    results = [f.result() for f in concurrent.futures.as_completed(futures)]
    total_closed = sum(r['closed'] for r in results)
    
    return jsonify({"status": "success", "message": f"Closed {total_closed} positions in group {group_name}."})

def sync_trading_log():
    """Full resync of trading_log from each instance's MT5 deal history.
    Shared by the manual /api/sync_log route and the periodic background sync thread."""
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
        
        with mt5_lock:
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
    return total_synced


@flask_app.route('/api/sync_log', methods=['POST'])
def api_sync_log():
    total_synced = sync_trading_log()
    return jsonify({"status": "success", "synced": total_synced})


def trading_log_sync_thread():
    """Keeps trading_log fresh for the weekly/monthly Telegram report stats now
    that the old manual 'Sync Logs' UI button (Review page) is gone."""
    while True:
        try:
            sync_trading_log()
        except Exception as e:
            logging.error(f"Trading log sync thread error: {e}")
        time.sleep(900)

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

@flask_app.route('/api/review_dates', methods=['GET'])
def api_review_dates():
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    c.execute("SELECT DISTINCT date(datetime(COALESCE(local_time, time), 'unixepoch')) FROM trading_log ORDER BY date(datetime(COALESCE(local_time, time), 'unixepoch')) DESC")
    rows = c.fetchall()
    conn.close()
    
    dates = [r[0] for r in rows if r[0]]
    return jsonify({"dates": dates})


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

import zmq

def zmq_router_thread():
    context = zmq.Context()
    pull_socket = context.socket(zmq.PULL)
    pull_socket.bind("tcp://127.0.0.1:5555")
    
    pub_socket = context.socket(zmq.PUB)
    pub_socket.bind("tcp://127.0.0.1:5556")
    
    logging.info("[ZMQ ROUTER] Active and bridging Provider -> Consumers on 5555/5556")
    while True:
        try:
            msg = pull_socket.recv_json()
            logging.info(f"[ZMQ ROUTER] Routing Trade: {msg}")
            pub_socket.send_json(msg)
        except Exception as e:
            logging.error(f"ZMQ Router error: {e}")

def telegram_listener_thread():
    """Long-polls Telegram getUpdates for inline-keyboard button taps (the ARM
    button on profit-lock alerts). Long-polling (not a webhook) so this works
    behind the VPS's NAT with no public URL/HTTPS setup required."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id or chat_id == "YOUR_CHAT_ID_HERE":
        logging.warning("[TELEGRAM LISTENER] Telegram credentials not set, inbound listener not started.")
        return

    # A webhook (even one set accidentally by some other tool/run) silently
    # blocks getUpdates from ever receiving anything, so clear it on startup.
    telegram_delete_webhook()

    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    c.execute("SELECT telegram_last_update_id FROM global_settings WHERE id = 1")
    row = c.fetchone()
    last_update_id = row[0] if row and row[0] else 0
    conn.close()

    logging.info("[TELEGRAM LISTENER] Polling for inline button taps...")
    while True:
        try:
            updates = telegram_get_updates(offset=last_update_id + 1, timeout=30)
            for update in updates:
                last_update_id = update["update_id"]

                cq = update.get("callback_query")
                if not cq:
                    continue

                callback_id = cq.get("id")
                sender_chat_id = str(cq.get("message", {}).get("chat", {}).get("id", ""))
                if sender_chat_id != str(chat_id):
                    logging.warning(f"[TELEGRAM LISTENER] Ignoring callback from unauthorized chat {sender_chat_id}")
                    continue

                message_id = cq.get("message", {}).get("message_id")
                parts = (cq.get("data") or "").split(":")

                if len(parts) == 3 and parts[0] == "arm":
                    try:
                        inst_id = int(parts[1])
                    except ValueError:
                        telegram_answer_callback(callback_id, "Invalid request")
                        continue
                    token = parts[2]

                    with profit_lock_lock:
                        state = profit_lock_state.get(inst_id)
                        armed_ok = bool(state and state.get("status") == "APPROACHING" and state.get("token") == token)
                        if armed_ok:
                            state["status"] = "ARMED"
                            state["token"] = None

                    if armed_ok:
                        telegram_answer_callback(callback_id, "Armed")
                        telegram_edit_message(message_id, "🔒 Armed — will auto-close the moment the target is hit.")
                    else:
                        telegram_answer_callback(callback_id, "This alert has expired or was already handled.")
                else:
                    telegram_answer_callback(callback_id, "Unknown action")

            if updates:
                conn = sqlite3.connect('trades.db')
                c = conn.cursor()
                c.execute("UPDATE global_settings SET telegram_last_update_id = ? WHERE id = 1", (last_update_id,))
                conn.commit()
                conn.close()
        except Exception as e:
            logging.error(f"Telegram listener error: {e}")
            time.sleep(2)

copier_workers = {}

def copier_manager_thread():
    import sys
    while True:
        try:
            conn = sqlite3.connect('trades.db')
            c = conn.cursor()
            try:
                c.execute("SELECT id, path, copier_role, copier_risk_type, copier_fixed_lot, copier_risk_usd, copier_risk_multiplier, symbol_mapping, account_type FROM instances WHERE copier_role IN ('PROVIDER', 'CONSUMER')")
                active_copiers = c.fetchall()
            except sqlite3.OperationalError:
                active_copiers = []
            conn.close()
            
            desired = {r[0]: r for r in active_copiers}
            
            to_remove = []
            for cid, w in copier_workers.items():
                if cid not in desired or w['config'] != desired[cid] or w['process'].poll() is not None:
                    try:
                        w['process'].terminate()
                    except: pass
                    to_remove.append(cid)
            
            for cid in to_remove:
                del copier_workers[cid]
                
            for cid, r in desired.items():
                if cid not in copier_workers:
                    cmd = [
                        sys.executable, 'mt5_worker.py',
                        '--id', str(r[0]),
                        '--path', str(r[1]),
                        '--role', str(r[2]),
                        '--risk_type', str(r[3]),
                        '--fixed_lot', str(r[4]),
                        '--risk_usd', str(r[5]),
                        '--risk_mult', str(r[6]),
                        '--symbol_mapping', str(r[7] if len(r) > 7 and r[7] else '{}'),
                        '--account_type', str(r[8] if len(r) > 8 and r[8] else 'PERSONAL')
                    ]
                    p = subprocess.Popen(cmd)
                    copier_workers[cid] = {'process': p, 'config': r}
                    logging.info(f"Started MT5 Copier Worker [{r[2]}] for Instance {cid}")
                    
        except Exception as e:
            logging.error(f"Copier manager error: {e}")

        time.sleep(3)

# --- NEWS BLACKOUT (PROP FIRM) ---

_news_state = {"last_success_date": None, "failure_alerted_date": None}

def _format_news_summary(windows, date_str):
    lines = [f"✅ News Calendar Fetched — {len(windows)} high-impact events today ({date_str}):"]
    if not windows:
        lines.append("(none)")
    for w in sorted(windows, key=lambda x: x['event_time']):
        local_time = datetime.fromtimestamp(w['event_time']).strftime('%H:%M')
        lines.append(f"- {local_time} {w['currency']} {w['title']}")
    return "\n".join(lines)

def _attempt_news_fetch():
    """Returns (ok, windows). Up to 3 attempts with short backoff."""
    for attempt in range(3):
        try:
            raw = news_calendar.fetch_raw_calendar()
            high_impact = news_calendar.filter_high_impact(raw)
            today_events = news_calendar.filter_today(high_impact)
            return True, news_calendar.events_to_windows(today_events)
        except Exception as e:
            logging.error(f"News calendar fetch attempt {attempt + 1} failed: {e}")
            if attempt < 2:
                time.sleep(5 if attempt == 0 else 15)
    return False, []

def news_calendar_thread():
    while True:
        try:
            today_str = datetime.utcnow().strftime("%Y-%m-%d")
            if _news_state["last_success_date"] != today_str:
                ok, windows = _attempt_news_fetch()
                if ok:
                    news_calendar.save_windows_file({
                        "status": "AUTO", "date": today_str,
                        "fetched_at": int(time.time()), "events": windows
                    })
                    _news_state["last_success_date"] = today_str
                    logging.info(f"[NEWS] Fetched {len(windows)} high-impact events for {today_str}")
                    send_telegram_message(_format_news_summary(windows, today_str))
                else:
                    news_calendar.save_windows_file({
                        "status": "FAILED", "date": today_str,
                        "fetched_at": int(time.time()), "events": []
                    })
                    logging.error("[NEWS] Failed to fetch news calendar after retries; PropFirm instances fail-closed.")
                    if _news_state["failure_alerted_date"] != today_str:
                        send_telegram_message(
                            "❌ Failed to fetch the news calendar (3 attempts). PropFirm instances are "
                            "BLOCKED from ALL trade copying (open/modify/close) until this is fixed. "
                            "Please send me today's high-impact news list (title, currency, time + "
                            "timezone) so I can enter it manually in the News panel."
                        )
                        _news_state["failure_alerted_date"] = today_str
        except Exception as e:
            logging.error(f"News calendar thread error: {e}")
        time.sleep(60)

@flask_app.route('/api/news/today', methods=['GET'])
def api_news_today():
    return jsonify(news_calendar.load_windows_file())

@flask_app.route('/api/news/manual', methods=['POST'])
def api_news_manual():
    data = request.json or {}
    entries = data.get('events', [])
    if not entries:
        return jsonify({"error": "No events provided"}), 400
    windows = news_calendar.manual_events_to_windows(entries)
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    payload = {"status": "MANUAL", "date": today_str, "fetched_at": int(time.time()), "events": windows}
    news_calendar.save_windows_file(payload)
    _news_state["last_success_date"] = today_str
    return jsonify(payload)

@flask_app.route('/api/news/blocked_actions', methods=['GET', 'POST'])
def api_news_blocked_actions():
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()

    if request.method == 'GET':
        status = request.args.get('status', 'PENDING')
        c.execute("SELECT id, instance_id, instance_name, action_type, ticket, symbol, volume, sl, tp, reason, blocked_at, status FROM blocked_copier_actions WHERE status = ? ORDER BY blocked_at DESC", (status,))
        rows = c.fetchall()
        conn.close()
        actions = [{
            "id": r[0], "instance_id": r[1], "instance_name": r[2], "action_type": r[3],
            "ticket": r[4], "symbol": r[5], "volume": r[6], "sl": r[7], "tp": r[8],
            "reason": r[9], "blocked_at": r[10], "status": r[11]
        } for r in rows]
        return jsonify(actions)

    data = request.json or {}
    action_type = data.get('action_type')
    ticket = data.get('ticket')
    if not action_type or not ticket:
        conn.close()
        return jsonify({"error": "action_type and ticket required"}), 400
    c.execute(
        "INSERT INTO blocked_copier_actions (instance_id, instance_name, action_type, ticket, symbol, volume, sl, tp, reason, blocked_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')",
        (data.get('instance_id'), data.get('instance_name', ''), action_type, ticket, data.get('symbol', ''),
         data.get('volume'), data.get('sl'), data.get('tp'), data.get('reason', ''), int(time.time()))
    )
    conn.commit()
    new_id = c.lastrowid
    conn.close()
    notify_clients("tracker_update", "update")
    return jsonify({"id": new_id, "status": "PENDING"}), 201

def _close_position_by_ticket(inst_path, ticket, volume):
    """Single-ticket variant of close_instance_positions' order-send pattern."""
    with mt5_lock:
        if not mt5.initialize(path=inst_path):
            return False, "MT5 not connected"
        pos = mt5.positions_get(ticket=ticket)
        if not pos:
            return False, "Position not found"
        p = pos[0]
        tick = mt5.symbol_info_tick(p.symbol)
        if not tick:
            return False, "No tick data"
        order_type = mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY
        price = tick.bid if order_type == mt5.ORDER_TYPE_SELL else tick.ask
        req = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol, "volume": volume or p.volume,
            "type": order_type, "position": ticket, "price": price, "deviation": 50,
            "magic": p.magic, "comment": "", "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        res = mt5.order_send(req)
        if not res or res.retcode != mt5.TRADE_RETCODE_DONE:
            req["type_filling"] = mt5.ORDER_FILLING_FOK
            res = mt5.order_send(req)
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            return True, None
        return False, f"retcode={res.retcode if res else 'None'}"

def _modify_position_by_ticket(inst_path, ticket, sl, tp):
    with mt5_lock:
        if not mt5.initialize(path=inst_path):
            return False, "MT5 not connected"
        pos = mt5.positions_get(ticket=ticket)
        if not pos:
            return False, "Position not found"
        p = pos[0]
        req = {
            "action": mt5.TRADE_ACTION_SLTP, "symbol": p.symbol, "position": ticket,
            "sl": float(sl) if sl is not None else p.sl, "tp": float(tp) if tp is not None else p.tp
        }
        res = mt5.order_send(req)
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            return True, None
        return False, f"retcode={res.retcode if res else 'None'}"

@flask_app.route('/api/news/blocked_actions/<int:action_id>/execute', methods=['POST'])
def api_news_blocked_action_execute(action_id):
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    c.execute("SELECT instance_id, action_type, ticket, volume, sl, tp, status FROM blocked_copier_actions WHERE id = ?", (action_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Not found"}), 404

    instance_id, action_type, ticket, volume, sl, tp, status = row
    if status != 'PENDING':
        conn.close()
        return jsonify({"error": f"Action already {status}"}), 400

    c.execute("SELECT path FROM instances WHERE id = ?", (instance_id,))
    inst_row = c.fetchone()
    if not inst_row:
        conn.close()
        return jsonify({"error": "Instance not found"}), 404
    inst_path = inst_row[0]

    if action_type == 'CLOSE':
        ok, err = _close_position_by_ticket(inst_path, ticket, volume)
    elif action_type == 'MODIFY':
        ok, err = _modify_position_by_ticket(inst_path, ticket, sl, tp)
    else:
        conn.close()
        return jsonify({"error": f"Unknown action_type {action_type}"}), 400

    if not ok:
        conn.close()
        return jsonify({"error": err}), 500

    c.execute("UPDATE blocked_copier_actions SET status='EXECUTED', resolved_at=? WHERE id=?", (int(time.time()), action_id))
    conn.commit()
    conn.close()
    notify_clients("tracker_update", "update")
    return jsonify({"status": "EXECUTED"})

@flask_app.route('/api/news/blocked_actions/<int:action_id>/dismiss', methods=['POST'])
def api_news_blocked_action_dismiss(action_id):
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    c.execute("UPDATE blocked_copier_actions SET status='DISMISSED', resolved_at=? WHERE id=? AND status='PENDING'", (int(time.time()), action_id))
    changed = c.rowcount
    conn.commit()
    conn.close()
    if changed == 0:
        return jsonify({"error": "Not found or already resolved"}), 404
    notify_clients("tracker_update", "update")
    return jsonify({"status": "DISMISSED"})

@flask_app.route('/', defaults={'path': ''})
@flask_app.route('/<path:path>')
def serve_react(path):
    if path.startswith('api/'):
        return "Not found", 404
        
    full_path = os.path.join(flask_app.static_folder, path)
    if path != "" and os.path.exists(full_path):
        return send_from_directory(flask_app.static_folder, path)
        
    try:
        return render_template('index.html')
    except Exception as e:
        return f"Please run 'npm run build' inside the frontend directory. Error: {e}", 500

def main():
    logging.info("Starting Premium MT5 Bridge Server...")
    
    # DB Reconcile and Poller
    reconcile_on_boot()
    threading.Thread(target=poller_thread, daemon=True).start()
    threading.Thread(target=zmq_router_thread, daemon=True).start()
    threading.Thread(target=copier_manager_thread, daemon=True).start()
    threading.Thread(target=news_calendar_thread, daemon=True).start()
    threading.Thread(target=telegram_listener_thread, daemon=True).start()
    threading.Thread(target=trading_log_sync_thread, daemon=True).start()
    
    # Setup Ngrok
    
    send_telegram_message("✅ MT5 Bridge Server Started & Web UI Ready!")
    
    # Auto-open browser
    threading.Thread(target=lambda: (time.sleep(1), webbrowser.open("http://127.0.0.1:5000")), daemon=True).start()

    # Run Flask with SocketIO
    socketio.run(flask_app, host='0.0.0.0', port=5000, use_reloader=False, allow_unsafe_werkzeug=True)

if __name__ == "__main__":
    main()
