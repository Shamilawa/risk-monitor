//+------------------------------------------------------------------+
//|                                           TV_Manual_Confirm.mq5 |
//|                                  Copyright 2024, TradingView HUD |
//|                                             https://www.mql5.com |
//+------------------------------------------------------------------+
#property copyright "Copyright 2024, TradingView HUD"
#property link      "https://www.mql5.com"
#property version   "2.03"
#property strict

#include <Trade\Trade.mqh>

// --- UI Settings ---
int      panel_x = 100;
int      panel_y = 100;
int      panel_w = 260;
int      panel_h = 200;
color    panel_bg = clrWhiteSmoke;
color    header_bg = clrDodgerBlue;

// --- Global Variables ---
CTrade   trade;
bool     is_dragging = false;
int      drag_offset_x = 0;
int      drag_offset_y = 0;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   CreatePanel();
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   DeletePanel();
}

//+------------------------------------------------------------------+
//| ChartEvent function                                              |
//+------------------------------------------------------------------+
void OnChartEvent(const int id, const long &lparam, const double &dparam, const string &sparam)
{
   // 1. Handle Execution Click
   if(id == CHARTEVENT_OBJECT_CLICK && sparam == "TV_BtnExec")
   {
      OnExecuteClick();
   }

   // 2. Handle Drag and Drop
   if(id == CHARTEVENT_MOUSE_MOVE)
   {
      int x = (int)lparam;
      int y = (int)dparam;
      int state = (int)sparam;

      // Click on Header (top 25 pixels) to Start Drag
      if(state == 1) // Mouse button down
      {
         if(x >= panel_x && x <= panel_x + panel_w && y >= panel_y && y <= panel_y + 25)
         {
            if(!is_dragging)
            {
               is_dragging = true;
               drag_offset_x = x - panel_x;
               drag_offset_y = y - panel_y;
            }
         }
      }
      else // Mouse button up
      {
         is_dragging = false;
      }

      // Move Panel if dragging
      if(is_dragging)
      {
         panel_x = x - drag_offset_x;
         panel_y = y - drag_offset_y;
         UpdatePanelPosition();
      }
   }
}

//+------------------------------------------------------------------+
//| Create UI Components                                             |
//+------------------------------------------------------------------+
void CreatePanel()
{
   // Background
   CreateRect("TV_BG", panel_x, panel_y, panel_w, panel_h, panel_bg, clrGray);
   // Header
   CreateRect("TV_Header", panel_x, panel_y, panel_w, 25, header_bg, header_bg);
   CreateLabel("TV_Title", panel_x+10, panel_y+5, "TV Manual Execution", clrWhite, 9);
   
   // Inputs
   CreateLabel("TV_LblCSV", panel_x+10, panel_y+35, "Paste CSV Data:", clrBlack, 8);
   CreateEdit("TV_EditCSV", panel_x+10, panel_y+50, 240, 40, "");
   
   // Load persisted risk from terminal memory
   string saved_risk = DoubleToString(GlobalVariableGet("TV_LastRisk"), 2);
   if(StringToDouble(saved_risk) <= 0) saved_risk = "";

   CreateLabel("TV_LblCash", panel_x+10, panel_y+100, "Cash Risk ($ MANDATORY):", clrRed, 8);
   CreateEdit("TV_EditCash", panel_x+10, panel_y+115, 240, 25, saved_risk);
   
   // Button
   CreateButton("TV_BtnExec", panel_x+10, panel_y+155, 240, 35, "PLACE 2 ORDERS", clrGreen);
   
   ChartRedraw();
}

void UpdatePanelPosition()
{
   ObjectSetInteger(0, "TV_BG", OBJPROP_XDISTANCE, panel_x);
   ObjectSetInteger(0, "TV_BG", OBJPROP_YDISTANCE, panel_y);
   ObjectSetInteger(0, "TV_Header", OBJPROP_XDISTANCE, panel_x);
   ObjectSetInteger(0, "TV_Header", OBJPROP_YDISTANCE, panel_y);
   ObjectSetInteger(0, "TV_Title", OBJPROP_XDISTANCE, panel_x+10);
   ObjectSetInteger(0, "TV_Title", OBJPROP_YDISTANCE, panel_y+5);
   ObjectSetInteger(0, "TV_LblCSV", OBJPROP_XDISTANCE, panel_x+10);
   ObjectSetInteger(0, "TV_LblCSV", OBJPROP_YDISTANCE, panel_y+35);
   ObjectSetInteger(0, "TV_EditCSV", OBJPROP_XDISTANCE, panel_x+10);
   ObjectSetInteger(0, "TV_EditCSV", OBJPROP_YDISTANCE, panel_y+50);
   ObjectSetInteger(0, "TV_LblCash", OBJPROP_XDISTANCE, panel_x+10);
   ObjectSetInteger(0, "TV_LblCash", OBJPROP_YDISTANCE, panel_y+100);
   ObjectSetInteger(0, "TV_EditCash", OBJPROP_XDISTANCE, panel_x+10);
   ObjectSetInteger(0, "TV_EditCash", OBJPROP_YDISTANCE, panel_y+115);
   ObjectSetInteger(0, "TV_BtnExec", OBJPROP_XDISTANCE, panel_x+10);
   ObjectSetInteger(0, "TV_BtnExec", OBJPROP_YDISTANCE, panel_y+155);
   ChartRedraw();
}

