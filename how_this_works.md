# How This System Works

This document explains the underlying mechanics of the TradingView to MT5 bridge. The system is designed to give you the speed of algorithmic trading while retaining the safety of manual confirmation. It supports two distinct workflows: **Semi-Automated** and **Fully Manual**.

---

## 🤖 The Semi-Automated Process (Webhook Route)

This is the primary workflow. It connects TradingView directly to your MT5 terminal so you don't have to manually type in Entry, Stop Loss, or Take Profit numbers.

### The Workflow:
1. **Signal Generation:** Your custom Pine Script indicator runs on TradingView servers. When all conditions are met and the candle closes, it generates a Buy or Sell signal.
2. **JSON Payload:** The indicator packages the trade data (Direction, Symbol, Entry Price, Stop Loss, Take Profit, and Risk Amount $) into a lightweight JSON format.
3. **The Webhook:** TradingView instantly fires an HTTP POST request containing this JSON to your public Ngrok URL.
4. **The Local Bridge:** Ngrok securely forwards this request to your computer, where the local Python Flask server (`app.py`) is listening.
5. **Dynamic Lot Sizing (Smart Calculation):** The Python script instantly connects to your MT5 terminal in the background. It reads the current tick size and tick value for the specific currency pair. It calculates exactly how many points away your Stop Loss is, and uses your `$ Risk Amount` to mathematically determine the exact **Lot Size** required.
6. **Human-in-the-Loop Confirmation:** Before any money is risked, the Python script triggers a native Windows MessageBox that interrupts your screen. It displays all the calculated details.
7. **Execution:** 
   - If you click **Yes**, the script uses the official MetaQuotes `MetaTrader5` library to instantly send the Market Order.
   - If you click **No**, the signal is logged and safely discarded.

---

## ✍️ The Manual Process (Copy-Paste Route)

Sometimes you might be trading on a different computer, your local Python server might be off, or you just prefer to execute trades manually. The indicator is built to handle this seamlessly.

### The Workflow:
1. **Enable CSV Labels:** In the TradingView indicator settings, check the box for **"Copy Mode: Show CSV on Labels"**.
2. **Visual Signal:** When a signal occurs, instead of showing a generic text like "FLOW" or "VALUE", the chart label will display a raw, comma-separated string.
   *Example:* `buy,EURUSD,1.05000,100.0,1.04500,1.05500,1.06000`
3. **Copy the Data:** Double-click the label (or right-click -> Settings -> Text) to highlight and copy the exact string.
4. **Manual Execution:** You can now read the exact entry, stop loss, and take profit levels to type them into MT5 manually on your phone, or paste the CSV string into an EA or third-party copier if you use one.

*Note: Even when the labels are showing the CSV string, the indicator will still send the JSON Webhook in the background. They operate independently so you always have both options available!*

---

## 🛡️ Why This Architecture?

1. **Security:** By running the Python server locally on your own machine, your MT5 credentials and trade execution are never exposed to a third-party server.
2. **Dynamic Risk Management:** TradingView doesn't know the tick value of your MT5 broker. By passing the calculation to Python, the system ensures your risk is exactly $100 (or whatever you set), regardless of the currency pair you are trading.
3. **No Phantom Trades:** The script is hardcoded to only alert on `barstate.isconfirmed`. This prevents "repainting" where a signal flashes intra-bar and disappears, ensuring you only ever take valid, confirmed setups.
