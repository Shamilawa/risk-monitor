import customtkinter as ctk
import threading
import queue
import logging
import winsound
import subprocess
import urllib.request
import json
import MetaTrader5 as mt5
from flask import Flask, request, jsonify
import os
import requests
from dotenv import load_dotenv
import sqlite3
import random
import time

load_dotenv()

# --- CONFIGURATION ---
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# --- QUEUE FOR GUI EVENTS ---
signal_queue = queue.Queue()

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
        logging.warning("Telegram credentials not fully set in .env. Skipping Telegram notification.")
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
                    logging.info(f"[Magic {magic}] Recovery Trade Hit TP!")
                    send_telegram_message(f"✅ [Magic {magic}] {symbol} Recovery Trade hit TP!")
                    c.execute("UPDATE trade_groups SET status = 'RECOVERY_SUCCESS' WHERE magic_number = ?", (magic,))
                else:
                    logging.info(f"[Magic {magic}] Recovery Trade Hit SL!")
                    send_telegram_message(f"🛑 [Magic {magic}] {symbol} Recovery Trade hit SL!")
                    c.execute("UPDATE trade_groups SET status = 'RECOVERY_FAILED' WHERE magic_number = ?", (magic,))
                conn.commit()
                conn.close()
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

def poller_thread():
    while True:
        try:
            if not mt5.initialize():
                time.sleep(5)
                continue
                
            conn = sqlite3.connect('trades.db')
            c = conn.cursor()
            c.execute("SELECT magic_number, symbol, trade_1_ticket, trade_2_ticket, recovery_ticket, rec_action, rec_entry, rec_sl, rec_tp, rec_volume, status FROM trade_groups WHERE status IN ('ACTIVE', 'PENDING_ORIGINAL', 'RECOVERY_TRIGGERED')")
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
    c.execute("SELECT magic_number, symbol, trade_1_ticket, trade_2_ticket, recovery_ticket, rec_action, rec_entry, rec_sl, rec_tp, rec_volume, status FROM trade_groups WHERE status IN ('ACTIVE', 'PENDING_ORIGINAL', 'RECOVERY_TRIGGERED')")
    active_groups = c.fetchall()
    conn.close()
    
    for group in active_groups:
        check_trade_group(group)

# --- FLASK APP ---
flask_app = Flask(__name__)
werk_log = logging.getLogger('werkzeug')
werk_log.setLevel(logging.ERROR)

@flask_app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json(force=True)
    logging.info(f"RAW JSON from TV: {data}")
    if not data:
        return jsonify({"error": "Invalid payload"}), 400
        
    signal_queue.put(data)
    return jsonify({"status": "signal received"}), 200

def run_flask():
    flask_app.run(host='0.0.0.0', port=5000, use_reloader=False)

# --- GUI LOGGING HANDLER ---
class TextboxHandler(logging.Handler):
    def __init__(self, textbox):
        super().__init__()
        self.textbox = textbox

    def emit(self, record):
        msg = self.format(record)
        self.textbox.configure(state="normal")
        self.textbox.insert("end", msg + "\n")
        self.textbox.see("end")
        self.textbox.configure(state="disabled")

