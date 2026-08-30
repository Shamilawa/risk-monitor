import threading
import queue
import logging
import math
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

# Static is scoped to the hashed Vite bundles under dist/assets, NOT to dist itself. With
# static_url_path='/' Flask registers a '/<path:filename>' rule that outranks serve_react's
# catch-all, so any client-side route (/portfolio, /portfolio/1, /copier) 404s the moment
# it is loaded directly or refreshed -- only in-app navigation hid it. Everything outside
# /assets now falls through to serve_react, which serves real files if they exist and
# index.html otherwise, which is what SPA routing needs.
flask_app = Flask(
    __name__,
    static_folder=os.path.join(frontend_dist, 'assets'),
    static_url_path='/assets',
    template_folder=frontend_dist,
)
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
    # alert_profit_ceiling_usd replaces the old alert_daily_profit_target column, which was read
    # every poll but never actually evaluated anywhere -- RENAME keeps it in the same tuple
    # position on existing DBs (the positional SELECT tuples below depend on that), ADD COLUMN
    # covers fresh DBs where the old column never existed.
    try:
        c.execute("ALTER TABLE instances RENAME COLUMN alert_daily_profit_target TO alert_profit_ceiling_usd")
    except sqlite3.OperationalError:
        try:
            c.execute("ALTER TABLE instances ADD COLUMN alert_profit_ceiling_usd REAL DEFAULT 0.0")
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

    try:
        c.execute("ALTER TABLE instances ADD COLUMN news_block_before_min REAL DEFAULT 2.0")
    except sqlite3.OperationalError: pass
    try:
        c.execute("ALTER TABLE instances ADD COLUMN news_block_after_min REAL DEFAULT 2.0")
    except sqlite3.OperationalError: pass

    # trade_locked: set by the profit-ceiling auto-close once it books profit on an instance, to
    # stop it opening any further trades until manually unlocked (POST /api/instances/<id>/unlock).
    try:
        c.execute("ALTER TABLE instances ADD COLUMN trade_locked INTEGER DEFAULT 0")
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

    # sl_at_open/entry_risk_usd let weekly/daily reports derive "trades without SL"
    # and "max risk exposed" from complete broker history instead of live polling
    # snapshots, which silently miss any trade that isn't caught mid-open by a poll.
    try:
        c.execute("ALTER TABLE trading_log ADD COLUMN sl_at_open REAL DEFAULT 0")
    except Exception: pass
    try:
        c.execute("ALTER TABLE trading_log ADD COLUMN entry_risk_usd REAL DEFAULT 0")
    except Exception: pass

    # --- Journal columns -------------------------------------------------------------
    # position_id is the journal's real identity for a trade. A scale-out closes in several
    # OUT deals; the old sync inserted one row per OUT deal and gave each row the *whole*
    # position's summed P&L, multiplying that trade's profit by its number of partial exits.
    # One row per position, keyed on position_id, is what fixes it -- see sync_trading_log().
    # direction comes from the ENTRY deal: the closing deal's `type` is inverted relative to
    # the position (a long closes with a SELL deal), so `type` alone can't be read directly.
    for ddl in (
        "ALTER TABLE trading_log ADD COLUMN position_id INTEGER",
        "ALTER TABLE trading_log ADD COLUMN direction INTEGER",       # 0 = LONG, 1 = SHORT
        "ALTER TABLE trading_log ADD COLUMN entry_price REAL DEFAULT 0",
        "ALTER TABLE trading_log ADD COLUMN exit_price REAL DEFAULT 0",
        "ALTER TABLE trading_log ADD COLUMN tp_at_open REAL DEFAULT 0",
        # MAE/MFE are the worst and best floating P&L the position ever showed, in account
        # currency. NULL means "not backfilled yet" and must stay distinguishable from 0.0,
        # which is a legitimate value for a trade that never went against you.
        "ALTER TABLE trading_log ADD COLUMN mae_usd REAL",
        "ALTER TABLE trading_log ADD COLUMN mfe_usd REAL",
    ):
        try:
            c.execute(ddl)
        except sqlite3.OperationalError: pass

    c.execute("CREATE INDEX IF NOT EXISTS idx_trading_log_position ON trading_log (instance_id, position_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_trading_log_close ON trading_log (instance_id, local_time)")

    # Journal annotations live in their own table keyed on (instance_id, position_id) because
    # sync_trading_log() may delete and rebuild trading_log rows at any time -- trading_log.id
    # is not stable across a resync, so nothing user-authored may ever be keyed to it.
    c.execute('''
        CREATE TABLE IF NOT EXISTS trade_annotations (
            instance_id INTEGER,
            position_id INTEGER,
            tags        TEXT DEFAULT '',
            grade       TEXT DEFAULT '',
            note        TEXT DEFAULT '',
            updated_at  INTEGER,
            PRIMARY KEY (instance_id, position_id)
        )
    ''')

    # Deposits, withdrawals, credits and corrections -- every balance change that is NOT a
    # trade. Without these a $5,000 deposit looks like a 40% daily return and every
    # risk-adjusted ratio built on top of it is garbage, so they are captured and then
    # subtracted out of the return series.
    c.execute('''
        CREATE TABLE IF NOT EXISTS balance_operations (
            instance_id INTEGER,
            ticket      INTEGER,
            time        INTEGER,
            local_time  INTEGER,
            deal_type   INTEGER,
            amount      REAL,
            comment     TEXT,
            PRIMARY KEY (instance_id, ticket)
        )
    ''')
    c.execute("CREATE INDEX IF NOT EXISTS idx_balance_ops_time ON balance_operations (instance_id, local_time)")

    # Per-instance incremental-sync bookmark. schema_version forces exactly one full rebuild
    # when an existing DB first runs the position-aggregated sync, so pre-existing rows (which
    # have no position_id and may be multi-counted) are replaced rather than merged into.
    c.execute('''
        CREATE TABLE IF NOT EXISTS trading_log_sync_state (
            instance_id     INTEGER PRIMARY KEY,
            last_deal_time  INTEGER DEFAULT 0,
            schema_version  INTEGER DEFAULT 0,
            last_sync_at    INTEGER DEFAULT 0
        )
    ''')

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

    # "What counts as a trading day" has exactly one definition everywhere (daily P&L,
    # calendar, hour/weekday breakdowns, review dates, risk snapshots). See
    # _journal_day_config(). MACHINE = this computer's local timezone, which is also the
    # frame the frontend renders in, so the two agree by construction.
    try:
        c.execute("ALTER TABLE global_settings ADD COLUMN journal_day_anchor TEXT DEFAULT 'MACHINE'")
    except sqlite3.OperationalError: pass
    # Only consulted when journal_day_anchor = 'FIXED'.
    try:
        c.execute("ALTER TABLE global_settings ADD COLUMN journal_day_offset_min INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass
    # ADD COLUMN backfills existing rows with NULL rather than the DEFAULT, so pin the
    # single settings row explicitly.
    c.execute("UPDATE global_settings SET journal_day_anchor = 'MACHINE' WHERE journal_day_anchor IS NULL")

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

    # Cloud sync status, surfaced on the Settings "Cloud Sync" panel -- covers both the
    # daily Task Scheduler run and the manual "Sync Now" button, which share cloud_sync.py's
    # sync_to_cloud() and both write these same three columns.
    try:
        c.execute("ALTER TABLE global_settings ADD COLUMN last_cloud_sync_at INTEGER")
    except sqlite3.OperationalError: pass
    try:
        c.execute("ALTER TABLE global_settings ADD COLUMN last_cloud_sync_status TEXT")
    except sqlite3.OperationalError: pass
    try:
        c.execute("ALTER TABLE global_settings ADD COLUMN last_cloud_sync_message TEXT")
    except sqlite3.OperationalError: pass

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
    alert_profit_ceiling_usd = inst[11] if len(inst) > 11 else 0.0
    account_type = inst[12] if len(inst) > 12 else 'PERSONAL'
    alert_profit_lock_pct = inst[13] if len(inst) > 13 else 0.0
    alert_drawdown_levels = inst[14] if len(inst) > 14 else '2,4,6,8,10'
    trade_locked = bool(inst[15]) if len(inst) > 15 and inst[15] is not None else False

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
                "alert_profit_ceiling_usd": alert_profit_ceiling_usd,
                "account_type": account_type,
                "alert_profit_lock_pct": alert_profit_lock_pct,
                "alert_drawdown_levels": alert_drawdown_levels,
                "trade_locked": trade_locked,
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


def _journal_day_config(c):
    """How the app decides which calendar day a trade belongs to.

    There is exactly one definition of "a trading day", and this is it -- daily P&L, review
    dates, risk snapshots and (later) the calendar and hour/weekday breakdowns all bucket
    through _journal_date_str(), so they can never disagree about where a day starts.

      MACHINE (default) -- this computer's local timezone. Also exactly what the frontend
                           gets from `new Date(ts * 1000)`, so backend and UI agree by
                           construction, including across DST changes.
      UTC               -- days pinned to UTC.
      FIXED             -- UTC shifted by journal_day_offset_min, for pinning days to a
                           broker's server day when it differs from both of the above.

    A fixed offset cannot express MACHINE correctly: it would be an hour out for half the
    year anywhere that observes DST, which is why this is a mode rather than a number.
    """
    anchor, offset_min = 'MACHINE', 0
    try:
        c.execute("SELECT journal_day_anchor, journal_day_offset_min FROM global_settings WHERE id = 1")
        row = c.fetchone()
        if row:
            anchor = (row[0] or 'MACHINE').upper()
            offset_min = int(row[1] or 0)
    except (sqlite3.OperationalError, TypeError, ValueError):
        pass
    if anchor not in ('MACHINE', 'UTC', 'FIXED'):
        anchor = 'MACHINE'
    return {"anchor": anchor, "offset_min": offset_min}


def _journal_date_str(ts, cfg):
    """Calendar date ('YYYY-MM-DD') that a UTC timestamp belongs to, in journal-day terms."""
    ts = int(ts)
    if cfg["anchor"] == 'MACHINE':
        # fromtimestamp() applies this machine's rules *as they were at that instant*, so a
        # trade from last winter keeps the offset that was actually in force then.
        return datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
    shift = cfg["offset_min"] * 60 if cfg["anchor"] == 'FIXED' else 0
    return datetime.utcfromtimestamp(ts + shift).strftime('%Y-%m-%d')


def _journal_now(cfg):
    """'Now' as a naive datetime in the journal's day frame, for walking day lists."""
    if cfg["anchor"] == 'MACHINE':
        return datetime.now()
    shift = timedelta(minutes=cfg["offset_min"]) if cfg["anchor"] == 'FIXED' else timedelta(0)
    return datetime.now(timezone.utc).replace(tzinfo=None) + shift


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


def _query_trade_stats(c, inst_id, ts_from, ts_to, current_balance=None):
    """current_balance (optional): the instance's live balance *right now*, used to anchor a
    realized high-water-mark drawdown reconstructed from closed trades. This -- along with
    no_sl_count/max_entry_risk_usd below -- is sourced entirely from trading_log (complete
    broker history, refreshed by sync_trading_log() regardless of app uptime), unlike the
    risk_snapshots-based figures in _query_risk_range which only reflect what the live poller
    happened to sample."""
    c.execute(
        "SELECT profit, sl_at_open, entry_risk_usd FROM trading_log WHERE instance_id = ? AND COALESCE(local_time, time) >= ? AND COALESCE(local_time, time) < ? ORDER BY COALESCE(local_time, time) ASC",
        (inst_id, ts_from, ts_to)
    )
    rows = c.fetchall()
    profits = [row[0] for row in rows if row[0] is not None]
    total = len(profits)
    wins = sum(1 for p in profits if p > 0)
    win_rate = (wins / total * 100.0) if total else None
    largest_loss = min(profits) if profits else 0.0
    best_trade = max(profits) if profits else 0.0
    total_realized = sum(profits)

    gross_profit = sum(p for p in profits if p > 0)
    gross_loss = sum(p for p in profits if p < 0)
    if gross_loss < 0:
        profit_factor = gross_profit / abs(gross_loss)
    else:
        # No losing trades at all -- the ratio is genuinely undefined (division by zero),
        # not "99.9". Return None so the UI renders n/a instead of a fabricated number that
        # reads like a real, very good result.
        profit_factor = None

    max_streak = 0
    cur_streak = 0
    for p in profits:
        if p < 0:
            cur_streak += 1
            max_streak = max(max_streak, cur_streak)
        else:
            cur_streak = 0

    no_sl_count = sum(1 for row in rows if row[0] is not None and not row[1])
    max_entry_risk_usd = max((row[2] or 0.0 for row in rows), default=0.0)

    # Realized equity high-water-mark drawdown: walk the period's closed-trade P&L in order,
    # anchored so the running balance ends at current_balance at ts_to. This is the balance-based
    # analogue of "peak drawdown" and is available even if the poller never sampled a single
    # floating-loss moment -- it only needs closed trades, which trading_log always has.
    realized_dd_pct = 0.0
    if current_balance is not None and profits:
        c.execute(
            "SELECT COALESCE(SUM(profit), 0) FROM trading_log WHERE instance_id = ? AND COALESCE(local_time, time) >= ?",
            (inst_id, ts_to)
        )
        profit_after_period = c.fetchone()[0] or 0.0
        balance_at_period_start = current_balance - profit_after_period - total_realized
        running = balance_at_period_start
        peak = running
        for p in profits:
            running += p
            peak = max(peak, running)
            if peak > 0:
                realized_dd_pct = max(realized_dd_pct, (peak - running) / peak * 100)

    return {
        "total_trades": total, "win_rate": win_rate, "largest_loss": largest_loss,
        "max_loss_streak": max_streak, "total_realized": total_realized,
        "best_trade": best_trade, "profit_factor": profit_factor,
        "gross_profit": gross_profit, "gross_loss": gross_loss,
        "no_sl_count": no_sl_count, "max_entry_risk_usd": max_entry_risk_usd,
        "realized_dd_pct": realized_dd_pct,
    }


def _query_daily_pnl(c, inst_id, days):
    """Ascending list of {date, label, profit} for the trailing `days` window,
    one entry per calendar day (0.0 where no trades closed). DB-only (reads
    trading_log, kept fresh by trading_log_sync_thread) — no live MT5 call,
    so this is safe to call from a request handler without touching mt5_lock."""
    # int(time.time()), not datetime.utcnow().timestamp(): .timestamp() reads a *naive*
    # datetime as local time, so on a UTC+5:30 machine utcnow().timestamp() lands 19800s in
    # the past -- which silently dropped every trade closed in the last 5h30m from this
    # window. The epochs stored in trading_log are true UTC, so compare against true UTC.
    ts_to = int(time.time())
    ts_from = ts_to - days * 86400

    # Read the day config *before* the trade query: _journal_day_config() runs its own
    # SELECT on this same cursor, which would discard the pending trade rows and leave
    # every day reading 0.00.
    cfg = _journal_day_config(c)
    c.execute(
        "SELECT COALESCE(local_time, time) as t, profit FROM trading_log WHERE instance_id = ? AND COALESCE(local_time, time) >= ? AND COALESCE(local_time, time) < ?",
        (inst_id, ts_from, ts_to)
    )
    daily_totals = {}
    for t, profit in c.fetchall():
        if t is None or profit is None:
            continue
        date_str = _journal_date_str(t, cfg)
        daily_totals[date_str] = daily_totals.get(date_str, 0.0) + profit

    # The day list is walked back from "now" in the same frame the buckets use, so labels
    # line up with totals instead of being a day out near midnight.
    day_cursor = _journal_now(cfg)
    out = []
    for i in range(days, -1, -1):
        d = day_cursor - timedelta(days=i)
        date_str = d.strftime('%Y-%m-%d')
        out.append({"date": date_str, "label": d.strftime('%m/%d'), "profit": round(daily_totals.get(date_str, 0.0), 2)})
    return out


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

        # risk_snapshots (risk, above) only reflects moments the live poller actually sampled an
        # open position -- it silently under-reports (often to zero) if the app wasn't running, or
        # a trade opened and closed between polls. stats, below, is reconstructed from complete
        # broker deal/order history via trading_log, so it can't miss a closed trade. We take the
        # max of the two for drawdown/risk-exposed (either source can see something the other
        # can't -- e.g. a floating spike that recovered before close is poller-only) and prefer the
        # historical count outright for no-SL trades, since it's a strict superset of what polling
        # can ever catch.
        peak_dd = risk["peak_drawdown_pct"]
        max_risk = risk["max_risk_usd"]
        no_sl = risk["no_sl_count"]
        stats = None
        if ts_from is not None:
            stats = _query_trade_stats(c, inst_id, ts_from, ts_to, current_balance=r.get("balance"))
            peak_dd = max(peak_dd, stats["realized_dd_pct"])
            max_risk = max(max_risk, stats["max_entry_risk_usd"])
            no_sl = stats["no_sl_count"]

        breach_flag = " ⚠️ breached limit" if dd_limit > 0 and peak_dd >= dd_limit else ""

        lines.append(f"\n{inst_name}")
        lines.append(f"  Peak drawdown: {peak_dd:.2f}% (limit {dd_limit:.1f}%){breach_flag}")
        lines.append(f"  Max risk exposed: ${max_risk:.2f}")
        lines.append(f"  Trades without SL: {no_sl}")

        if period in ("weekly", "monthly") and stats is not None and stats["total_trades"] > 0:
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
                c.execute("SELECT id, name, path, symbol_suffix, group_name, copier_role, copier_risk_type, copier_fixed_lot, copier_risk_usd, copier_risk_multiplier, alert_drawdown_limit, alert_profit_ceiling_usd, account_type, alert_profit_lock_pct, alert_drawdown_levels, trade_locked FROM instances")
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

                    # --- Profit ceiling: close outright once total equity (realized + unrealized)
                    # reaches a fixed $ level, no arm/confirm step, then LOCK the instance so it
                    # can't open further trades. The copier worker refuses new copied trades on a
                    # locked instance (see copier_manager_thread/mt5_worker.py); the kill-switch
                    # below catches anything opened another way (manual, an EA) by closing it again.
                    # Stays locked until POST /api/instances/<id>/unlock.
                    ceiling = r.get("alert_profit_ceiling_usd", 0.0)
                    trade_locked = r.get("trade_locked", False)
                    equity = r.get("equity", 0.0)

                    if trade_locked:
                        if current_tickets:
                            close_res = close_instance_positions((inst_id, inst_name, inst_path_by_id.get(inst_id)))
                            if close_res.get("closed", 0) > 0:
                                send_telegram_message(
                                    f"🔒 {inst_name} is locked (profit ceiling reached) but had "
                                    f"{close_res.get('closed', 0)} new position(s) open — closed them again. "
                                    f"Unlock the instance from the Copier page to allow trading."
                                )
                    elif ceiling > 0 and equity >= ceiling:
                        if auto_close_enabled:
                            close_res = close_instance_positions((inst_id, inst_name, inst_path_by_id.get(inst_id)))
                            c.execute("UPDATE instances SET trade_locked = 1 WHERE id = ?", (inst_id,))
                            send_telegram_message(
                                f"🔒 {inst_name} equity hit ${equity:.2f} (ceiling ${ceiling:.2f}) — closed "
                                f"{close_res.get('closed', 0)} position(s) and LOCKED the instance from further "
                                f"trading. Unlock it from the Copier page when you're ready."
                            )
                        else:
                            send_telegram_message(
                                f"⚠️ {inst_name} equity hit ${equity:.2f} (ceiling ${ceiling:.2f}), but auto-close "
                                f"is currently disabled so it wasn't closed or locked. Please close manually."
                            )

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
                    yesterday_ts_from = int(datetime.strptime(yesterday_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
                    yesterday_ts_to = yesterday_ts_from + 86400
                    daily_report = build_risk_report("daily", risk_payload, c, yesterday_date_str, yesterday_date_str, yesterday_ts_from, yesterday_ts_to)
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
            c.execute("SELECT id, name, path, risk_usd, symbol_mapping, auto_trade, accepted_timeframe, profit_limit, profit_limit_start_time, group_name, copier_role, copier_risk_type, copier_fixed_lot, copier_risk_usd, copier_risk_multiplier, alert_drawdown_limit, alert_profit_ceiling_usd, account_type, alert_profit_lock_pct, alert_drawdown_levels, news_block_before_min, news_block_after_min, trade_locked FROM instances ORDER BY id ASC")
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
                "alert_profit_ceiling_usd": r[16] if len(r) > 16 else 0.0,
                "account_type": r[17] if len(r) > 17 else 'PERSONAL',
                "alert_profit_lock_pct": r[18] if len(r) > 18 else 0.0,
                "alert_drawdown_levels": r[19] if len(r) > 19 and r[19] else '2,4,6,8,10',
                "news_block_before_min": r[20] if len(r) > 20 and r[20] is not None else 2.0,
                "news_block_after_min": r[21] if len(r) > 21 and r[21] is not None else 2.0,
                "trade_locked": bool(r[22]) if len(r) > 22 and r[22] else False
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
        alert_profit_ceiling_usd = float(data.get('alert_profit_ceiling_usd', 0.0))
        account_type = data.get('account_type', 'PERSONAL')
        alert_profit_lock_pct = float(data.get('alert_profit_lock_pct', 0.0))
        alert_drawdown_levels = _format_drawdown_levels(_parse_drawdown_levels(data.get('alert_drawdown_levels', '2,4,6,8,10'))) or '2,4,6,8,10'
        news_block_before_min = float(data.get('news_block_before_min', 2.0))
        news_block_after_min = float(data.get('news_block_after_min', 2.0))
        import time
        profit_limit_start_time = int(time.time())

        if not name or not path:
            conn.close()
            return jsonify({"error": "Name and path required"}), 400

        try:
            c.execute("INSERT INTO instances (name, path, risk_usd, symbol_mapping, auto_trade, accepted_timeframe, profit_limit, profit_limit_start_time, group_name, alert_drawdown_limit, alert_profit_ceiling_usd, account_type, alert_profit_lock_pct, alert_drawdown_levels, news_block_before_min, news_block_after_min) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (name, path, risk_usd, symbol_mapping, auto_trade, accepted_timeframe, profit_limit, profit_limit_start_time, group_name, alert_drawdown_limit, alert_profit_ceiling_usd, account_type, alert_profit_lock_pct, alert_drawdown_levels, news_block_before_min, news_block_after_min))
        except sqlite3.OperationalError:
            try:
                c.execute("INSERT INTO instances (name, path, risk_usd, symbol_mapping, auto_trade, accepted_timeframe, profit_limit, profit_limit_start_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (name, path, risk_usd, symbol_mapping, auto_trade, accepted_timeframe, profit_limit, profit_limit_start_time))
            except sqlite3.OperationalError:
                c.execute("INSERT INTO instances (name, path, risk_usd, symbol_mapping, auto_trade, accepted_timeframe) VALUES (?, ?, ?, ?, ?, ?)", (name, path, risk_usd, symbol_mapping, auto_trade, accepted_timeframe))

        conn.commit()
        new_id = c.lastrowid
        conn.close()
        return jsonify({"id": new_id, "name": name, "path": path, "risk_usd": risk_usd, "symbol_mapping": symbol_mapping, "auto_trade": auto_trade, "accepted_timeframe": accepted_timeframe, "profit_limit": profit_limit, "account_type": account_type, "alert_drawdown_levels": alert_drawdown_levels, "news_block_before_min": news_block_before_min, "news_block_after_min": news_block_after_min}), 201
        
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
        alert_profit_ceiling_usd = float(data.get('alert_profit_ceiling_usd', 0.0))
        account_type = data.get('account_type', 'PERSONAL')
        alert_profit_lock_pct = float(data.get('alert_profit_lock_pct', 0.0))
        alert_drawdown_levels = _format_drawdown_levels(_parse_drawdown_levels(data.get('alert_drawdown_levels', '2,4,6,8,10'))) or '2,4,6,8,10'
        news_block_before_min = float(data.get('news_block_before_min', 2.0))
        news_block_after_min = float(data.get('news_block_after_min', 2.0))

        if not instance_id or not name or not path:
            conn.close()
            return jsonify({"error": "ID, name and path required"}), 400

        try:
            c.execute("UPDATE instances SET name=?, path=?, risk_usd=?, symbol_mapping=?, auto_trade=?, accepted_timeframe=?, profit_limit=?, group_name=?, alert_drawdown_limit=?, alert_profit_ceiling_usd=?, account_type=?, alert_profit_lock_pct=?, alert_drawdown_levels=?, news_block_before_min=?, news_block_after_min=? WHERE id=?", (name, path, risk_usd, symbol_mapping, auto_trade, accepted_timeframe, profit_limit, group_name, alert_drawdown_limit, alert_profit_ceiling_usd, account_type, alert_profit_lock_pct, alert_drawdown_levels, news_block_before_min, news_block_after_min, instance_id))
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

@flask_app.route('/api/portfolio_overview', methods=['GET'])
def api_portfolio_overview():
    """Per-instance risk metrics + daily P&L series for the trailing N days
    (default 90, i.e. 'last quarter'). Deliberately DB-only — no MT5 calls —
    so the Portfolio Management page can hit this freely without contending
    with the poller's mt5_lock. The frontend anchors the equity curve to
    each instance's *live* equity (already streamed over the socket) and
    walks these daily deltas backwards from there."""
    days = int(request.args.get('days', 90))
    days = max(1, min(days, 365))

    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    c.execute("SELECT id, name, group_name, account_type, copier_role FROM instances ORDER BY id ASC")
    instances = c.fetchall()

    # date_from/date_to query risk_snapshots, whose `date` the poller writes in UTC -- a
    # range query has to match its own writer's frame, so these stay UTC even though trade
    # bucketing below uses the journal day. Unifying the two means moving the live daily
    # reset as well, which is a risk-behaviour decision (a prop firm's daily loss window
    # is the broker's day, not this machine's), not a display one.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    date_from = (now - timedelta(days=days)).strftime('%Y-%m-%d')
    date_to = now.strftime('%Y-%m-%d')
    # int(time.time()), not naive utcnow().timestamp(): the latter is read as local time and
    # lands hours in the past (19800s on a UTC+5:30 machine), which was silently excluding
    # every trade closed within that span from all of this page's metrics.
    ts_to = int(time.time())
    ts_from = ts_to - days * 86400

    result = []
    for inst_id, name, group_name, account_type, copier_role in instances:
        risk = _query_risk_range(c, inst_id, date_from, date_to)
        stats = _query_trade_stats(c, inst_id, ts_from, ts_to)
        daily_pnl = _query_daily_pnl(c, inst_id, days)

        result.append({
            "id": inst_id,
            "name": name,
            "group_name": group_name or 'Ungrouped',
            "account_type": account_type or 'PERSONAL',
            "copier_role": copier_role or 'NONE',
            "days": days,
            "daily_pnl": daily_pnl,
            "risk": {
                "peak_drawdown_pct": risk["peak_drawdown_pct"],
                "max_risk_usd": risk["max_risk_usd"],
                "no_sl_count": risk["no_sl_count"],
                "total_trades": stats["total_trades"],
                "win_rate": stats["win_rate"],
                "profit_factor": stats["profit_factor"],
                "largest_loss": stats["largest_loss"],
                "best_trade": stats["best_trade"],
                "max_loss_streak": stats["max_loss_streak"],
                "total_realized": stats["total_realized"],
            },
        })

    conn.close()
    return jsonify(result)

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

@flask_app.route('/api/instances/unlock', methods=['POST'])
def api_instances_unlock():
    """Clears trade_locked, set by the profit-ceiling auto-close (see poller_thread) once it
    books profit on an instance. Manual-only -- there's no automatic reset."""
    data = request.json
    instance_id = data.get('id')
    if not instance_id:
        return jsonify({"error": "ID required"}), 400

    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    try:
        c.execute("UPDATE instances SET trade_locked=0 WHERE id=?", (instance_id,))
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

# MT5 deal-entry constants, read defensively so the module still imports against a build
# that renames one. 0=IN (opens volume), 1=OUT, 2=INOUT (reversal), 3=OUT_BY (close-by).
DEAL_ENTRY_IN = getattr(mt5, 'DEAL_ENTRY_IN', 0)
DEAL_ENTRY_OUT = getattr(mt5, 'DEAL_ENTRY_OUT', 1)
DEAL_ENTRY_INOUT = getattr(mt5, 'DEAL_ENTRY_INOUT', 2)
DEAL_ENTRY_OUT_BY = getattr(mt5, 'DEAL_ENTRY_OUT_BY', 3)

# Bumped whenever the *meaning* of a trading_log row changes, or when a new table needs
# backfilling from full history. An instance whose stored version is lower gets exactly one
# forced full rebuild.
#   v2: one row per position (was one per closing deal, each carrying the whole P&L)
#   v3: balance_operations captured, so historical deposits/withdrawals exist for the
#       return series that Sharpe/Sortino/Calmar are computed from
TRADING_LOG_SCHEMA_VERSION = 3

# Incremental syncs re-examine a little before the bookmark: a position can open before the
# window and close inside it, and brokers post swap/commission adjustments after the closing
# deal. Cheap insurance -- these positions are simply rebuilt from source.
SYNC_OVERLAP_SECONDS = 3 * 24 * 3600


def _broker_time_offset(deals):
    """Seconds to add to a broker-time deal epoch to get a true UTC epoch.

    MT5 reports deal/tick times as epochs expressed in the *server's* timezone, so
    (wall-clock UTC now - tick epoch now) recovers the constant shift. Returns None when no
    symbol yields a tick, so callers can refuse to write rows with a fabricated offset.
    """
    candidates = []
    seen = set()
    for d in reversed(deals):
        if d.symbol and d.symbol not in seen:
            seen.add(d.symbol)
            candidates.append(d.symbol)
        if len(candidates) >= 10:
            break
    if not candidates:
        all_symbols = mt5.symbols_get() or ()
        candidates = [s.name for s in all_symbols[:10]]

    for symbol in candidates:
        mt5.symbol_select(symbol, True)
        tick = mt5.symbol_info_tick(symbol)
        if tick and tick.time > 0:
            return int(time.time()) - tick.time
    return None


def _entry_protection(entry_deal, opened_volume):
    """(sl, tp, risk_usd) the position was opened with, from the entry *order's* history.

    Deliberately not sourced from live polling: the poller only sees an SL if it happens to
    sample while the position is open, so it misses fast trades and every stretch where the
    app wasn't running. Order history persists regardless.

    risk_usd is sized on the position's total opened volume rather than the first entry
    deal's, so a position scaled into reports the risk it actually carried.
    """
    sl = tp = 0.0
    risk_usd = 0.0
    try:
        entry_orders = mt5.history_orders_get(ticket=entry_deal.order)
    except Exception:
        entry_orders = None
    if entry_orders:
        sl = entry_orders[0].sl or 0.0
        tp = entry_orders[0].tp or 0.0

    if sl:
        volume = opened_volume or entry_deal.volume
        order_type = mt5.ORDER_TYPE_BUY if entry_deal.type == mt5.DEAL_TYPE_BUY else mt5.ORDER_TYPE_SELL
        calc = mt5.order_calc_profit(order_type, entry_deal.symbol, volume, entry_deal.price, sl)
        if calc is not None:
            risk_usd = abs(calc)
        else:
            sym_info = mt5.symbol_info(entry_deal.symbol)
            if sym_info and sym_info.trade_tick_size and sym_info.trade_tick_value:
                ticks_lost = abs(entry_deal.price - sl) / sym_info.trade_tick_size
                risk_usd = ticks_lost * sym_info.trade_tick_value * volume
    return sl, tp, risk_usd


def _build_position_row(pos_deals, time_offset):
    """Collapse every deal of one MT5 position into a single closed-trade row.

    Returns None when the position isn't fully closed (opened volume still exceeds closed
    volume), so open and partially-closed positions never enter closed-trade history with a
    half-formed P&L.

    This one-row-per-position shape is the fix for the multi-counting defect: profit,
    commission and swap are each summed over the position exactly once here, whereas the
    previous sync wrote one row per closing deal and gave *every* one of them the whole
    position's total -- turning a three-part scale-out into 3x its real P&L.
    """
    trade_deals = [d for d in pos_deals if d.type in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL)]
    in_deals = [d for d in trade_deals if d.entry == DEAL_ENTRY_IN]
    out_deals = [d for d in trade_deals if d.entry in (DEAL_ENTRY_OUT, DEAL_ENTRY_OUT_BY, DEAL_ENTRY_INOUT)]
    if not in_deals or not out_deals:
        return None

    opened_volume = sum(d.volume for d in in_deals)
    closed_volume = sum(d.volume for d in out_deals)
    if closed_volume + 1e-8 < opened_volume:
        return None

    in_deals.sort(key=lambda d: (d.time, d.ticket))
    out_deals.sort(key=lambda d: (d.time, d.ticket))
    entry_deal = in_deals[0]
    last_out = out_deals[-1]

    raw_profit = sum(d.profit for d in trade_deals)
    commission = sum(d.commission for d in trade_deals)
    swap = sum(d.swap for d in trade_deals)

    def vwap(deals):
        vol = sum(d.volume for d in deals)
        return (sum(d.price * d.volume for d in deals) / vol) if vol else 0.0

    return {
        "position_id": entry_deal.position_id,
        "ticket": last_out.ticket,
        "symbol": entry_deal.symbol,
        # `type` stays the closing deal's type for backward compatibility with existing
        # readers; `direction` below is the one to actually use.
        "type": last_out.type,
        "direction": 0 if entry_deal.type == mt5.DEAL_TYPE_BUY else 1,
        "volume": closed_volume,
        "opened_volume": opened_volume,
        "raw_profit": raw_profit,
        "commission": commission,
        "swap": swap,
        "profit": raw_profit + commission + swap,
        "time": last_out.time,
        "local_start_time": entry_deal.time + time_offset,
        "local_time": last_out.time + time_offset,
        "magic": entry_deal.magic,
        "comment": entry_deal.comment,
        "entry_price": vwap(in_deals),
        "exit_price": vwap(out_deals),
        "entry_deal": entry_deal,
    }


def sync_trading_log(full=False):
    """Refresh trading_log from each instance's MT5 deal history, one row per *position*.

    Incremental by default: only positions touched since that instance's bookmark (minus
    SYNC_OVERLAP_SECONDS) are rebuilt, instead of deleting all history and re-fetching from
    the year 2000 on every cycle. Pass full=True to force a complete rebuild.
    """
    mode = "full" if full else "incremental"
    logging.info(f"Syncing trading log from MT5 instances ({mode})...")
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    c.execute("SELECT id, name, path FROM instances")
    instances = c.fetchall()

    if not instances:
        instances = [(None, "Default", None)]

    total_synced = 0
    for inst_id, inst_name, inst_path in instances:
        bookmark = None
        if inst_id is not None:
            c.execute(
                "SELECT last_deal_time, schema_version FROM trading_log_sync_state WHERE instance_id = ?",
                (inst_id,)
            )
            bookmark = c.fetchone()
        last_deal_time = (bookmark[0] or 0) if bookmark else 0
        schema_version = (bookmark[1] or 0) if bookmark else 0

        # inst_id None is the pathless "Default" fallback, which has no bookmark row to key.
        rebuild = (
            full
            or inst_id is None
            or schema_version < TRADING_LOG_SCHEMA_VERSION
            or last_deal_time <= 0
        )

        with mt5_lock:
            initialized = mt5.initialize(path=inst_path) if inst_path else mt5.initialize()
            if not initialized:
                logging.error(f"Failed to initialize MT5 for instance {inst_name}")
                continue

            # last_deal_time is a raw deal.time, i.e. broker-time-as-epoch, and
            # history_deals_get() interprets naive datetimes in that same frame -- so the
            # bookmark round-trips without ever converting to UTC. (local_time is the
            # UTC-corrected column; it is deliberately not what the bookmark tracks.)
            from_date = datetime(2000, 1, 1) if rebuild else datetime.utcfromtimestamp(
                max(0, last_deal_time - SYNC_OVERLAP_SECONDS)
            )
            to_date = datetime.now() + timedelta(days=1)

            deals = mt5.history_deals_get(from_date, to_date)
            if deals is None:
                logging.error(f"Failed to get history deals for {inst_name}: {mt5.last_error()}")
                continue

            if not deals:
                continue

            time_offset = _broker_time_offset(deals)
            if time_offset is None:
                # Writing rows with a fabricated 0 offset would silently misdate every trade
                # by the broker's UTC offset, so skip this instance and retry next cycle.
                logging.error(f"No tick available to derive broker time offset for {inst_name}; skipping sync")
                continue

            position_ids = {
                d.position_id for d in deals
                if d.type in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL) and d.position_id
            }
            max_deal_time = max(d.time for d in deals)

            if rebuild:
                c.execute("DELETE FROM trading_log WHERE instance_id = ?", (inst_id,))
                c.execute("DELETE FROM balance_operations WHERE instance_id = ?", (inst_id,))

            # Non-trade balance changes: deposits, withdrawals, credits, corrections. Kept
            # apart from trading_log so they never pollute trade statistics, but recorded so
            # the daily return series can subtract them out.
            for d in deals:
                if d.type in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL):
                    continue
                amount = (d.profit or 0.0) + (d.commission or 0.0) + (d.swap or 0.0)
                if amount == 0:
                    continue
                c.execute('''
                    INSERT OR REPLACE INTO balance_operations
                        (instance_id, ticket, time, local_time, deal_type, amount, comment)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (inst_id, d.ticket, d.time, d.time + time_offset, d.type, amount, d.comment))

            synced_here = 0
            for pid in sorted(position_ids):
                pos_deals = mt5.history_deals_get(position=pid)
                if not pos_deals:
                    continue

                row = _build_position_row(list(pos_deals), time_offset)
                if row is None:
                    continue

                sl_at_open, tp_at_open, entry_risk_usd = _entry_protection(
                    row["entry_deal"], row["opened_volume"]
                )

                try:
                    # Replace rather than insert: an incremental re-run, or a position that
                    # picked up another partial close since last sync, must not leave the
                    # previous row behind.
                    c.execute(
                        "DELETE FROM trading_log WHERE instance_id = ? AND position_id = ?",
                        (inst_id, pid)
                    )
                    c.execute('''
                        INSERT OR REPLACE INTO trading_log (
                            instance_id, ticket, position_id, symbol, type, direction, volume, profit,
                            time, magic, comment, commission, swap, raw_profit, local_start_time,
                            local_time, sl_at_open, tp_at_open, entry_risk_usd, entry_price, exit_price
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        inst_id, row["ticket"], row["position_id"], row["symbol"], row["type"],
                        row["direction"], row["volume"], row["profit"], row["time"], row["magic"],
                        row["comment"], row["commission"], row["swap"], row["raw_profit"],
                        row["local_start_time"], row["local_time"], sl_at_open, tp_at_open,
                        entry_risk_usd, row["entry_price"], row["exit_price"]
                    ))
                    synced_here += 1
                except Exception as e:
                    logging.error(f"Error writing position {pid} for {inst_name}: {e}")

            if inst_id is not None:
                c.execute('''
                    INSERT OR REPLACE INTO trading_log_sync_state
                        (instance_id, last_deal_time, schema_version, last_sync_at)
                    VALUES (?, ?, ?, ?)
                ''', (inst_id, int(max_deal_time), TRADING_LOG_SCHEMA_VERSION, int(time.time())))

            total_synced += synced_here
            logging.info(
                f"{inst_name}: {mode} sync wrote {synced_here} closed positions "
                f"from {len(deals)} deals (offset {time_offset}s)"
            )

        # Commit per instance so one failing terminal can't discard the others' work.
        conn.commit()

    conn.close()
    logging.info(f"Sync complete. Wrote {total_synced} closed positions.")
    return total_synced


@flask_app.route('/api/sync_log', methods=['POST'])
def api_sync_log():
    # Manual sync is the "something looks wrong, rebuild it" button, so it forces a full
    # resync; the background thread below stays incremental.
    total_synced = sync_trading_log(full=request.args.get('full', '1') != '0')
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
    
    query = (
        "SELECT l.id, l.instance_id, i.name, l.ticket, l.symbol, l.type, l.volume, l.profit, "
        "l.time, l.magic, l.comment, l.commission, l.swap, l.raw_profit, l.local_start_time, "
        "l.local_time, l.position_id, l.direction, l.entry_price, l.exit_price, l.sl_at_open, "
        "l.tp_at_open, l.entry_risk_usd "
        "FROM trading_log l LEFT JOIN instances i ON l.instance_id = i.id"
    )
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
    scratch_trades = 0
    total_trades = 0

    for r in rows:
        trades.append({
            "id": r[0],
            "instance_id": r[1],
            "instance_name": r[2] or "Default",
            "ticket": r[3],
            "symbol": r[4],
            # direction is stored from the ENTRY deal (0 = long, 1 = short). Rows written
            # before that column existed only have `type`, which is the *closing* deal's
            # type and therefore inverted relative to the position -- a long closes with a
            # SELL deal -- hence the fallback inversion.
            "type": (
                ("BUY" if r[17] == 0 else "SELL") if r[17] is not None
                else ("SELL" if r[5] == 0 else "BUY" if r[5] == 1 else str(r[5]))
            ),
            "volume": r[6],
            "profit": r[7],
            "time": r[8],
            "magic": r[9],
            "comment": r[10],
            "commission": r[11],
            "swap": r[12],
            "raw_profit": r[13],
            "local_start_time": r[14],
            "local_time": r[15],
            "position_id": r[16],
            "direction": r[17],
            "entry_price": r[18],
            "exit_price": r[19],
            "sl_at_open": r[20],
            "tp_at_open": r[21],
            "entry_risk_usd": r[22],
        })
        
        # Every row is one closed position now, so all of them count. Scratch trades
        # (exactly breakeven) are excluded from the win-rate denominator rather than
        # silently counted as losses.
        profit = r[7] or 0.0
        total_profit += profit
        total_trades += 1
        if profit > 0:
            profitable_trades += 1
        elif profit == 0:
            scratch_trades += 1

    decided_trades = total_trades - scratch_trades
    win_rate = (profitable_trades / decided_trades * 100) if decided_trades > 0 else 0
    
    conn.close()
    
    return jsonify({
        "metrics": {
            "total_profit": round(total_profit, 2),
            "win_rate": round(win_rate, 2),
            "total_trades": total_trades,
            "scratch_trades": scratch_trades
        },
        "trades": trades
    })

@flask_app.route('/api/review_dates', methods=['GET'])
def api_review_dates():
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    # Bucketed through the same journal-day offset as /api/portfolio_overview's daily P&L,
    # so a date listed here always matches the day that page attributes trades to.
    cfg = _journal_day_config(c)
    c.execute("SELECT DISTINCT COALESCE(local_time, time) FROM trading_log")
    rows = c.fetchall()
    conn.close()

    dates = sorted({_journal_date_str(r[0], cfg) for r in rows if r[0] is not None}, reverse=True)
    return jsonify({"dates": dates})


@flask_app.route('/api/journal/config', methods=['GET', 'POST'])
def api_journal_config():
    """The journal-day offset, so the frontend buckets days exactly the way the backend
    does instead of falling back to the browser's own timezone (which is how a trade can
    appear on one date in a table and another in the daily P&L)."""
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()

    if request.method == 'POST':
        data = request.json or {}
        anchor = str(data.get('journal_day_anchor', 'MACHINE')).upper()
        if anchor not in ('MACHINE', 'UTC', 'FIXED'):
            conn.close()
            return jsonify({"error": "journal_day_anchor must be MACHINE, UTC or FIXED"}), 400
        try:
            offset_min = int(data.get('journal_day_offset_min', 0))
        except (TypeError, ValueError):
            conn.close()
            return jsonify({"error": "journal_day_offset_min must be an integer"}), 400
        if not -1440 < offset_min < 1440:
            conn.close()
            return jsonify({"error": "journal_day_offset_min must be within +/- 24h"}), 400
        c.execute(
            "UPDATE global_settings SET journal_day_anchor = ?, journal_day_offset_min = ? WHERE id = 1",
            (anchor, offset_min)
        )
        conn.commit()

    cfg = _journal_day_config(c)
    conn.close()
    # current_offset_min is what the anchor resolves to *right now* -- informational, so the
    # UI can show "days start at 00:00 UTC+05:30" without re-deriving it.
    now = datetime.now(timezone.utc).astimezone()
    resolved = (
        int(now.utcoffset().total_seconds() // 60) if cfg["anchor"] == 'MACHINE'
        else cfg["offset_min"] if cfg["anchor"] == 'FIXED'
        else 0
    )
    return jsonify({
        "journal_day_anchor": cfg["anchor"],
        "journal_day_offset_min": cfg["offset_min"],
        "current_offset_min": resolved,
        "today": _journal_date_str(int(time.time()), cfg),
    })


# =============================== TRADING JOURNAL ===============================
# Per-instance closed-trade analytics. Everything here is DB-only (reads trading_log,
# kept fresh by trading_log_sync_thread) so these routes never touch mt5_lock and can be
# polled freely by the UI.
#
# House rules for every metric below, so numbers can't quietly disagree with each other:
#   * one row = one closed position (see sync_trading_log)
#   * `profit` is already net of commission and swap -- never re-add them
#   * win > 0, loss < 0, scratch == 0; scratches are excluded from the win-rate denominator
#     rather than counted as losses
#   * R metrics only include trades that had a stop, and always ship their coverage %
#   * a metric that can't be computed returns None, never a sentinel

JOURNAL_TRADE_COLUMNS = (
    "l.position_id, l.ticket, l.symbol, l.direction, l.type, l.volume, l.profit, "
    "l.raw_profit, l.commission, l.swap, COALESCE(l.local_time, l.time) AS close_ts, "
    "l.local_start_time, l.magic, l.comment, l.sl_at_open, l.tp_at_open, "
    "l.entry_risk_usd, l.entry_price, l.exit_price, l.mae_usd, l.mfe_usd"
)

DURATION_BUCKETS = (
    (60, "< 1m"),
    (300, "1-5m"),
    (1800, "5-30m"),
    (3600, "30-60m"),
    (14400, "1-4h"),
    (86400, "4-24h"),
    (float('inf'), "> 1d"),
)

WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _journal_dt(ts, cfg):
    """A timestamp as a naive datetime in the journal's day frame (see _journal_day_config).
    Hour-of-day and weekday breakdowns read from this, so they agree with the calendar."""
    ts = int(ts)
    if cfg["anchor"] == 'MACHINE':
        return datetime.fromtimestamp(ts)
    shift = cfg["offset_min"] * 60 if cfg["anchor"] == 'FIXED' else 0
    return datetime.utcfromtimestamp(ts + shift)


def _duration_bucket(seconds):
    if seconds is None or seconds < 0:
        return "unknown"
    for limit, label in DURATION_BUCKETS:
        if seconds < limit:
            return label
    return DURATION_BUCKETS[-1][1]


def _fetch_journal_trades(c, inst_id, ts_from=None, ts_to=None, filters=None):
    """Closed trades for one instance as plain dicts, newest last.

    Annotations are LEFT JOINed on (instance_id, position_id) -- never on trading_log.id,
    which a resync regenerates.
    """
    filters = filters or {}
    sql = (
        f"SELECT {JOURNAL_TRADE_COLUMNS}, a.tags, a.grade, a.note "
        "FROM trading_log l "
        "LEFT JOIN trade_annotations a "
        "  ON a.instance_id = l.instance_id AND a.position_id = l.position_id "
        "WHERE l.instance_id = ?"
    )
    params = [inst_id]

    if ts_from is not None:
        sql += " AND COALESCE(l.local_time, l.time) >= ?"
        params.append(int(ts_from))
    if ts_to is not None:
        sql += " AND COALESCE(l.local_time, l.time) < ?"
        params.append(int(ts_to))
    if filters.get('symbol'):
        sql += " AND l.symbol = ?"
        params.append(filters['symbol'])
    if filters.get('magic') is not None:
        sql += " AND l.magic = ?"
        params.append(int(filters['magic']))
    sql += " ORDER BY COALESCE(l.local_time, l.time) ASC"

    trades = []
    for r in c.execute(sql, params):
        close_ts = r[10]
        open_ts = r[11]
        duration = (close_ts - open_ts) if (close_ts is not None and open_ts) else None
        risk = r[16] or 0.0
        profit = r[6] or 0.0
        # direction is NULL on rows written before Phase 0; fall back to inverting the
        # closing deal's type, which is what the old schema encoded.
        direction = r[3]
        if direction is None:
            direction = 1 if r[4] == 0 else 0
        trades.append({
            "position_id": r[0],
            "ticket": r[1],
            "symbol": r[2],
            "direction": direction,
            "side": "LONG" if direction == 0 else "SHORT",
            "volume": r[5],
            "profit": profit,
            "raw_profit": r[7] or 0.0,
            "commission": r[8] or 0.0,
            "swap": r[9] or 0.0,
            "close_ts": close_ts,
            "open_ts": open_ts,
            "duration_sec": duration,
            "magic": r[12],
            "comment": r[13],
            "sl_at_open": r[14] or 0.0,
            "tp_at_open": r[15] or 0.0,
            "entry_risk_usd": risk,
            "entry_price": r[17] or 0.0,
            "exit_price": r[18] or 0.0,
            "r_multiple": (profit / risk) if risk > 0 else None,
            # NULL until the M1 backfill has run; 0.0 is a real value, so don't coalesce.
            "mae_usd": r[19],
            "mfe_usd": r[20],
            "mae_r": (r[19] / risk) if (risk > 0 and r[19] is not None) else None,
            "mfe_r": (r[20] / risk) if (risk > 0 and r[20] is not None) else None,
            "tags": r[21] or "",
            "grade": r[22] or "",
            "note": r[23] or "",
        })

    # Applied in Python rather than SQL because they derive from the journal day frame
    # (direction fallback, hour/weekday) rather than from a stored column.
    if filters.get('direction') in (0, 1):
        trades = [t for t in trades if t['direction'] == filters['direction']]
    if filters.get('outcome'):
        want = filters['outcome']
        trades = [t for t in trades if
                  (want == 'win' and t['profit'] > 0)
                  or (want == 'loss' and t['profit'] < 0)
                  or (want == 'scratch' and t['profit'] == 0)]
    return trades


def _stdev(values):
    """Sample standard deviation; None below two points, where it is undefined."""
    n = len(values)
    if n < 2:
        return None
    mean = sum(values) / n
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1))


def _streaks(profits):
    """(max_win_streak, max_loss_streak, current_streak) -- current is signed:
    +3 means three wins in a row, -2 two losses. Scratches break a streak without
    starting one."""
    max_win = max_loss = 0
    cur_win = cur_loss = 0
    for p in profits:
        if p > 0:
            cur_win += 1
            cur_loss = 0
        elif p < 0:
            cur_loss += 1
            cur_win = 0
        else:
            cur_win = cur_loss = 0
        max_win = max(max_win, cur_win)
        max_loss = max(max_loss, cur_loss)
    current = cur_win if cur_win else -cur_loss
    return max_win, max_loss, current


def _drawdown_series(trades, start_balance=None):
    """Running realized equity and the underwater curve, one point per closed trade.

    When start_balance is known the drawdown is a true percentage of the running
    high-water mark; without it only the dollar depth is meaningful, and pct is reported
    against the peak *cumulative P&L*, which is why the caller should pass a balance
    whenever it has one.
    """
    points = []
    running = start_balance if start_balance is not None else 0.0
    peak = running
    max_dd_usd = 0.0
    max_dd_pct = 0.0

    for t in trades:
        running += t['profit']
        peak = max(peak, running)
        dd_usd = peak - running
        dd_pct = (dd_usd / peak * 100.0) if peak > 0 else 0.0
        max_dd_usd = max(max_dd_usd, dd_usd)
        max_dd_pct = max(max_dd_pct, dd_pct)
        points.append({
            "ts": t['close_ts'],
            "equity": round(running, 2),
            "dd_usd": round(dd_usd, 2),
            "dd_pct": round(dd_pct, 4),
        })

    current_dd_usd = round(peak - running, 2) if points else 0.0
    current_dd_pct = round((peak - running) / peak * 100.0, 4) if points and peak > 0 else 0.0
    return {
        "points": points,
        "max_dd_usd": round(max_dd_usd, 2),
        "max_dd_pct": round(max_dd_pct, 4),
        "current_dd_usd": current_dd_usd,
        "current_dd_pct": current_dd_pct,
    }


def _journal_metrics(trades, start_balance=None):
    """Every headline number for one set of closed trades.

    Pure: takes rows, returns numbers, touches no DB and no MT5. That is what makes it
    testable against hand-computed cases.
    """
    total = len(trades)
    if total == 0:
        return {
            "total_trades": 0, "wins": 0, "losses": 0, "scratches": 0, "win_rate": None,
            "net_pnl": 0.0, "gross_profit": 0.0, "gross_loss": 0.0, "profit_factor": None,
            "avg_win": None, "avg_loss": None, "payoff_ratio": None,
            "breakeven_win_rate": None, "expectancy_usd": None, "expectancy_r": None,
            "r_coverage_pct": 0.0, "r_trades": 0, "sqn": None, "std_r": None,
            "largest_win": 0.0, "largest_loss": 0.0, "max_win_streak": 0,
            "max_loss_streak": 0, "current_streak": 0, "commission_total": 0.0,
            "swap_total": 0.0, "cost_drag_pct": None, "no_sl_count": 0,
            "avg_hold_win_sec": None, "avg_hold_loss_sec": None, "avg_hold_sec": None,
            "max_dd_usd": 0.0, "max_dd_pct": 0.0, "current_dd_usd": 0.0,
            "current_dd_pct": 0.0, "total_volume": 0.0,
        }

    profits = [t['profit'] for t in trades]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p < 0]
    scratches = total - len(wins) - len(losses)

    gross_profit = sum(wins)
    gross_loss = sum(losses)          # negative
    net_pnl = sum(profits)

    decided = len(wins) + len(losses)
    win_rate = (len(wins) / decided * 100.0) if decided else None

    avg_win = (gross_profit / len(wins)) if wins else None
    avg_loss = (gross_loss / len(losses)) if losses else None   # negative
    payoff = (avg_win / abs(avg_loss)) if (avg_win and avg_loss) else None
    # The win rate this payoff ratio needs just to break even -- shown beside the actual
    # win rate, it says immediately whether the edge is real.
    breakeven_wr = (1.0 / (1.0 + payoff) * 100.0) if payoff else None

    profit_factor = (gross_profit / abs(gross_loss)) if gross_loss < 0 else None

    r_values = [t['r_multiple'] for t in trades if t['r_multiple'] is not None]
    expectancy_r = (sum(r_values) / len(r_values)) if r_values else None
    std_r = _stdev(r_values)
    # Van Tharp SQN. Suppressed below 30 trades, where the estimator is too unstable to
    # report as a number without inviting a false read.
    sqn = (
        math.sqrt(len(r_values)) * expectancy_r / std_r
        if (len(r_values) >= 30 and std_r and std_r > 0) else None
    )

    max_win_streak, max_loss_streak, current_streak = _streaks(profits)

    commission_total = sum(t['commission'] for t in trades)
    swap_total = sum(t['swap'] for t in trades)
    # What fraction of the gross winnings the broker took. Swap is the one that quietly
    # kills carry-holding EAs, which is why it is tracked separately from commission.
    cost_drag = (
        (abs(commission_total) + abs(swap_total)) / gross_profit * 100.0
        if gross_profit > 0 else None
    )

    win_holds = [t['duration_sec'] for t in trades if t['profit'] > 0 and t['duration_sec'] is not None]
    loss_holds = [t['duration_sec'] for t in trades if t['profit'] < 0 and t['duration_sec'] is not None]
    all_holds = [t['duration_sec'] for t in trades if t['duration_sec'] is not None]

    dd = _drawdown_series(trades, start_balance)

    return {
        "total_trades": total,
        "wins": len(wins),
        "losses": len(losses),
        "scratches": scratches,
        "win_rate": win_rate,
        "net_pnl": net_pnl,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": profit_factor,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff_ratio": payoff,
        "breakeven_win_rate": breakeven_wr,
        "expectancy_usd": net_pnl / total,
        "expectancy_r": expectancy_r,
        "r_trades": len(r_values),
        "r_coverage_pct": len(r_values) / total * 100.0,
        "std_r": std_r,
        "sqn": sqn,
        "largest_win": max(profits) if profits else 0.0,
        "largest_loss": min(profits) if profits else 0.0,
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
        "current_streak": current_streak,
        "commission_total": commission_total,
        "swap_total": swap_total,
        "cost_drag_pct": cost_drag,
        "no_sl_count": sum(1 for t in trades if not t['sl_at_open']),
        "avg_hold_win_sec": (sum(win_holds) / len(win_holds)) if win_holds else None,
        "avg_hold_loss_sec": (sum(loss_holds) / len(loss_holds)) if loss_holds else None,
        "avg_hold_sec": (sum(all_holds) / len(all_holds)) if all_holds else None,
        "total_volume": sum(t['volume'] or 0.0 for t in trades),
        "max_dd_usd": dd["max_dd_usd"],
        "max_dd_pct": dd["max_dd_pct"],
        "current_dd_usd": dd["current_dd_usd"],
        "current_dd_pct": dd["current_dd_pct"],
    }