void DeletePanel()
{
   ObjectsDeleteAll(0, "TV_");
   ChartRedraw();
}

// --- Logic Implementation ---
void OnExecuteClick()
{
   string raw_data = ObjectGetString(0, "TV_EditCSV", OBJPROP_TEXT);
   
   int start = StringFind(raw_data, "buy,");
   if(start == -1) start = StringFind(raw_data, "sell,");
   if(start == -1) { Alert("Error: Invalid CSV. Copy the full line."); return; }
   
   string data = StringSubstr(raw_data, start);
   string parts[];
   int count = StringSplit(data, ',', parts);
   
   if(count < 7) { Alert("Error: Incomplete Data."); return; }

   string action  = parts[0];
   string symbol  = parts[1];
   double entry_p = StringToDouble(parts[2]);
   double risk_p  = StringToDouble(parts[3]);
   double sl      = StringToDouble(parts[4]);
   double tp1     = StringToDouble(parts[5]);
   double tp2     = StringToDouble(parts[6]);

   if(!SymbolInfoInteger(symbol, SYMBOL_SELECT)) SymbolSelect(symbol, true);
   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   
   entry_p = NormalizeDouble(entry_p, digits);
   sl      = NormalizeDouble(sl, digits);
   tp1     = NormalizeDouble(tp1, digits);
   tp2     = NormalizeDouble(tp2, digits);

   double risk_amt = StringToDouble(ObjectGetString(0, "TV_EditCash", OBJPROP_TEXT));
   if(risk_amt <= 0)
   {
      Alert("Error: You MUST enter a Cash Risk amount ($)!");
      return;
   }

   double sl_dist = MathAbs(entry_p - sl);
   double tick_val = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_size = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
   double lot = risk_amt / ( (sl_dist / tick_size) * tick_val );
   
   double step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   lot = MathFloor(lot / step) * step;
   if(lot < SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN)) lot = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);

   string msg = StringFormat("Place 2 Orders on %s?\n\nEntry: %0.5f\nLot: %0.2f\nSL: %0.5f\nTP1: %0.5f\nTP2: %0.5f", 
                             symbol, entry_p, lot, sl, tp1, tp2);
                             
   if(MessageBox(msg, "Confirm Pending Orders", MB_YESNO | MB_ICONQUESTION) == IDYES)
   {
      double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
      double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
      PlaceOrder(symbol, (action == "buy"), entry_p, ask, bid, lot, sl, tp1, "TV_TP1");
      PlaceOrder(symbol, (action == "buy"), entry_p, ask, bid, lot, sl, tp2, "TV_TP2");
      // Persist the risk value to terminal memory
      GlobalVariableSet("TV_LastRisk", risk_amt);
      
      // Clear ONLY the CSV box, keep the Cash Risk box as is
      ObjectSetString(0, "TV_EditCSV", OBJPROP_TEXT, "");
   }
}

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

// --- Helper Functions ---
void CreateRect(string name, int x, int y, int w, int h, color bg, color border)
{
   ObjectCreate(0, name, OBJ_RECTANGLE_LABEL, 0, 0, 0);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, name, OBJPROP_XSIZE, w);
   ObjectSetInteger(0, name, OBJPROP_YSIZE, h);
   ObjectSetInteger(0, name, OBJPROP_BGCOLOR, bg);
   ObjectSetInteger(0, name, OBJPROP_BORDER_TYPE, BORDER_FLAT);
   ObjectSetInteger(0, name, OBJPROP_COLOR, border);
   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
}

void CreateLabel(string name, int x, int y, string txt, color c, int size)
{
   ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetString(0, name, OBJPROP_TEXT, txt);
   ObjectSetInteger(0, name, OBJPROP_COLOR, c);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, size);
   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
}

void CreateEdit(string name, int x, int y, int w, int h, string txt)
{
   ObjectCreate(0, name, OBJ_EDIT, 0, 0, 0);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, name, OBJPROP_XSIZE, w);
   ObjectSetInteger(0, name, OBJPROP_YSIZE, h);
   ObjectSetString(0, name, OBJPROP_TEXT, txt);
   ObjectSetInteger(0, name, OBJPROP_BGCOLOR, clrWhite);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clrBlack);
   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_ALIGN, ALIGN_LEFT);
}

void CreateButton(string name, int x, int y, int w, int h, string txt, color bg)
{
   ObjectCreate(0, name, OBJ_BUTTON, 0, 0, 0);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, name, OBJPROP_XSIZE, w);
   ObjectSetInteger(0, name, OBJPROP_YSIZE, h);
   ObjectSetString(0, name, OBJPROP_TEXT, txt);
   ObjectSetInteger(0, name, OBJPROP_BGCOLOR, bg);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clrWhite);
   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
}
