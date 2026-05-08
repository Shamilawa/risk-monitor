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

def execute_trade(symbol, action_type, sl, tp, volume, entry_price):
    if not mt5.initialize():
        logging.error(f"MT5 initialization failed: {mt5.last_error()}")
        return False
        
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        logging.error(f"Failed to get tick for {symbol}")
        return False

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
        return False
        
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
        "magic": 999111,
        "comment": "TradingView Signal",
        "type_time": mt5.ORDER_TIME_GTC,
    }
    
    if not is_pending:
        request["type_filling"] = mt5.ORDER_FILLING_IOC
        
    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logging.error(f"Order failed, retcode={result.retcode}")
        logging.error(f"Error Description: {result.comment}")
        return False
        
    logging.info(f"Trade Executed Successfully! Ticket: {result.order}")
    return True

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
        self.geometry("750x550")
        
        # Grid Layout
        self.grid_rowconfigure(2, weight=1)
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
        
        # Logs View
        self.log_frame = ctk.CTkFrame(self)
        self.log_frame.grid(row=2, column=0, padx=20, pady=(0, 20), sticky="nsew")
        
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
        
        # Test Telegram Connection
        send_telegram_message("✅ MT5 Bridge GUI Started & Telegram Connected!")
        
        # Setup Ngrok
        self.ngrok_process = None
        self.start_ngrok()
        
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Start checking queue
        self.check_queue()

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
            if split_trade:
                execute_trade(symbol, action, sl, tp1, vol1, entry)
                execute_trade(symbol, action, sl, tp2, vol2, entry)
            else:
                execute_trade(symbol, action, sl, tp1, calculated_volume, entry)
                
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
