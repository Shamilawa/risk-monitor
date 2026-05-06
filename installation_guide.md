# TradingView to MT5 Bridge - Installation & Setup Guide

This guide will walk you through setting up the end-to-end automated trading bridge between TradingView and MetaTrader 5 (MT5). 

The system uses a **Local Python Server** to receive webhooks from TradingView, dynamically calculate lot sizes based on your risk tolerance, and present a manual confirmation popup before executing trades in MT5.

---

## ⚡ Quick Start Guide (For Experienced Users)
1. **Install Dependencies:** `pip install flask MetaTrader5`
2. **Enable MT5 Algo:** Go to MT5 Tools -> Options -> Expert Advisors -> check `Allow algorithmic trading`.
3. **Start Bridge:** Double-click `mt5_bridge/run.bat`.
4. **Start Ngrok:** Run `ngrok http 5000` in a terminal and copy the HTTPS Forwarding URL.
5. **TradingView Alert:** Paste the Ngrok URL into your alert's Webhook field and append `/webhook` (e.g., `https://xxxx.ngrok.app/webhook`).

---

## 📋 Prerequisites
1. **TradingView:** A paid TradingView account (Essential, Plus, or Premium) is required to use the Webhook alerts feature.
2. **MetaTrader 5:** Installed on your Windows PC and logged into your broker account.
3. **Python:** Installed on your Windows PC (Version 3.8 or higher recommended).
4. **Ngrok:** A free account at [ngrok.com](https://ngrok.com/) to expose your local server to the internet.

---

## 🛠️ Step 1: Python & Server Setup
1. **Install Python:** Download and install Python from `python.org`. **IMPORTANT:** During installation, make sure to check the box that says **"Add Python to PATH"**.
2. **Install Libraries:** Open a Command Prompt (Terminal) and run the following command to install the required libraries:
   ```cmd
   pip install flask MetaTrader5
   ```
3. **Verify Files:** Ensure the `mt5_bridge` folder is downloaded to your computer and contains the `app.py` and `run.bat` files.

---

## 📈 Step 2: MetaTrader 5 Setup
Your Python script needs permission to send trades to your MT5 terminal.
1. Open MetaTrader 5.
2. Go to the top menu and click **Tools** -> **Options** (or press `Ctrl+O`).
3. Navigate to the **Expert Advisors** tab.
4. Check the box for **"Allow algorithmic trading"**.
5. Click **OK**.
6. Ensure that the symbols you want to trade (e.g., `EURUSD`) are visible in the "Market Watch" window on the left side of MT5.

---

## 🚀 Step 3: Start the Local Bridge Server
1. Navigate to the `mt5_bridge` folder on your computer.
2. Double-click the **`run.bat`** file.
3. A command prompt window will open displaying:
   `Starting MT5 Bridge Server on port 5000...`
   `Waiting for TradingView webhooks...`
4. **Keep this window open** while you are trading. If you close it, the bridge will stop working.

---

## 🌐 Step 4: Expose Server to the Internet (Ngrok)
TradingView exists in the cloud, so it needs a public URL to send the alert to. Ngrok provides a temporary public URL that connects directly to your local server.
1. Download the Ngrok executable from their website.
2. Authenticate your Ngrok account by running the auth token command provided in your Ngrok dashboard (you only have to do this once).
3. Open a new Command Prompt and start the tunnel by running:
   ```cmd
   ngrok http 5000
   ```
4. Ngrok will start and display a **Forwarding URL** (e.g., `https://a1b2c3d4.ngrok-free.app`). 
5. **Copy this URL**. Keep the Ngrok window open.

*Note: With a free Ngrok account, this URL will change every time you restart Ngrok. You will need to update TradingView with the new URL whenever you restart your computer.*

---

## 📊 Step 5: TradingView Setup
1. **Add Indicator:** Open TradingView and add the custom `indicator.pine` script to your chart.
2. **Configure Settings:** 
   - Open the indicator settings.
   - Under "Automation / Webhooks", set your **MT5 Symbol Name** exactly as it appears in MT5 (e.g., if MT5 shows `EURUSD.m`, enter `EURUSD.m` instead of `{{ticker}}`).
   - Set your **Risk Amount ($)**.
3. **Create the Alert:**
   - Click the "Alerts" clock icon on the right sidebar.
   - **Condition:** Select the Indicator Name.
   - **Crucial Step:** Select **"Any alert() function call"** from the secondary dropdown.
   - **Notifications:** Check the **Webhook URL** box.
   - **Webhook URL:** Paste the Ngrok URL you copied in Step 4, and add `/webhook` to the very end of it. 
     *(Example: `https://a1b2c3d4.ngrok-free.app/webhook`)*
   - Click **Create**.

---

## 🧪 Step 6: Testing the Workflow
1. Wait for a signal to trigger and the candle to close (or create a fast-moving dummy alert for testing).
2. When the alert fires, TradingView sends the JSON data to your Ngrok URL.
3. Your local Python script receives it and pauses.
4. A **Windows MessageBox** will pop up on your screen detailing the Trade Direction, Symbol, SL, TP, and the dynamically calculated Lot Size.
5. Click **Yes** to instantly place the trade in MT5, or **No** to abort. 

**Congratulations! Your semi-automated trading bridge is now fully operational.**
