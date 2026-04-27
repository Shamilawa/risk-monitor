//+------------------------------------------------------------------+
//|                                           TV_Manual_Confirm.mq5 |
//|                                  Copyright 2024, TradingView HUD |
//|                                             https://www.mql5.com |
//+------------------------------------------------------------------+
#property copyright "Copyright 2024, TradingView HUD"
#property link      "https://www.mql5.com"
#property version   "1.08"
#property strict

#include <Trade\Trade.mqh>
#include <Controls\Edit.mqh>
#include <Controls\Button.mqh>

// --- Global Objects ---
CTrade trade;
CEdit  input_box;
CEdit  risk_cash_box;
CButton execute_btn;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   input_box.Create(0, "CSVInput", 0, 20, 50, 550, 100);
   input_box.Text("");

   risk_cash_box.Create(0, "RiskCash", 0, 20, 110, 550, 140);
   risk_cash_box.Text("");

   execute_btn.Create(0, "ExecBtn", 0, 20, 150, 550, 190);
   execute_btn.Text("PLACE PENDING ORDERS (CSV)");
   execute_btn.ColorBackground(clrGreen);
   
   ChartRedraw();
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   ObjectDelete(0, "CSVInput");
   ObjectDelete(0, "RiskCash");
   ObjectDelete(0, "ExecBtn");
}

//+------------------------------------------------------------------+
//| ChartEvent function                                              |
//+------------------------------------------------------------------+
void OnChartEvent(const int id, const long &lparam, const double &dparam, const string &sparam)
{
   if(id == CHARTEVENT_OBJECT_CLICK && sparam == "ExecBtn")
   {
      string raw_text = input_box.Text();
      ProcessTrade(raw_text);
   }
}

//+------------------------------------------------------------------+
//| Process CSV and Execute Trade                                    |
//+------------------------------------------------------------------+
void ProcessTrade(string raw_data)
{
   // 1. CLEAN THE DATA (Remove timestamp if present)
   // We look for "buy," or "sell,"
   int start = StringFind(raw_data, "buy,");
   if(start == -1) start = StringFind(raw_data, "sell,");
   
   if(start == -1) { Alert("Error: Invalid data. Expected 'buy,' or 'sell,'"); return; }
   string data = StringSubstr(raw_data, start);

   // 2. Split CSV
   string parts[];
   int count = StringSplit(data, ',', parts);
   
   if(count < 7)
   { 
      Alert("Error: Data truncated or invalid. Please check the logs."); 
      return; 
   }

   string action = parts[0];
   string symbol = parts[1];
   double entry_p = StringToDouble(parts[2]);
   double risk_p  = StringToDouble(parts[3]);
   double sl      = StringToDouble(parts[4]);
   double tp1     = StringToDouble(parts[5]);
   double tp2     = StringToDouble(parts[6]);

   // 3. Prep Symbol
   if(!SymbolInfoInteger(symbol, SYMBOL_SELECT))
      SymbolSelect(symbol, true);

   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   double current_ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
   double current_bid = SymbolInfoDouble(symbol, SYMBOL_BID);
   
   entry_p = NormalizeDouble(entry_p, digits);
   sl      = NormalizeDouble(sl, digits);
   tp1     = NormalizeDouble(tp1, digits);
   tp2     = NormalizeDouble(tp2, digits);

   // 4. Risk & Lot Calc
   double risk_amt = 0;
   double cash_override = StringToDouble(risk_cash_box.Text());
   if(cash_override > 0)
      risk_amt = cash_override;
   else
      risk_amt = AccountInfoDouble(ACCOUNT_BALANCE) * (risk_p / 100.0);

   double sl_dist = MathAbs(entry_p - sl);
   double tick_val = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_size = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
   double lot = risk_amt / ( (sl_dist / tick_size) * tick_val );
   
   double step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   lot = MathFloor(lot / step) * step;
   if(lot < SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN)) lot = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);

   // 5. Determine Specific Order Logic
   bool is_buy = (action == "buy");

   // Confirmation Message
   string msg = StringFormat("Place 2 %s Orders on %s?\n\nEntry: %0.5f\nLot: %0.2f each\nSL: %0.5f\nTP1: %0.5f\nTP2: %0.5f", 
                             is_buy ? "BUY" : "SELL", symbol, entry_p, lot, sl, tp1, tp2);
                             
   if(MessageBox(msg, "Confirm Pending Orders", MB_YESNO | MB_ICONQUESTION) == IDYES)
   {
      PlaceOrder(symbol, is_buy, entry_p, current_ask, current_bid, lot, sl, tp1, "TV_TP1");
      PlaceOrder(symbol, is_buy, entry_p, current_ask, current_bid, lot, sl, tp2, "TV_TP2");
      
      input_box.Text(""); 
      risk_cash_box.Text("");
   }
}

// --- Helper to place correct pending order type ---
void PlaceOrder(string sym, bool is_buy, double entry, double ask, double bid, double lot, double sl, double tp, string comment)
{
   if(is_buy)
   {
      if(entry > ask) trade.BuyStop(lot, entry, sym, sl, tp, ORDER_TIME_GTC, 0, comment);
      else trade.BuyLimit(lot, entry, sym, sl, tp, ORDER_TIME_GTC, 0, comment);
   }
   else
   {
      if(entry < bid) trade.SellStop(lot, entry, sym, sl, tp, ORDER_TIME_GTC, 0, comment);
      else trade.SellLimit(lot, entry, sym, sl, tp, ORDER_TIME_GTC, 0, comment);
   }
}