# --- Phase 2: risk-adjusted ratios, distribution shape, Monte Carlo -------------------
#
# The ratios below all consume a *daily return series*, which this app has to reconstruct:
# there is no historical equity record, only closed trades. So returns here are
# balance-based (realized) rather than equity-based (mark-to-market). That is the same
# thing every broker-statement analyser does, but it means an open position's floating
# swing never shows up as volatility. Every response says so via `basis`.

# Below this many observations the estimators are too unstable to publish as a number.
MIN_RETURN_DAYS = 60
MIN_MC_TRADES = 20


def _fetch_balance_ops(c, inst_id, ts_from=None, ts_to=None):
    sql = "SELECT COALESCE(local_time, time), amount FROM balance_operations WHERE instance_id = ?"
    params = [inst_id]
    if ts_from is not None:
        sql += " AND COALESCE(local_time, time) >= ?"
        params.append(int(ts_from))
    if ts_to is not None:
        sql += " AND COALESCE(local_time, time) < ?"
        params.append(int(ts_to))
    return c.execute(sql, params).fetchall()


def _daily_return_series(c, inst_id, trades, ts_from, ts_to, current_balance, cfg):
    """Daily realized returns, with deposits and withdrawals removed.

    A day's return is that day's trade P&L over the balance the day *started* with.
    Deposits move the base without being a return, so they are added to the next day's
    starting balance but never to the numerator -- otherwise funding an account reads as a
    spectacular trading day.

    Returns None when there is no live balance to anchor to: a percentage return needs a
    real denominator, and inventing one would quietly corrupt every ratio downstream.
    """
    if current_balance is None or not trades:
        return None

    ops = _fetch_balance_ops(c, inst_id, ts_from, ts_to)

    # Walk the balance back to the start of the window: strip everything that happened
    # after it, then the window's own trade P&L and funding.
    after_pnl = c.execute(
        "SELECT COALESCE(SUM(profit), 0) FROM trading_log "
        "WHERE instance_id = ? AND COALESCE(local_time, time) >= ?",
        (inst_id, ts_to)
    ).fetchone()[0] or 0.0
    after_ops = c.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM balance_operations "
        "WHERE instance_id = ? AND COALESCE(local_time, time) >= ?",
        (inst_id, ts_to)
    ).fetchone()[0] or 0.0

    window_pnl = sum(t['profit'] for t in trades)
    window_ops = sum(a for _, a in ops)
    start_balance = current_balance - after_pnl - after_ops - window_pnl - window_ops

    pnl_by_day = {}
    for t in trades:
        pnl_by_day[_journal_date_str(t['close_ts'], cfg)] = (
            pnl_by_day.get(_journal_date_str(t['close_ts'], cfg), 0.0) + t['profit']
        )
    ops_by_day = {}
    for ts, amount in ops:
        day = _journal_date_str(ts, cfg)
        ops_by_day[day] = ops_by_day.get(day, 0.0) + amount

    first_day = datetime.strptime(min(pnl_by_day), '%Y-%m-%d')
    last_day = datetime.strptime(max(pnl_by_day), '%Y-%m-%d')

    series = []
    balance = start_balance
    day = first_day
    while day <= last_day:
        key = day.strftime('%Y-%m-%d')
        pnl = pnl_by_day.get(key, 0.0)
        funding = ops_by_day.get(key, 0.0)
        # Funding lands before the day's trading: capital deposited on day D is available to
        # trade that same day. Applying it afterwards left a zero opening balance on the day
        # an account was funded, dropping that date out of the return series entirely.
        balance += funding

        # Weekends are skipped unless something actually happened -- most instruments are
        # closed, and padding them with zeros would understate volatility. Crypto days with
        # real trades still count, which is why this is a data test, not a calendar test.
        include = day.weekday() < 5 or pnl != 0.0 or funding != 0.0
        if include and balance > 0:
            series.append({
                "date": key,
                "start_balance": round(balance, 2),
                "pnl": round(pnl, 2),
                "funding": round(funding, 2),
                "ret": pnl / balance,
            })
        balance += pnl
        day += timedelta(days=1)

    return {"series": series, "start_balance": round(start_balance, 2), "end_balance": round(balance, 2)}


