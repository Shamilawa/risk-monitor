import time
from flask import Flask, request, jsonify
import MetaTrader5 as mt5
import ctypes
import threading
import winsound
import logging
import os
import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
# Disable Flask noisy logs
log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)

app = Flask(__name__)

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

def show_confirmation(title, message):
    """
    Shows a native Windows Yes/No dialog that stays on top of all other windows.
    Returns True if YES was clicked, False otherwise.
    """
    # Play a loud system alert sound
    winsound.PlaySound("SystemExclamation", winsound.SND_ALIAS | winsound.SND_ASYNC)
    
    # 4 = MB_YESNO, 32 = MB_ICONQUESTION, 4096 = MB_SYSTEMMODAL (stays on top)
    result = ctypes.windll.user32.MessageBoxW(0, message, title, 4 | 32 | 4096)
    return result == 6 # 6 is IDYES

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

def execute_trade(symbol, action_type, sl, tp, volume, entry_price):
    """
    Connects to MT5 and executes the trade (Market or Pending).
    """
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

    # Prepare the order request
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
    
    # Market orders usually require type_filling depending on broker
    if not is_pending:
        request["type_filling"] = mt5.ORDER_FILLING_IOC
    
    # Send the order to MT5
    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logging.error(f"Order failed, retcode={result.retcode}")
        # Dictionary of common MT5 error codes
        logging.error(f"Error Description: {result.comment}")
        return False
        
    logging.info(f"Trade Executed Successfully! Ticket: {result.order}")
    return True

def handle_signal_in_background(data):
    """
    Handles the popup and execution in a separate thread so we don't block the Flask webhook response.
    TradingView requires a quick 200 OK response.
    """
    try:
        # Extract data from the JSON payload
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
        
        # Calculate Lot Size Dynamically
        calculated_volume = calculate_volume(symbol, entry, sl, risk_usd)
        
        # Determine if we should split the trade into two targets
        symbol_info = mt5.symbol_info(symbol)
        step = symbol_info.volume_step if symbol_info else 0.01
        min_vol = symbol_info.volume_min if symbol_info else 0.01
        
        # Try to split volume evenly
        vol1 = round((calculated_volume / 2) / step) * step
        vol2 = calculated_volume - vol1
        
        # Fix floating point precision
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
        
        # Prepare the message for the user
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
        
        logging.info(f"Signal received for {symbol}. Waiting for user confirmation...")
        
        # Send Telegram Notification
        send_telegram_message(msg)
        
        # Show Popup
        if show_confirmation("MT5 Trade Confirmation", msg):
            logging.info("User clicked YES. Executing trade...")
            if split_trade:
                execute_trade(symbol, action, sl, tp1, vol1, entry)
                execute_trade(symbol, action, sl, tp2, vol2, entry)
            else:
                execute_trade(symbol, action, sl, tp1, calculated_volume, entry)
        else:
            logging.info("User clicked NO. Trade aborted.")
            
    except Exception as e:
        logging.error(f"Error processing signal: {e}")

@app.route('/webhook', methods=['POST'])
def webhook():
    """
    Endpoint that TradingView will call.
    """
    # force=True allows Flask to parse JSON even if TradingView sends it as text/plain
    data = request.get_json(force=True)
    logging.info(f"=== RAW JSON RECEIVED FROM TRADINGVIEW ===")
    logging.info(data)
    logging.info(f"==========================================")
    
    if not data:
        return jsonify({"error": "Invalid payload"}), 400
        
    # Start a background thread so the webhook returns 200 OK to TradingView immediately
    thread = threading.Thread(target=handle_signal_in_background, args=(data,))
    thread.start()
    
    return jsonify({"status": "signal received"}), 200

if __name__ == '__main__':
    logging.info("Starting MT5 Bridge Server on port 5000...")
    logging.info("Waiting for TradingView webhooks...")
    send_telegram_message("✅ MT5 Bridge Server Started & Telegram Connected!")
    app.run(host='0.0.0.0', port=5000)