# --- GUI CLASS ---
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("MT5 Bridge Dashboard")
        self.geometry("850x700")
        
        # Grid Layout
        self.grid_rowconfigure(2, weight=1)
        self.grid_rowconfigure(3, weight=1)
        self.grid_columnconfigure(0, weight=1)
        
        # Header
        self.header_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.header_frame.grid(row=0, column=0, padx=20, pady=20, sticky="ew")
        
        self.title_label = ctk.CTkLabel(self.header_frame, text="⚡ MT5 TradingView Bridge", font=ctk.CTkFont(size=24, weight="bold"))
        self.title_label.pack(side="left")
        
        # Status Indicators
        self.status_frame = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        self.status_frame.pack(side="right")
        
        self.mt5_status = ctk.CTkLabel(self.status_frame, text="⬤ MT5 Connected", text_color="#2ecc71", font=ctk.CTkFont(weight="bold"))
        self.mt5_status.pack(side="right", padx=10)
        
        # Webhook URL Area
        self.url_frame = ctk.CTkFrame(self)
        self.url_frame.grid(row=1, column=0, padx=20, pady=(0, 10), sticky="ew")
        
        ctk.CTkLabel(self.url_frame, text="Webhook URL: ", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=10, pady=10)
        
        self.webhook_url = ctk.StringVar(value="Starting Ngrok tunnel...")
        self.url_entry = ctk.CTkEntry(self.url_frame, textvariable=self.webhook_url, state="readonly", width=400)
        self.url_entry.pack(side="left", padx=10, fill="x", expand=True)
        
        self.copy_btn = ctk.CTkButton(self.url_frame, text="Copy", width=60, command=self.copy_webhook)
        self.copy_btn.pack(side="left", padx=10)
        
        # Tracker View
        self.tracker_frame = ctk.CTkFrame(self)
        self.tracker_frame.grid(row=2, column=0, padx=20, pady=(0, 10), sticky="nsew")
        
        self.tracker_label = ctk.CTkLabel(self.tracker_frame, text="Live Trade Tracker", font=ctk.CTkFont(weight="bold", size=14))
        self.tracker_label.pack(anchor="w", padx=10, pady=5)
        
        self.col_widths = [250, 120, 140, 200]
        
        # Header Row
        header_container = ctk.CTkFrame(self.tracker_frame, fg_color="#333333", corner_radius=0)
        # Add 22px padding on the right to perfectly account for the scrollbar width below
        header_container.pack(fill="x", padx=(5, 22), pady=(0, 0))
        
        header_bg = "#1f1f1f"
        for i, (txt, w) in enumerate(zip(["Symbol / Group", "Ticket", "Trade Type", "Status"], self.col_widths)):
            header_container.grid_columnconfigure(i, minsize=w, weight=1)
            
            anchor = "w" if i in (0, 3) else "center"
            pad_x = (0, 1) if i < 3 else (0, 0)
            
            cell_f = ctk.CTkFrame(header_container, fg_color=header_bg, corner_radius=0)
            cell_f.grid(row=0, column=i, padx=pad_x, sticky="nsew")
            
            lbl = ctk.CTkLabel(cell_f, text=txt, anchor=anchor, font=ctk.CTkFont(weight="bold", size=12))
            lbl.pack(fill="both", expand=True, padx=10, pady=5)
        
        # Scrollable Table Body
        self.table_scroll = ctk.CTkScrollableFrame(self.tracker_frame, fg_color="#333333", corner_radius=0)
        self.table_scroll.pack(fill="both", expand=True, padx=5, pady=(0, 5))
        
        self.last_table_hash = None
        
        # Logs View
        self.log_frame = ctk.CTkFrame(self)
        self.log_frame.grid(row=3, column=0, padx=20, pady=(0, 20), sticky="nsew")
        
        self.log_label = ctk.CTkLabel(self.log_frame, text="Live Server Logs", font=ctk.CTkFont(weight="bold"))
        self.log_label.pack(anchor="w", padx=10, pady=5)
        
        self.log_box = ctk.CTkTextbox(self.log_frame, state="disabled", font=ctk.CTkFont(family="Consolas", size=13))
        self.log_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        
        self.setup_logging()
        logging.info("Starting Premium MT5 Bridge GUI...")
        
        # Verify MT5
        if not mt5.initialize():
            self.mt5_status.configure(text="⬤ MT5 Offline", text_color="#e74c3c")
            logging.error("Could not connect to MT5. Is it open?")
            
        # Start Server
        self.flask_thread = threading.Thread(target=run_flask, daemon=True)
        self.flask_thread.start()
        logging.info("Flask Webhook Server listening on port 5000...")
        
        # DB Reconcile and Poller
        reconcile_on_boot()
        self.poll_thread = threading.Thread(target=poller_thread, daemon=True)
        self.poll_thread.start()
        
        # Test Telegram Connection
        send_telegram_message("✅ MT5 Bridge GUI Started & Telegram Connected!")
        
        # Setup Ngrok
        self.ngrok_process = None
        self.start_ngrok()
        
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Start checking queue and updating UI table
        self.check_queue()
        self.update_tracker_table()

    def start_ngrok(self):
        logging.info("Starting Ngrok silently...")
        self.ngrok_process = subprocess.Popen(['ngrok', 'http', '5000'], creationflags=0x08000000)
        self.after(3000, self.fetch_ngrok_url)
        
    def fetch_ngrok_url(self):
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
                
                self.webhook_url.set(public_url + "/webhook")
                logging.info(f"Ngrok connected successfully: {public_url}")
            else:
                self.after(2000, self.fetch_ngrok_url)
        except Exception as e:
            self.after(2000, self.fetch_ngrok_url)

    def copy_webhook(self):
        self.clipboard_clear()
        self.clipboard_append(self.webhook_url.get())
        logging.info("Webhook URL copied to clipboard!")

    def on_closing(self):
        if self.ngrok_process:
            logging.info("Terminating Ngrok...")
            self.ngrok_process.terminate()
        self.destroy()

    def setup_logging(self):
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
        
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        logger.addHandler(ch)
        
        th = TextboxHandler(self.log_box)
        th.setFormatter(formatter)
        logger.addHandler(th)

    def check_queue(self):
        try:
            while not signal_queue.empty():
                data = signal_queue.get_nowait()
                self.show_trade_popup(data)
        except queue.Empty:
            pass
        finally:
            self.after(100, self.check_queue)
            
    def get_badge_colors(self, status):
        if status == "ACTIVE":
            return {"fg_color": "#1E3A8A", "text_color": "#60A5FA"}
        elif status == "PENDING_ORIGINAL" or status.startswith("PENDING"):
            return {"fg_color": "#78350F", "text_color": "#FBBF24"}
        elif status == "SUCCESS_TP1_HIT":
            return {"fg_color": "#064E3B", "text_color": "#34D399"}
        elif status == "RECOVERY_TRIGGERED":
            return {"fg_color": "#4C1D95", "text_color": "#A78BFA"}
        elif status == "CANCELLED":
            return {"fg_color": "#3F3F46", "text_color": "#A1A1AA"}
        elif status == "RECOVERY_SUCCESS":
            return {"fg_color": "#064E3B", "text_color": "#34D399"}
        elif status == "RECOVERY_FAILED":
            return {"fg_color": "#7F1D1D", "text_color": "#FCA5A5"}
        return {"fg_color": "#3F3F46", "text_color": "#A1A1AA"}
        
    def update_tracker_table(self):
        try:
            conn = sqlite3.connect('trades.db')
            c = conn.cursor()
            c.execute("SELECT magic_number, symbol, trade_1_ticket, trade_2_ticket, recovery_ticket, status FROM trade_groups WHERE status != 'CANCELLED' ORDER BY symbol ASC, magic_number DESC LIMIT 100")
            rows = c.fetchall()
            conn.close()
            
            current_hash = hash(str(rows))
            if current_hash == self.last_table_hash:
                self.after(3000, self.update_tracker_table)
                return
            self.last_table_hash = current_hash
            
            for widget in self.table_scroll.winfo_children():
                widget.destroy()
                
            symbols = {}
            for r in rows:
                magic, symbol, t1, t2, rec, status = r
                if symbol not in symbols:
                    symbols[symbol] = []
                symbols[symbol].append(r)
                
            row_idx = 0
            
            def create_row(texts, is_symbol_header=False, badge_col=None, badge_colors=None):
                nonlocal row_idx
                bg_color = "#1a1a1a" if is_symbol_header else ("#2b2b2b" if row_idx % 2 == 0 else "#242424")
                
                row_f = ctk.CTkFrame(self.table_scroll, fg_color="#333333", corner_radius=0)
                row_f.pack(fill="x", anchor="w", pady=(0, 1))
                
                for i, (txt, w) in enumerate(zip(texts, self.col_widths)):
                    row_f.grid_columnconfigure(i, minsize=w, weight=1)
                    
                    anchor = "w" if i in (0, 3) else "center"
                    pad_x = (0, 1) if i < 3 else (0, 0)
                    
                    cell_f = ctk.CTkFrame(row_f, fg_color=bg_color, corner_radius=0)
                    cell_f.grid(row=0, column=i, padx=pad_x, sticky="nsew")
                    
                    if i == badge_col and badge_colors:
                        lbl = ctk.CTkLabel(cell_f, text=f"  {txt}  ", corner_radius=4, **badge_colors, height=22, font=ctk.CTkFont(size=11, weight="bold"))
                        lbl.pack(anchor=anchor, padx=10, pady=5)
                    else:
                        font = ctk.CTkFont(weight="bold", size=12) if is_symbol_header else ctk.CTkFont(size=12)
                        lbl = ctk.CTkLabel(cell_f, text=txt, anchor=anchor, font=font, text_color="#ffffff" if is_symbol_header else "#d1d5db")
                        lbl.pack(fill="both", expand=True, padx=10, pady=5)
                
                row_idx += 1

            for sym, groups in symbols.items():
                create_row([f"\u25bc {sym}", "", "", ""], is_symbol_header=True)
                
                for g in groups:
                    magic, _, t1, t2, rec, status = g
                    
                    g_colors = self.get_badge_colors(status)
                    create_row([f"   Magic: {magic}", "", "Group", status], badge_col=3, badge_colors=g_colors)
                    
                    t1_val = str(t1) if t1 else "N/A"
                    t1_colors = self.get_badge_colors(status)
                    create_row([f"      \u21b3 Orig 1", t1_val, "Original (TP1)", status], badge_col=3, badge_colors=t1_colors)
                    
                    if t2:
                        t2_val = str(t2)
                        create_row([f"      \u21b3 Orig 2", t2_val, "Original (TP2)", status], badge_col=3, badge_colors=t1_colors)
                        
                    rec_val = str(rec) if rec else "N/A"
                    rec_status = "PENDING_ORIGINAL" if not rec and status == "PENDING_ORIGINAL" else status
                    if status == "SUCCESS_TP1_HIT": rec_status = "CANCELLED"
                    elif status == "RECOVERY_TRIGGERED": rec_status = "ACTIVE"
                    elif status == "CANCELLED": rec_status = "CANCELLED"
                    elif rec: rec_status = "PENDING (Placed)" if status == "ACTIVE" else status
                    
                    rec_colors = self.get_badge_colors(rec_status)
                    create_row([f"      \u21b3 Recovery", rec_val, "Recovery", rec_status], badge_col=3, badge_colors=rec_colors)
                    
        except Exception:
            pass
            
        self.after(3000, self.update_tracker_table)
            
    def show_trade_popup(self, data):
        winsound.PlaySound("SystemExclamation", winsound.SND_ALIAS | winsound.SND_ASYNC)
        
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
        tick = mt5.symbol_info_tick(symbol)
        actual_entry = entry if entry > 0 else (tick.ask if action == "BUY" else tick.bid)
        
        rec_action = "SELL" if action == "BUY" else "BUY"
        rec_entry = sl
        rec_sl = actual_entry
        r_amount = abs(rec_entry - rec_sl)
        
        if rec_action == "BUY":
            rec_tp = rec_entry + (r_amount * 0.5)
        else:
            rec_tp = rec_entry - (r_amount * 0.5)
            
        rec_volume = calculate_volume(symbol, rec_entry, rec_sl, risk_usd)
            
        logging.info(f"Signal received for {symbol}. Waiting for confirmation...")
        
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
        
        # Popup Window
        popup = ctk.CTkToplevel(self)
        popup.title("TRADE CONFIRMATION")
        popup.geometry("400x420")
        popup.attributes("-topmost", True)
        popup.grab_set() # Force focus
        
        # Style based on action
        action_color = "#2ecc71" if action == "BUY" else "#e74c3c"
        
        title = ctk.CTkLabel(popup, text="NEW TRADINGVIEW SIGNAL", font=ctk.CTkFont(size=18, weight="bold"))
        title.pack(pady=10)
        
        action_lbl = ctk.CTkLabel(popup, text=f"{action} {symbol}", font=ctk.CTkFont(size=22, weight="bold"), text_color=action_color)
        action_lbl.pack()
        
        # Details Grid
        info_frame = ctk.CTkFrame(popup)
        info_frame.pack(fill="x", padx=20, pady=10)
        
        def add_row(parent, label, value):
            frame = ctk.CTkFrame(parent, fg_color="transparent")
            frame.pack(fill="x", padx=10, pady=4)
            ctk.CTkLabel(frame, text=label, font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
            ctk.CTkLabel(frame, text=str(value), font=ctk.CTkFont(size=13)).pack(side="right")
            
        add_row(info_frame, "Entry Level:", f"{entry} (Limit/Stop)" if entry > 0 else "Market")
        add_row(info_frame, "Stop Loss:", sl)
        add_row(info_frame, "Take Profit 1:", tp1)
        if tp2 != 0: add_row(info_frame, "Take Profit 2:", tp2)
        add_row(info_frame, "Risk Amount:", f"${risk_usd}")
        add_row(info_frame, "Total Lot Size:", f"{calculated_volume} Lots")
        add_row(info_frame, "Recovery Trade:", f"{rec_action} @ {rec_entry} (Vol: {rec_volume})")
        
        if split_trade:
            split_lbl = ctk.CTkLabel(popup, text=f"Will execute TWO trades:\nTrade 1: {vol1} Lots (TP1)  |  Trade 2: {vol2} Lots (TP2)", text_color="#f39c12", font=ctk.CTkFont(size=12, weight="bold"))
            split_lbl.pack(pady=5)
        else:
            split_lbl = ctk.CTkLabel(popup, text=f"Will execute ONE trade (TP1 only)\nReason: {split_reason}", text_color="#f39c12", font=ctk.CTkFont(size=12, weight="bold"))
            split_lbl.pack(pady=5)
            
        # Buttons
        btn_frame = ctk.CTkFrame(popup, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=10)
        
        def on_execute():
            logging.info("User clicked EXECUTE.")
            popup.destroy()
            
            magic_number = random.randint(100000, 999999)
            t1_ticket = None
            t2_ticket = None
            rec_ticket = None
            
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
                
        def on_abort():
            logging.info("User clicked ABORT.")
            popup.destroy()
            
        btn_exec = ctk.CTkButton(btn_frame, text="EXECUTE TRADE", height=40, fg_color="#2ecc71", hover_color="#27ae60", font=ctk.CTkFont(size=14, weight="bold"), command=on_execute)
        btn_exec.pack(side="left", expand=True, padx=5, fill="x")
        
        btn_abort = ctk.CTkButton(btn_frame, text="ABORT", height=40, fg_color="#e74c3c", hover_color="#c0392b", font=ctk.CTkFont(size=14, weight="bold"), command=on_abort)
        btn_abort.pack(side="right", expand=True, padx=5, fill="x")

if __name__ == "__main__":
    app = App()
    app.mainloop()