def _downside_deviation(returns, mar=0.0):
    """Standard Sortino denominator: RMS of shortfalls below the minimum acceptable
    return, averaged over *all* periods (not just the losing ones)."""
    if not returns:
        return None
    shortfalls = [min(r - mar, 0.0) ** 2 for r in returns]
    return math.sqrt(sum(shortfalls) / len(shortfalls))


def _ulcer_index(balances):
    """RMS of percentage drawdown at every point. Unlike max drawdown -- a single unlucky
    sample -- this measures how much time was spent underwater and how deep."""
    if not balances:
        return None
    peak = balances[0]
    squares = []
    for b in balances:
        peak = max(peak, b)
        dd = ((peak - b) / peak * 100.0) if peak > 0 else 0.0
        squares.append(dd * dd)
    return math.sqrt(sum(squares) / len(squares))


def _risk_adjusted_metrics(daily):
    """Sharpe / Sortino / Calmar / Ulcer from a daily return series.

    Risk-free rate is taken as zero and said so. periods_per_year is measured from the data
    rather than assumed to be 252, so an instrument that trades weekends annualises on its
    own calendar instead of an equities one.
    """
    empty = {
        "sharpe": None, "sortino": None, "calmar": None, "ulcer_index": None,
        "volatility_annual_pct": None, "return_annual_pct": None, "total_return_pct": None,
        "max_dd_pct": None, "observations": 0, "periods_per_year": None,
        "sufficient": False, "min_observations": MIN_RETURN_DAYS,
        "opening_balance": None, "closing_balance": None, "funding_total": None,
    }
    if not daily or not daily["series"]:
        return empty

    series = daily["series"]
    returns = [d["ret"] for d in series]
    n = len(returns)

    balances = [d["start_balance"] for d in series] + [daily["end_balance"]]
    span_days = (
        datetime.strptime(series[-1]["date"], '%Y-%m-%d')
        - datetime.strptime(series[0]["date"], '%Y-%m-%d')
    ).days + 1
    periods_per_year = (n / span_days * 365.25) if span_days > 0 else None

    start_b, end_b = daily["start_balance"], daily["end_balance"]

    # Time-weighted return: chain the daily returns geometrically. Each day is already
    # measured against the balance that day actually started with, so a deposit changes the
    # base without ever appearing as performance -- which is the whole reason TWR is the
    # standard for accounts with cash flows.
    #
    # The naive (end - funding) / start form this replaced broke outright whenever the
    # account was *funded inside the window*: the reconstructed opening balance is then 0,
    # and total return came back n/a while every other figure computed normally.
    twr = 1.0
    for r in returns:
        twr *= (1.0 + r)
    total_return = twr - 1.0 if returns else None

    max_dd_pct = 0.0
    peak = balances[0]
    for b in balances:
        peak = max(peak, b)
        if peak > 0:
            max_dd_pct = max(max_dd_pct, (peak - b) / peak * 100.0)

    ulcer = _ulcer_index(balances)

    out = dict(empty)
    out.update({
        "observations": n,
        "periods_per_year": round(periods_per_year, 1) if periods_per_year else None,
        "total_return_pct": round(total_return * 100.0, 3) if total_return is not None else None,
        "max_dd_pct": round(max_dd_pct, 3),
        "ulcer_index": round(ulcer, 3) if ulcer is not None else None,
        "sufficient": n >= MIN_RETURN_DAYS,
        # Exposed so the return can be audited against the account it was measured on.
        # opening_balance is legitimately 0 when the account was funded inside the window --
        # that is why the return is time-weighted rather than a simple end/start ratio.
        "opening_balance": round(start_b, 2),
        "closing_balance": round(end_b, 2),
        "funding_total": round(sum(d["funding"] for d in series), 2),
    })

    # Everything below is a distribution estimate; publishing it on a handful of days would
    # dress noise up as authority.
    if n < MIN_RETURN_DAYS or periods_per_year is None:
        return out

    mean_r = sum(returns) / n
    sd = _stdev(returns)
    dd_dev = _downside_deviation(returns)
    ann = math.sqrt(periods_per_year)

    if span_days > 0 and total_return is not None and total_return > -1:
        annual_return = (1.0 + total_return) ** (365.25 / span_days) - 1.0
    else:
        annual_return = None

    out.update({
        "sharpe": round(mean_r / sd * ann, 3) if sd and sd > 0 else None,
        "sortino": round(mean_r / dd_dev * ann, 3) if dd_dev and dd_dev > 0 else None,
        "volatility_annual_pct": round(sd * ann * 100.0, 3) if sd else None,
        "return_annual_pct": round(annual_return * 100.0, 3) if annual_return is not None else None,
        "calmar": (
            round(annual_return * 100.0 / max_dd_pct, 3)
            if (annual_return is not None and max_dd_pct > 0) else None
        ),
    })
    return out


def _r_distribution(trades, bin_size=0.5):
    """Histogram of R-multiples, plus how concentrated the profit is.

    The concentration numbers are the point of this panel: a strategy whose gross profit is
    mostly three outliers has not demonstrated an edge, however good the headline
    expectancy looks.
    """
    r_values = [t['r_multiple'] for t in trades if t['r_multiple'] is not None]
    profits = sorted((t['profit'] for t in trades if t['profit'] > 0), reverse=True)
    gross_profit = sum(profits)

    def share(k):
        return round(sum(profits[:k]) / gross_profit * 100.0, 2) if gross_profit > 0 and profits else None

    top_decile = max(1, len(profits) // 10) if profits else 0

    bins = []
    if r_values:
        lo = math.floor(min(r_values) / bin_size) * bin_size
        hi = math.ceil(max(r_values) / bin_size) * bin_size
        edges = []
        e = lo
        while e < hi - 1e-9:
            edges.append(e)
            e += bin_size
        if not edges:
            edges = [lo]
        counts = [0] * len(edges)
        for r in r_values:
            idx = min(int((r - lo) / bin_size), len(edges) - 1)
            counts[max(0, idx)] += 1
        bins = [
            {
                "start": round(edges[i], 2),
                "end": round(edges[i] + bin_size, 2),
                "label": f"{edges[i]:+.1f}R",
                "count": counts[i],
                "is_loss": edges[i] + bin_size <= 0.0001,
            }
            for i in range(len(edges))
        ]

    return {
        "bin_size": bin_size,
        "bins": bins,
        "r_trades": len(r_values),
        "coverage_pct": round(len(r_values) / len(trades) * 100.0, 1) if trades else 0.0,
        "min_r": round(min(r_values), 2) if r_values else None,
        "max_r": round(max(r_values), 2) if r_values else None,
        "median_r": round(sorted(r_values)[len(r_values) // 2], 3) if r_values else None,
        "top1_share_pct": share(1),
        "top3_share_pct": share(3),
        "top_decile_share_pct": share(top_decile) if top_decile else None,
        "winners": len(profits),
    }


def _monte_carlo_drawdown(trades, start_balance, iterations=5000, seed=None):
    """Reshuffle the *actual* trade sequence many times to see what drawdowns this strategy
    could plausibly have produced.

    Permutation, not resampling with replacement: the trade set is held fixed and only its
    order changes, which answers the question a trader actually has -- "was this drawdown
    bad luck in sequencing, or is something broken?" A current drawdown sitting at the 60th
    percentile is normal; one past the 99th is a signal.
    """
    profits = [t['profit'] for t in trades]
    n = len(profits)
    if n < MIN_MC_TRADES or start_balance is None or start_balance <= 0:
        return {
            "sufficient": False, "min_trades": MIN_MC_TRADES, "trades": n,
            "iterations": 0, "percentiles": {}, "actual_max_dd_pct": None,
            "actual_percentile": None, "final_percentiles": {}, "prob_worse": None,
        }

    # Keep the work bounded on large histories; 2000 paths still resolves the tail fine.
    iterations = max(200, min(iterations, 20000))
    if n * iterations > 4_000_000:
        iterations = max(200, 4_000_000 // n)

    rng = random.Random(seed)

    def max_dd_pct(sequence):
        balance = start_balance
        peak = balance
        worst = 0.0
        for p in sequence:
            balance += p
            peak = max(peak, balance)
            if peak > 0:
                worst = max(worst, (peak - balance) / peak * 100.0)
        return worst, balance

    actual_dd, _ = max_dd_pct(profits)

    def pctile(sorted_vals, p):
        if not sorted_vals:
            return None
        idx = min(len(sorted_vals) - 1, max(0, int(round(p / 100.0 * (len(sorted_vals) - 1)))))
        return round(sorted_vals[idx], 2)

    # Pass 1 -- permutation. Same trades, different order. Isolates sequencing risk: how bad
    # a drawdown this exact set of results could have produced if the losses had clustered
    # differently. Final P&L is invariant here by construction (a sum does not care about
    # order), which is why the outcome distribution comes from pass 2 instead.
    shuffled = list(profits)
    dds = []
    for _ in range(iterations):
        rng.shuffle(shuffled)
        dd, _final = max_dd_pct(shuffled)
        dds.append(dd)
    dds.sort()

    below = sum(1 for d in dds if d <= actual_dd)
    actual_percentile = round(below / len(dds) * 100.0, 1)

    # Pass 2 -- bootstrap with replacement. Draws n trades from the same distribution to
    # answer the forward-looking question: if the edge holds, what does the *next* run of
    # this many trades plausibly look like? Unlike pass 1 this does vary the total.
    boot_finals = []
    boot_dds = []
    for _ in range(iterations):
        sample = [profits[rng.randrange(n)] for _ in range(n)]
        dd, final = max_dd_pct(sample)
        boot_dds.append(dd)
        boot_finals.append(final - start_balance)
    boot_finals.sort()
    boot_dds.sort()

    return {
        "sufficient": True,
        "min_trades": MIN_MC_TRADES,
        "trades": n,
        "iterations": iterations,
        "start_balance": round(start_balance, 2),
        "actual_max_dd_pct": round(actual_dd, 3),
        "actual_percentile": actual_percentile,
        "prob_worse": round(100.0 - actual_percentile, 1),
        # Sequencing risk (permutation)
        "percentiles": {str(p): pctile(dds, p) for p in (50, 75, 90, 95, 99)},
        # Forward outlook (bootstrap)
        "bootstrap": {
            "final_percentiles": {str(p): pctile(boot_finals, p) for p in (5, 25, 50, 75, 95)},
            "dd_percentiles": {str(p): pctile(boot_dds, p) for p in (50, 90, 95, 99)},
            "prob_losing": round(sum(1 for f in boot_finals if f < 0) / len(boot_finals) * 100.0, 1),
            "actual_total": round(sum(profits), 2),
        },
    }


def _edge_ratio(trades):
    """Mean favourable excursion over mean adverse excursion, both normalised by the trade's
    own risk. Above 1 means trades travel further in your favour than against you before
    resolving -- the cleanest evidence that entries have an edge independent of exits."""
    mfe_r, mae_r = [], []
    for t in trades:
        risk = t.get('entry_risk_usd') or 0.0
        if risk <= 0 or t.get('mfe_usd') is None or t.get('mae_usd') is None:
            continue
        mfe_r.append(abs(t['mfe_usd']) / risk)
        mae_r.append(abs(t['mae_usd']) / risk)
    if not mfe_r:
        return {"edge_ratio": None, "avg_mfe_r": None, "avg_mae_r": None, "sample": 0}
    avg_mfe = sum(mfe_r) / len(mfe_r)
    avg_mae = sum(mae_r) / len(mae_r)
    return {
        "edge_ratio": round(avg_mfe / avg_mae, 3) if avg_mae > 0 else None,
        "avg_mfe_r": round(avg_mfe, 3),
        "avg_mae_r": round(avg_mae, 3),
        "sample": len(mfe_r),
    }


def _journal_group_stats(trades):
    """The subset of metrics that make sense as columns in a breakdown table."""
    m = _journal_metrics(trades)
    return {
        "trades": m["total_trades"],
        "net_pnl": round(m["net_pnl"], 2),
        "win_rate": round(m["win_rate"], 2) if m["win_rate"] is not None else None,
        "profit_factor": round(m["profit_factor"], 3) if m["profit_factor"] is not None else None,
        "expectancy_usd": round(m["expectancy_usd"], 2) if m["expectancy_usd"] is not None else None,
        "expectancy_r": round(m["expectancy_r"], 3) if m["expectancy_r"] is not None else None,
        "r_coverage_pct": round(m["r_coverage_pct"], 1),
        "max_dd_usd": m["max_dd_usd"],
        "avg_hold_sec": round(m["avg_hold_sec"]) if m["avg_hold_sec"] is not None else None,
        "gross_profit": round(m["gross_profit"], 2),
        "gross_loss": round(m["gross_loss"], 2),
    }


def _journal_window(request_args, c):
    """(ts_from, ts_to, days) for a request. days=0 means all history.

    Uses int(time.time()) rather than a naive utcnow().timestamp(), which reads as local
    time and lands hours in the past -- see the note in _query_daily_pnl.
    """
    try:
        days = int(request_args.get('days', 90))
    except (TypeError, ValueError):
        days = 90
    days = max(0, min(days, 3650))
    ts_to = int(time.time())
    ts_from = None if days == 0 else ts_to - days * 86400
    return ts_from, ts_to, days


def _pct_of(value, base):
    """A value as a percentage of the window's opening capital. None when there is no
    denominator to divide by -- an invented base would make every percentage on the page a
    guess."""
    if value is None or not base or base <= 0:
        return None
    return round(value / base * 100.0, 4)


def _reference_balance(c, inst_id, ts_from, ts_to, current_balance):
    """The capital this window opened with -- the single denominator behind every % figure
    on the page.

    One base for everything, deliberately. Percentages that each used a different
    denominator (opening balance here, balance-at-the-time there) would not add up, and a
    breakdown whose rows don't sum to the total is worse than no percentages at all.

    Computed from the *window bounds only*, never from the filtered trade set: if it moved
    when the user filtered to one EA, that EA's "% return" would be measured against a
    different account size than everything else on screen.

    Walks back from the live balance: strip what happened after the window, then the
    window's own trades and funding. If the account was *funded inside* the window that
    leaves 0, so the funding is added back -- the meaningful denominator is the capital that
    was actually available to trade.
    """
    if current_balance is None:
        return None
    lo = int(ts_from) if ts_from is not None else 0

    def total(table, col, frm, to=None):
        sql = (f"SELECT COALESCE(SUM({col}), 0) FROM {table} "
               "WHERE instance_id = ? AND COALESCE(local_time, time) >= ?")
        params = [inst_id, frm]
        if to is not None:
            sql += " AND COALESCE(local_time, time) < ?"
            params.append(to)
        return c.execute(sql, params).fetchone()[0] or 0.0

    after_pnl = total('trading_log', 'profit', ts_to)
    after_ops = total('balance_operations', 'amount', ts_to)
    window_pnl = total('trading_log', 'profit', lo, ts_to)
    window_ops = total('balance_operations', 'amount', lo, ts_to)

    opening = current_balance - after_pnl - after_ops - window_pnl - window_ops
    if opening <= 0:
        opening += window_ops
    return round(opening, 2) if opening > 0 else None


def _journal_instance(c, inst_id):
    c.execute(
        "SELECT id, name, group_name, account_type, copier_role, trade_locked "
        "FROM instances WHERE id = ?", (inst_id,)
    )
    r = c.fetchone()
    if not r:
        return None
    return {
        "id": r[0], "name": r[1], "group_name": r[2] or 'Ungrouped',
        "account_type": r[3] or 'PERSONAL', "copier_role": r[4] or 'NONE',
        "trade_locked": bool(r[5]),
    }


def _journal_request_filters(args):
    filters = {}
    if args.get('symbol'):
        filters['symbol'] = args['symbol']
    if args.get('magic') not in (None, '', 'all'):
        try:
            filters['magic'] = int(args['magic'])
        except (TypeError, ValueError):
            pass
    if args.get('direction') in ('0', '1'):
        filters['direction'] = int(args['direction'])
    elif args.get('direction') in ('LONG', 'SHORT'):
        filters['direction'] = 0 if args['direction'] == 'LONG' else 1
    if args.get('outcome') in ('win', 'loss', 'scratch'):
        filters['outcome'] = args['outcome']
    return filters


# --- MAE/MFE backfill -----------------------------------------------------------------
# Reconstructed from M1 bars rather than sampled live: the poller only sees a position if
# it happens to be open at a sample instant, so live sampling misses fast trades entirely
# and can never recover history. copy_rates_range works retroactively over everything the
# broker still holds, so a single pass fills years of trades.

mae_backfill_state = {}
mae_backfill_lock = threading.Lock()


def _backfill_mae_mfe(inst_id, inst_path, limit=None):
    """Fill mae_usd/mfe_usd for trades that don't have them yet.

    Deliberately takes mt5_lock per trade rather than for the whole job: this can run for
    minutes over a long history, and holding the lock throughout would stall the poller and
    with it every live risk alert.
    """
    def progress(**kw):
        with mae_backfill_lock:
            mae_backfill_state.setdefault(inst_id, {}).update(kw)

    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    sql = (
        "SELECT position_id, symbol, direction, volume, entry_price, local_start_time, "
        "local_time, time FROM trading_log "
        "WHERE instance_id = ? AND mae_usd IS NULL AND position_id IS NOT NULL "
        "AND entry_price > 0 AND local_start_time IS NOT NULL "
        "ORDER BY COALESCE(local_time, time) DESC"
    )
    params = [inst_id]
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))
    rows = c.execute(sql, params).fetchall()

    progress(status='RUNNING', total=len(rows), done=0, filled=0, failed=0, started_at=int(time.time()))
    if not rows:
        progress(status='IDLE', message='Nothing to backfill')
        conn.close()
        return {"total": 0, "filled": 0, "failed": 0}

    filled = failed = 0
    for i, (pid, symbol, direction, volume, entry_price, open_utc, close_utc, broker_close) in enumerate(rows):
        try:
            # local_* are true UTC; copy_rates_range wants broker-frame datetimes. The
            # per-row offset is recoverable as (local_time - time), so no global assumption.
            offset = (close_utc or 0) - (broker_close or 0)
            broker_open = (open_utc or 0) - offset
            frm = datetime.utcfromtimestamp(max(0, broker_open - 60))
            to = datetime.utcfromtimestamp((broker_close or 0) + 60)

            with mt5_lock:
                if not (mt5.initialize(path=inst_path) if inst_path else mt5.initialize()):
                    failed += 1
                    continue
                mt5.symbol_select(symbol, True)
                rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M1, frm, to)
                if rates is None or len(rates) == 0:
                    failed += 1
                    progress(done=i + 1, filled=filled, failed=failed)
                    continue

                worst_price = min(r['low'] for r in rates)
                best_price = max(r['high'] for r in rates)
                if direction == 1:      # short: price going up is adverse
                    worst_price, best_price = best_price, worst_price

                order_type = mt5.ORDER_TYPE_BUY if direction == 0 else mt5.ORDER_TYPE_SELL
                mae = mt5.order_calc_profit(order_type, symbol, volume, entry_price, worst_price)
                mfe = mt5.order_calc_profit(order_type, symbol, volume, entry_price, best_price)

            if mae is None or mfe is None:
                failed += 1
            else:
                # Excursions are one-sided by definition: the worst point can never be a
                # profit, the best can never be a loss, whatever rounding says.
                c.execute(
                    "UPDATE trading_log SET mae_usd = ?, mfe_usd = ? WHERE instance_id = ? AND position_id = ?",
                    (min(0.0, mae), max(0.0, mfe), inst_id, pid)
                )
                filled += 1
        except Exception as e:
            logging.error(f"MAE/MFE backfill failed for position {pid}: {e}")
            failed += 1

        if (i + 1) % 25 == 0:
            conn.commit()
        progress(done=i + 1, filled=filled, failed=failed)

    conn.commit()
    conn.close()
    progress(status='IDLE', message=f'Filled {filled}, failed {failed}')
    logging.info(f"MAE/MFE backfill for instance {inst_id}: filled {filled}, failed {failed}")
    return {"total": len(rows), "filled": filled, "failed": failed}


@flask_app.route('/api/journal/<int:inst_id>/backfill_mae', methods=['POST'])
def api_journal_backfill_mae(inst_id):
    with mae_backfill_lock:
        if mae_backfill_state.get(inst_id, {}).get('status') == 'RUNNING':
            return jsonify({"status": "ALREADY_RUNNING", **mae_backfill_state[inst_id]})

    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    row = c.execute("SELECT path FROM instances WHERE id = ?", (inst_id,)).fetchone()
    conn.close()
    if row is None:
        return jsonify({"error": "instance not found"}), 404

    limit = request.args.get('limit', type=int)
    threading.Thread(
        target=_backfill_mae_mfe, args=(inst_id, row[0], limit), daemon=True
    ).start()
    return jsonify({"status": "STARTED"})


@flask_app.route('/api/journal/<int:inst_id>/backfill_status', methods=['GET'])
def api_journal_backfill_status(inst_id):
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    pending = c.execute(
        "SELECT COUNT(*) FROM trading_log WHERE instance_id = ? AND mae_usd IS NULL "
        "AND position_id IS NOT NULL AND entry_price > 0", (inst_id,)
    ).fetchone()[0]
    filled = c.execute(
        "SELECT COUNT(*) FROM trading_log WHERE instance_id = ? AND mae_usd IS NOT NULL",
        (inst_id,)
    ).fetchone()[0]
    conn.close()
    with mae_backfill_lock:
        state = dict(mae_backfill_state.get(inst_id, {"status": "IDLE"}))
    return jsonify({**state, "pending": pending, "filled": filled})


@flask_app.route('/api/journal/<int:inst_id>/distribution', methods=['GET'])
def api_journal_distribution(inst_id):
    """R-multiple histogram plus profit-concentration stats and the MAE/MFE edge ratio."""
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    if _journal_instance(c, inst_id) is None:
        conn.close()
        return jsonify({"error": "instance not found"}), 404

    ts_from, ts_to, days = _journal_window(request.args, c)
    trades = _fetch_journal_trades(c, inst_id, ts_from, ts_to, _journal_request_filters(request.args))
    conn.close()

    try:
        bin_size = max(0.1, min(float(request.args.get('bin', 0.5)), 5.0))
    except (TypeError, ValueError):
        bin_size = 0.5

    return jsonify({
        "days": days,
        **_r_distribution(trades, bin_size),
        "edge": _edge_ratio(trades),
    })


@flask_app.route('/api/journal/<int:inst_id>/riskadjusted', methods=['GET'])
def api_journal_riskadjusted(inst_id):
    """Sharpe / Sortino / Calmar / Ulcer, plus the daily return series they came from."""
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    if _journal_instance(c, inst_id) is None:
        conn.close()
        return jsonify({"error": "instance not found"}), 404

    ts_from, ts_to, days = _journal_window(request.args, c)
    if ts_from is None:
        ts_from = 0
    cfg = _journal_day_config(c)
    trades = _fetch_journal_trades(c, inst_id, ts_from, ts_to, _journal_request_filters(request.args))

    balance = request.args.get('balance', type=float)
    daily = _daily_return_series(c, inst_id, trades, ts_from, ts_to, balance, cfg)
    conn.close()

    metrics = _risk_adjusted_metrics(daily)
    return jsonify({
        "days": days,
        # Named so nobody reads these as mark-to-market figures.
        "basis": "realized balance (closed trades only; floating P&L is not included)",
        "risk_free_rate": 0.0,
        "anchored": daily is not None,
        "metrics": metrics,
        "series": daily["series"] if daily else [],
    })


@flask_app.route('/api/journal/<int:inst_id>/montecarlo', methods=['GET'])
def api_journal_montecarlo(inst_id):
    """Drawdown envelope from reshuffling the actual trade sequence."""
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    if _journal_instance(c, inst_id) is None:
        conn.close()
        return jsonify({"error": "instance not found"}), 404

    ts_from, ts_to, days = _journal_window(request.args, c)
    trades = _fetch_journal_trades(c, inst_id, ts_from, ts_to, _journal_request_filters(request.args))

    balance = request.args.get('balance', type=float)
    start_balance = None
    if balance is not None:
        after = c.execute(
            "SELECT COALESCE(SUM(profit), 0) FROM trading_log "
            "WHERE instance_id = ? AND COALESCE(local_time, time) >= ?",
            (inst_id, ts_to)
        ).fetchone()[0] or 0.0
        start_balance = balance - after - sum(t['profit'] for t in trades)
    conn.close()

    iterations = request.args.get('iterations', default=5000, type=int)
    # Seeded so the same window returns the same envelope across reloads -- a percentile
    # that jitters every refresh is not something anyone can act on.
    return jsonify({
        "days": days,
        **_monte_carlo_drawdown(trades, start_balance, iterations, seed=inst_id * 7919 + len(trades)),
    })


@flask_app.route('/api/journal/<int:inst_id>/summary', methods=['GET'])
def api_journal_summary(inst_id):
    """Headline metrics for the verdict bar.

    Pass ?balance= (the instance's live balance, which the UI already has off the socket)
    to get drawdown as a true percentage of the high-water mark rather than of cumulative
    P&L -- see _drawdown_series.
    """
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()

    instance = _journal_instance(c, inst_id)
    if instance is None:
        conn.close()
        return jsonify({"error": "instance not found"}), 404

    ts_from, ts_to, days = _journal_window(request.args, c)
    filters = _journal_request_filters(request.args)
    trades = _fetch_journal_trades(c, inst_id, ts_from, ts_to, filters)

    # Reconstruct the balance the window opened at, so drawdown % is measured against real
    # account size. Everything closed after the window is subtracted back off the live
    # balance, then the window's own P&L.
    start_balance = None
    balance_arg = request.args.get('balance')
    if balance_arg:
        try:
            live_balance = float(balance_arg)
            c.execute(
                "SELECT COALESCE(SUM(profit), 0) FROM trading_log "
                "WHERE instance_id = ? AND COALESCE(local_time, time) >= ?",
                (inst_id, ts_to)
            )
            after_window = c.fetchone()[0] or 0.0
            start_balance = live_balance - after_window - sum(t['profit'] for t in trades)
        except (TypeError, ValueError):
            start_balance = None

    metrics = _journal_metrics(trades, start_balance)

    # Every dollar figure gets a percentage twin, all against the same opening capital, so
    # the numbers on this page can be compared and summed without conversion.
    ref = _reference_balance(c, inst_id, ts_from, ts_to, balance_arg and float(balance_arg))
    conn.close()

    metrics["pct"] = {
        "reference_balance": ref,
        "net_pnl": _pct_of(metrics["net_pnl"], ref),
        "gross_profit": _pct_of(metrics["gross_profit"], ref),
        "gross_loss": _pct_of(metrics["gross_loss"], ref),
        "expectancy": _pct_of(metrics["expectancy_usd"], ref),
        "avg_win": _pct_of(metrics["avg_win"], ref),
        "avg_loss": _pct_of(metrics["avg_loss"], ref),
        "largest_win": _pct_of(metrics["largest_win"], ref),
        "largest_loss": _pct_of(metrics["largest_loss"], ref),
        "commission": _pct_of(metrics["commission_total"], ref),
        "swap": _pct_of(metrics["swap_total"], ref),
    }

    return jsonify({
        "instance": instance,
        "days": days,
        "start_balance": round(start_balance, 2) if start_balance is not None else None,
        "reference_balance": ref,
        "metrics": metrics,
    })


@flask_app.route('/api/journal/<int:inst_id>/equity', methods=['GET'])
def api_journal_equity(inst_id):
    """Per-trade equity curve plus the underwater (drawdown) series that shares its x-axis.

    A bare equity curve hides drawdown depth and duration, which is the thing an algo
    operator most needs to see -- so the two are always returned together.
    """
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    if _journal_instance(c, inst_id) is None:
        conn.close()
        return jsonify({"error": "instance not found"}), 404

    ts_from, ts_to, days = _journal_window(request.args, c)
    cfg = _journal_day_config(c)
    filters = _journal_request_filters(request.args)
    trades = _fetch_journal_trades(c, inst_id, ts_from, ts_to, filters)

    start_balance = None
    balance_arg = request.args.get('balance')
    if balance_arg:
        try:
            live_balance = float(balance_arg)
            c.execute(
                "SELECT COALESCE(SUM(profit), 0) FROM trading_log "
                "WHERE instance_id = ? AND COALESCE(local_time, time) >= ?",
                (inst_id, ts_to)
            )
            after_window = c.fetchone()[0] or 0.0
            start_balance = live_balance - after_window - sum(t['profit'] for t in trades)
        except (TypeError, ValueError):
            start_balance = None

    ref = _reference_balance(c, inst_id, ts_from, ts_to, balance_arg and float(balance_arg))

    dd = _drawdown_series(trades, start_balance)
    running = 0.0
    for point, t in zip(dd["points"], trades):
        point["label"] = _journal_dt(t['close_ts'], cfg).strftime('%Y-%m-%d %H:%M')
        point["profit"] = round(t['profit'], 2)
        # Cumulative return to this point, so the curve can be read in % as well as dollars.
        running += t['profit']
        point["cum_pct"] = _pct_of(running, ref)

    conn.close()
    return jsonify({
        "days": days,
        "start_balance": round(start_balance, 2) if start_balance is not None else None,
        "reference_balance": ref,
        "anchored": start_balance is not None,
        **dd,
    })


@flask_app.route('/api/journal/<int:inst_id>/breakdown', methods=['GET'])
def api_journal_breakdown(inst_id):
    """Performance split by one dimension. ?by=magic|symbol|direction|hour|weekday|duration

    Tables, not charts, on purpose: this is the view an algo operator scans to find which
    EA or session is bleeding, and scanning is what tables are for.
    """
    by = request.args.get('by', 'magic')
    valid = ('magic', 'symbol', 'direction', 'hour', 'weekday', 'duration')
    if by not in valid:
        return jsonify({"error": f"by must be one of {', '.join(valid)}"}), 400

    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    if _journal_instance(c, inst_id) is None:
        conn.close()
        return jsonify({"error": "instance not found"}), 404

    ts_from, ts_to, days = _journal_window(request.args, c)
    cfg = _journal_day_config(c)
    filters = _journal_request_filters(request.args)
    trades = _fetch_journal_trades(c, inst_id, ts_from, ts_to, filters)
    ref = _reference_balance(c, inst_id, ts_from, ts_to, request.args.get('balance', type=float))
    conn.close()

    def key_for(t):
        if by == 'magic':
            return t['magic'] if t['magic'] is not None else 0
        if by == 'symbol':
            return t['symbol'] or 'unknown'
        if by == 'direction':
            return t['side']
        if by == 'hour':
            return _journal_dt(t['close_ts'], cfg).hour
        if by == 'weekday':
            return _journal_dt(t['close_ts'], cfg).weekday()
        return _duration_bucket(t['duration_sec'])

    groups = {}
    for t in trades:
        groups.setdefault(key_for(t), []).append(t)

    rows = []
    for key, group in groups.items():
        stats = _journal_group_stats(group)
        # Against the window's opening capital, so these add up to the page total.
        stats['net_pnl_pct'] = _pct_of(stats['net_pnl'], ref)
        if by == 'weekday':
            label = WEEKDAY_NAMES[key]
        elif by == 'hour':
            label = f"{key:02d}:00"
        elif by == 'magic':
            # The EA's own comment is the only human-readable hint we have until magic
            # aliases land, so surface the most recent one.
            label = str(key)
            stats['hint'] = group[-1]['comment'] or ''
        else:
            label = str(key)
        rows.append({"key": key, "label": label, **stats})

    if by in ('hour', 'weekday'):
        rows.sort(key=lambda r: r['key'])
    elif by == 'duration':
        order = [lbl for _, lbl in DURATION_BUCKETS] + ["unknown"]
        rows.sort(key=lambda r: order.index(r['key']) if r['key'] in order else 99)
    else:
        rows.sort(key=lambda r: r['net_pnl'])

    return jsonify({"by": by, "days": days, "reference_balance": ref, "rows": rows})


@flask_app.route('/api/journal/<int:inst_id>/calendar', methods=['GET'])
def api_journal_calendar(inst_id):
    """Daily P&L keyed by journal day, for the month-grid heatmap."""
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    if _journal_instance(c, inst_id) is None:
        conn.close()
        return jsonify({"error": "instance not found"}), 404

    ts_from, ts_to, days = _journal_window(request.args, c)
    cfg = _journal_day_config(c)
    filters = _journal_request_filters(request.args)
    trades = _fetch_journal_trades(c, inst_id, ts_from, ts_to, filters)
    ref = _reference_balance(c, inst_id, ts_from, ts_to, request.args.get('balance', type=float))
    conn.close()

    by_day = {}
    for t in trades:
        day = _journal_date_str(t['close_ts'], cfg)
        d = by_day.setdefault(day, {"date": day, "profit": 0.0, "trades": 0, "wins": 0, "losses": 0})
        d["profit"] += t['profit']
        d["trades"] += 1
        if t['profit'] > 0:
            d["wins"] += 1
        elif t['profit'] < 0:
            d["losses"] += 1

    out = []
    for d in sorted(by_day.values(), key=lambda x: x["date"]):
        decided = d["wins"] + d["losses"]
        out.append({
            **d,
            "profit": round(d["profit"], 2),
            "profit_pct": _pct_of(d["profit"], ref),
            "win_rate": round(d["wins"] / decided * 100.0, 1) if decided else None,
        })

    best = max(out, key=lambda d: d["profit"], default=None)
    worst = min(out, key=lambda d: d["profit"], default=None)
    return jsonify({
        "days": days,
        "anchor": cfg["anchor"],
        "reference_balance": ref,
        "entries": out,
        "best_day": best,
        "worst_day": worst,
        "active_days": len(out),
    })


@flask_app.route('/api/journal/<int:inst_id>/trades', methods=['GET'])
def api_journal_trades(inst_id):
    """The trade log itself. Newest first, paginated, honouring every page filter."""
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    if _journal_instance(c, inst_id) is None:
        conn.close()
        return jsonify({"error": "instance not found"}), 404

    ts_from, ts_to, days = _journal_window(request.args, c)
    cfg = _journal_day_config(c)
    filters = _journal_request_filters(request.args)
    trades = _fetch_journal_trades(c, inst_id, ts_from, ts_to, filters)
    ref = _reference_balance(c, inst_id, ts_from, ts_to, request.args.get('balance', type=float))
    conn.close()

    # A single-day filter (from clicking a calendar cell) is applied here because the day a
    # trade belongs to is a journal-frame question, not a SQL one.
    day = request.args.get('date')
    if day:
        trades = [t for t in trades if _journal_date_str(t['close_ts'], cfg) == day]

    try:
        limit = max(1, min(int(request.args.get('limit', 200)), 2000))
        offset = max(0, int(request.args.get('offset', 0)))
    except (TypeError, ValueError):
        limit, offset = 200, 0

    trades.reverse()   # newest first for display
    total = len(trades)
    page = trades[offset:offset + limit]
    for t in page:
        t["date"] = _journal_date_str(t['close_ts'], cfg)
        t["close_label"] = _journal_dt(t['close_ts'], cfg).strftime('%Y-%m-%d %H:%M:%S')
        t["open_label"] = (
            _journal_dt(t['open_ts'], cfg).strftime('%Y-%m-%d %H:%M:%S') if t['open_ts'] else None
        )
        t["profit_pct"] = _pct_of(t['profit'], ref)
        t["risk_pct"] = _pct_of(t['entry_risk_usd'], ref) if t['entry_risk_usd'] else None

    return jsonify({
        "days": days, "total": total, "offset": offset, "limit": limit,
        "reference_balance": ref, "trades": page,
    })


@flask_app.route('/api/journal/<int:inst_id>/annotation', methods=['POST'])
def api_journal_annotation(inst_id):
    """Upsert a tag/grade/note for one trade, keyed on (instance_id, position_id)."""
    data = request.json or {}
    position_id = data.get('position_id')
    if position_id is None:
        return jsonify({"error": "position_id is required"}), 400

    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO trade_annotations
            (instance_id, position_id, tags, grade, note, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        inst_id, int(position_id),
        str(data.get('tags', ''))[:500],
        str(data.get('grade', ''))[:8],
        str(data.get('note', ''))[:4000],
        int(time.time()),
    ))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


@flask_app.route('/api/journal/<int:inst_id>/filters', methods=['GET'])
def api_journal_filters(inst_id):
    """Distinct symbols and magic numbers present, to populate the filter controls."""
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    ts_from, ts_to, days = _journal_window(request.args, c)

    sql = "SELECT DISTINCT symbol, magic FROM trading_log WHERE instance_id = ?"
    params = [inst_id]
    if ts_from is not None:
        sql += " AND COALESCE(local_time, time) >= ?"
        params.append(ts_from)
    rows = c.execute(sql, params).fetchall()
    conn.close()

    return jsonify({
        "symbols": sorted({r[0] for r in rows if r[0]}),
        "magics": sorted({r[1] for r in rows if r[1] is not None}),
        "days": days,
    })


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
                c.execute("SELECT id, path, copier_role, copier_risk_type, copier_fixed_lot, copier_risk_usd, copier_risk_multiplier, symbol_mapping, account_type, news_block_before_min, news_block_after_min, trade_locked FROM instances WHERE copier_role IN ('PROVIDER', 'CONSUMER')")
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
                        '--account_type', str(r[8] if len(r) > 8 and r[8] else 'PERSONAL'),
                        '--news_before_min', str(r[9] if len(r) > 9 and r[9] is not None else 2.0),
                        '--news_after_min', str(r[10] if len(r) > 10 and r[10] is not None else 2.0),
                        '--trade_locked', str(int(r[11]) if len(r) > 11 and r[11] else 0),
                    ]
                    p = subprocess.Popen(cmd)
                    copier_workers[cid] = {'process': p, 'config': r}
                    logging.info(f"Started MT5 Copier Worker [{r[2]}] for Instance {cid}")
                    
        except Exception as e:
            logging.error(f"Copier manager error: {e}")

        time.sleep(3)

# --- NEWS BLACKOUT (PROP FIRM) ---

_news_state = {"last_success_date": None, "failure_alerted_date": None}

# Tracks which of today's high-impact events already got their T-15min
# Telegram heads-up. Reset whenever the date rolls over. Keyed by event_time
# (an absolute epoch, so no collision risk even without the daily reset —
# the reset just keeps the set from growing unbounded across long uptimes).
_news_reminder_state = {"date": "", "alerted": set()}
NEWS_REMINDER_LEAD_SEC = 15 * 60

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

def _check_news_blackout_reminders():
    """Ticks every 60s alongside the daily fetch (see news_calendar_thread).
    Once today's events are on disk — whether from the auto-fetch or a
    manual entry — this fires a Telegram heads-up ~15 minutes before each
    event's blackout window actually opens, without needing per-event
    timers: it's just a threshold crossing checked on every tick.

    Each PROPFIRM/CONSUMER instance can configure its own before/after
    blackout width (different prop firms restrict different amounts of
    time around news), so "when the blackout opens" is instance-specific.
    Instances sharing the same before-minutes are grouped into one message
    instead of sending a duplicate per instance."""
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    if _news_reminder_state["date"] != today_str:
        _news_reminder_state["date"] = today_str
        _news_reminder_state["alerted"] = set()

    payload = news_calendar.load_windows_file()
    events = payload.get("events", [])
    if not events:
        return

    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    try:
        c.execute("SELECT name, news_block_before_min FROM instances WHERE account_type = 'PROPFIRM' AND copier_role = 'CONSUMER'")
        rows = c.fetchall()
    except sqlite3.OperationalError:
        rows = []
    conn.close()
    if not rows:
        return

    groups = {}
    for name, before_min in rows:
        bm = before_min if before_min is not None else 2.0
        groups.setdefault(bm, []).append(name)

    now_epoch = time.time()
    for w in events:
        event_time = w.get("event_time")
        if event_time is None:
            continue
        for before_min, names in groups.items():
            alert_key = (event_time, before_min)
            if alert_key in _news_reminder_state["alerted"]:
                continue
            blackout_start = event_time - before_min * 60
            alert_at = blackout_start - NEWS_REMINDER_LEAD_SEC
            if alert_at <= now_epoch < blackout_start:
                local_time = datetime.fromtimestamp(event_time).strftime('%H:%M')
                names_str = ", ".join(names)
                send_telegram_message(
                    f"🔔 News blackout in 15 min: {w['currency']} {w['title']} at {local_time} "
                    f"(blocks {before_min:g} min before — {names_str})."
                )
                _news_reminder_state["alerted"].add(alert_key)

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

            _check_news_blackout_reminders()
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
        
    # Serve real files from the build root (favicon.svg and friends); anything else is a
    # client-side route and must get index.html so React Router can resolve it.
    full_path = os.path.join(frontend_dist, path)
    if path != "" and os.path.isfile(full_path):
        return send_from_directory(frontend_dist, path)


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
