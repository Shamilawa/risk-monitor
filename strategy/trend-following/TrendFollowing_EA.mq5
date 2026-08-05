//+------------------------------------------------------------------+
//|                                            TrendFollowing_EA.mq5 |
//|  Trend Following - native MT5 port of the Pine Script v6          |
//|  "Pro: Flow & Value Pullback" indicator.                          |
//|  EMA-stack trend-pullback system with double Heikin Ashi trigger. |
//+------------------------------------------------------------------+
#property copyright "Converted from Pine Script v6 indicator"
#property version   "2.00"
#property strict

#include <Trade\Trade.mqh>

//------------------------------------------------------------------
// 1. INPUTS  (mirrors the Pine input groups)
//------------------------------------------------------------------
input group "Strategy Definitions"
input int    InpFastLen         = 21;    // Fast EMA (Flow Zone)
input int    InpSlowLen         = 50;    // Slow EMA (Value Zone)
input int    InpTrendLen        = 200;   // Trend EMA (Trend Filter)
input int    InpSlopeBars       = 5;     // EMA slope lookback (bars)

input group "Filters & Confirmation"
input bool   InpUseDoubleHA     = true;  // Require Double HA Confirmation?

input group "Risk Management"
input double InpRiskUsd         = 100.0; // Risk Amount ($) per signal
input int    InpEntryBufferPips = 5;     // Entry Tolerance (Pips)
input double InpTPRMultiple     = 1.8;   // Take Profit R-multiple

input group "ATR Bands (Stop Loss Source)"
input int    InpAtrPeriodBands  = 14;    // ATR Period (Bands)
input double InpAtrMultBands    = 3.0;   // ATR Band Scale Factor

input group "Visuals / UI"
input bool   InpShowChartObjects = true;   // Draw signals on chart
input string InpTxtA1            = "FLOW";  // Name for A1 Entry (shallow pullback)
input string InpTxtA2            = "VALUE"; // Name for A2 Entry (deep pullback)
input color  InpColEntry         = clrSilver; // Entry Line Color
input color  InpColSL            = clrRed;    // SL Line Color
input color  InpColTP            = clrLime;   // TP Line Color
input int    InpArrowWidth       = 2;      // Signal Arrow Size (1-5)
input bool   InpShowTextLabel    = true;   // Show FLOW/VALUE text next to arrow
input int    InpMaxSignalsOnChart = 500;   // Max signals kept drawn (oldest pruned, matches Pine's max_lines_count)

input group "Execution"
input long   InpMagicNumber      = 990211;
input int    InpSlippagePoints   = 20;
input int    InpPendingExpiryBars = 10;    // Bars before an unfilled limit is cancelled
input double InpInvalidateRMultiple = 1.4; // Cancel unfilled limit once price runs this many R past entry (0 = off)
input string InpTradeComment     = "TF";

//------------------------------------------------------------------
// 2. GLOBALS
//------------------------------------------------------------------
CTrade  trade;

int     hFastEMA, hSlowEMA, hTrendEMA;

datetime g_lastBarTime = 0;

string  g_drawnUids[];              // ring buffer of drawn signal ids, for pruning

// Every processing cycle replays the arm-state (can_take_long/short) across
// this many bars of history, instead of persisting it across calls. That's
// deliberate: a persisted flag starting "true" at EA-attach time would not
// reflect whatever the true lock state actually was mid-trend, and could
// silently diverge from TrendFollowing_Visual.mq5's indicator (which always
// replays its whole loaded chart). A full replay every bar close is cheap
// (a few thousand float ops) and keeps the two files - and the EA's own
// live decisions - consistent with "what really happened."
#define HISTORY_BARS 3000
#define OBJ_PREFIX   "TF_"

//------------------------------------------------------------------
// 3. INIT / DEINIT
//------------------------------------------------------------------
int OnInit()
{
   if(InpFastLen < 1 || InpSlowLen < 1 || InpTrendLen < 1 || InpSlopeBars < 1 ||
      InpAtrPeriodBands < 1 || InpAtrMultBands <= 0)
   {
      Print("TrendFollowing_EA: invalid input(s)");
      return(INIT_PARAMETERS_INCORRECT);
   }

   hFastEMA  = iMA(_Symbol, _Period, InpFastLen,  0, MODE_EMA, PRICE_CLOSE);
   hSlowEMA  = iMA(_Symbol, _Period, InpSlowLen,  0, MODE_EMA, PRICE_CLOSE);
   hTrendEMA = iMA(_Symbol, _Period, InpTrendLen, 0, MODE_EMA, PRICE_CLOSE);

   if(hFastEMA==INVALID_HANDLE || hSlowEMA==INVALID_HANDLE || hTrendEMA==INVALID_HANDLE)
   {
      Print("TrendFollowing_EA: failed to create EMA handle(s)");
      return(INIT_FAILED);
   }

   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetDeviationInPoints(InpSlippagePoints);
   trade.SetTypeFillingBySymbol(_Symbol);

   if(!MQLInfoInteger(MQL_TRADE_ALLOWED))
      Print("TrendFollowing_EA: AutoTrading is OFF (toolbar button and/or this EA's Allow algo trading checkbox) - signals will be detected and drawn but no orders will be sent until it's enabled.");

   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   IndicatorRelease(hFastEMA);
   IndicatorRelease(hSlowEMA);
   IndicatorRelease(hTrendEMA);
   Comment("");

   // Keep drawings across recompiles / parameter changes; only wipe on real removal.
   if(reason==REASON_REMOVE || reason==REASON_CHARTCLOSE || reason==REASON_CLOSE)
      ObjectsDeleteAll(0, OBJ_PREFIX);
}

//------------------------------------------------------------------
// 4. TICK LOOP  (Pine's `barstate.isconfirmed` == act on bar close)
//------------------------------------------------------------------
void OnTick()
{
   // Checked every tick (not gated to bar close) so a fast run-away move gets
   // caught as soon as it crosses the threshold, not up to a bar late.
   CheckPendingInvalidation();

   datetime curBarTime = iTime(_Symbol, _Period, 0);
   if(curBarTime == g_lastBarTime)
      return;
   g_lastBarTime = curBarTime;

   ProcessClosedBar();
}

//------------------------------------------------------------------
// Cancels our own working BUY_LIMIT/SELL_LIMIT orders once price has run
// InpInvalidateRMultiple * R past the entry in the trade's favor without the
// order ever filling. That means the anticipated pullback never happened -
// the move already played out without us, so filling late here would be
// chasing at a much worse risk:reward than the signal was based on. This is
// independent of (and usually fires well before) InpPendingExpiryBars, which
// only catches orders that simply sat there too long, not ones invalidated
// by a fast run-away.
//------------------------------------------------------------------
void CheckPendingInvalidation()
{
   if(InpInvalidateRMultiple <= 0) return;

   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   int    digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);

   for(int i=OrdersTotal()-1; i>=0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket==0) continue;
      if(OrderGetString(ORDER_SYMBOL) != _Symbol) continue;
      if(OrderGetInteger(ORDER_MAGIC) != InpMagicNumber) continue;

      long type = OrderGetInteger(ORDER_TYPE);
      if(type != ORDER_TYPE_BUY_LIMIT && type != ORDER_TYPE_SELL_LIMIT) continue;

      double entry = OrderGetDouble(ORDER_PRICE_OPEN);
      double sl    = OrderGetDouble(ORDER_SL);
      if(entry <= 0 || sl <= 0) continue;

      if(type == ORDER_TYPE_BUY_LIMIT)
      {
         double risk = entry - sl;
         if(risk <= 0) continue;
         double threshold = entry + risk*InpInvalidateRMultiple;
         if(bid >= threshold)
         {
            PrintFormat("TrendFollowing_EA: cancelling stale BUY LIMIT #%d - price reached %.*f, %.2gR past entry %.*f without filling",
                        (int)ticket, digits, bid, InpInvalidateRMultiple, digits, entry);
            trade.OrderDelete(ticket);
         }
      }
      else // ORDER_TYPE_SELL_LIMIT
      {
         double risk = sl - entry;
         if(risk <= 0) continue;
         double threshold = entry - risk*InpInvalidateRMultiple;
         if(ask <= threshold)
         {
            PrintFormat("TrendFollowing_EA: cancelling stale SELL LIMIT #%d - price reached %.*f, %.2gR past entry %.*f without filling",
                        (int)ticket, digits, ask, InpInvalidateRMultiple, digits, entry);
            trade.OrderDelete(ticket);
         }
      }
   }
}

//------------------------------------------------------------------
// 5. HELPERS
//------------------------------------------------------------------
// Pine: entry_buffer_pips * syminfo.mintick * 10  -> one "pip"
double PipSize()
{
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   return (digits==3 || digits==5) ? point*10.0 : point;
}

//------------------------------------------------------------------
// Wilder/RMA-smoothed ATR, matching Pine's ta.atr() (MT5's built-in iATR
// uses a *simple* MA of true range - different result, so this is by hand).
// Ascending arrays (index 0 = oldest) - identical algorithm to the one in
// TrendFollowing_Visual.mq5, so both files compute the exact same ATR for
// the exact same bar. Deliberately duplicated rather than shared via an
// #include: keeps each file drop-in/self-contained for MetaEditor.
//------------------------------------------------------------------
void CalcWilderATR(const double &high[], const double &low[], const double &close[],
                   double &atr[], int total, int period)
{
   ArrayResize(atr, total);
   ArrayInitialize(atr, 0.0);
   if(total < period+1) return;

   double sum = 0;
   for(int k=0; k<period; k++)
   {
      double tr = (k==0) ? (high[k]-low[k])
                         : MathMax(high[k]-low[k],
                           MathMax(MathAbs(high[k]-close[k-1]), MathAbs(low[k]-close[k-1])));
      sum += tr;
   }
   atr[period-1] = sum / period;

   for(int i=period; i<total; i++)
   {
      double tr = MathMax(high[i]-low[i],
                  MathMax(MathAbs(high[i]-close[i-1]), MathAbs(low[i]-close[i-1])));
      atr[i] = (atr[i-1]*(period-1) + tr) / period;
   }
}

//------------------------------------------------------------------
// Heikin Ashi, recomputed forward from raw OHLC (ascending arrays: haOpen[i]
// depends on i-1). Same algorithm as TrendFollowing_Visual.mq5's CalcHA().
//------------------------------------------------------------------
void CalcHeikinAshi(const double &open[], const double &high[], const double &low[],
                    const double &close[], double &haOpen[], double &haClose[], int total)
{
   ArrayResize(haOpen, total);
   ArrayResize(haClose, total);

   for(int i=0; i<total; i++)
   {
      haClose[i] = (open[i]+high[i]+low[i]+close[i]) / 4.0;
      if(i == 0)
         haOpen[i] = (open[i]+close[i]) / 2.0;
      else
         haOpen[i] = (haOpen[i-1]+haClose[i-1]) / 2.0;
   }
}

//------------------------------------------------------------------
// 6. LOT SIZING
//------------------------------------------------------------------
double CalcLotsForRisk(double riskUsd, double slDistance)
{
   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tickSize <= 0 || tickValue <= 0 || slDistance <= 0) return 0;

   double lossPerLot = (slDistance / tickSize) * tickValue;
   if(lossPerLot <= 0) return 0;

   double minLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double step   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(step <= 0) step = minLot;

   double lots = MathFloor((riskUsd/lossPerLot)/step)*step;
   if(lots < minLot) return 0;                 // can't honour the risk cap at min lot
   return MathMin(maxLot, lots);
}

//------------------------------------------------------------------
// 7. POSITION / ORDER GUARDS
//------------------------------------------------------------------
bool HasOpenPosition(bool isLong)
{
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket==0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagicNumber) continue;
      long type = PositionGetInteger(POSITION_TYPE);
      if(isLong  && type==POSITION_TYPE_BUY)  return true;
      if(!isLong && type==POSITION_TYPE_SELL) return true;
   }
   return false;
}

bool HasPendingOrder(bool isLong)
{
   for(int i=OrdersTotal()-1; i>=0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket==0) continue;
      if(OrderGetString(ORDER_SYMBOL) != _Symbol) continue;
      if(OrderGetInteger(ORDER_MAGIC) != InpMagicNumber) continue;
      long type = OrderGetInteger(ORDER_TYPE);
      if(isLong  && type==ORDER_TYPE_BUY_LIMIT)  return true;
      if(!isLong && type==ORDER_TYPE_SELL_LIMIT) return true;
   }
   return false;
}

//------------------------------------------------------------------
// 8. TRADE EXECUTION
//------------------------------------------------------------------
void ExecuteSignal(bool isLong, double entry, double sl, double tp, bool isMarket, string tag)
{
   if(HasOpenPosition(isLong))
   {
      PrintFormat("TrendFollowing_EA: %s %s signal ignored - a %s position (magic %d) is already open on %s",
                  isLong?"BUY":"SELL", tag, isLong?"BUY":"SELL", InpMagicNumber, _Symbol);
      return;
   }
   if(HasPendingOrder(isLong))
   {
      PrintFormat("TrendFollowing_EA: %s %s signal ignored - a %s limit order (magic %d) is already working on %s",
                  isLong?"BUY":"SELL", tag, isLong?"BUY":"SELL", InpMagicNumber, _Symbol);
      return;
   }

   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   entry = NormalizeDouble(entry, digits);
   sl    = NormalizeDouble(sl,    digits);
   tp    = NormalizeDouble(tp,    digits);

   double lots = CalcLotsForRisk(InpRiskUsd, MathAbs(entry - sl));
   if(lots <= 0)
   {
      PrintFormat("TrendFollowing_EA: %s %s skipped - risk $%.2f over a %.*f stop is below min lot",
                  isLong?"BUY":"SELL", tag, InpRiskUsd, digits, MathAbs(entry-sl));
      return;
   }

   datetime expiry = 0;
   if(!isMarket && InpPendingExpiryBars > 0)
      expiry = TimeCurrent() + InpPendingExpiryBars * PeriodSeconds(_Period);

   string cmt = InpTradeComment + "_" + tag;
   bool ok = false;

   if(isLong)
   {
      if(isMarket)
         ok = trade.Buy(lots, _Symbol, 0, sl, tp, cmt);
      else
         ok = trade.BuyLimit(lots, entry, _Symbol, sl, tp,
                             expiry>0?ORDER_TIME_SPECIFIED:ORDER_TIME_GTC, expiry, cmt);
   }
   else
   {
      if(isMarket)
         ok = trade.Sell(lots, _Symbol, 0, sl, tp, cmt);
      else
         ok = trade.SellLimit(lots, entry, _Symbol, sl, tp,
                              expiry>0?ORDER_TIME_SPECIFIED:ORDER_TIME_GTC, expiry, cmt);
   }

   if(!ok)
      PrintFormat("TrendFollowing_EA: %s %s order failed - retcode %d (%s)",
                  isLong?"BUY":"SELL", tag, trade.ResultRetcode(), trade.ResultRetcodeDescription());
}

//------------------------------------------------------------------
// 9. CHART DRAWING  (the MT5 equivalent of the Pine line.new/label.new block)
//------------------------------------------------------------------
void DrawLevelLine(string name, datetime t1, datetime t2, double price, color clr, string tip)
{
   if(!ObjectCreate(0, name, OBJ_TREND, 0, t1, price, t2, price)) return;
   ObjectSetInteger(0, name, OBJPROP_COLOR,     clr);
   ObjectSetInteger(0, name, OBJPROP_STYLE,     STYLE_DASH);
   ObjectSetInteger(0, name, OBJPROP_WIDTH,     1);
   ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, false);
   ObjectSetInteger(0, name, OBJPROP_RAY_LEFT,  false);
   ObjectSetInteger(0, name, OBJPROP_BACK,      true);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE,false);
   ObjectSetString (0, name, OBJPROP_TOOLTIP,   tip);
}

void PruneOldSignals()
{
   while(ArraySize(g_drawnUids) > InpMaxSignalsOnChart && InpMaxSignalsOnChart > 0)
   {
      string uid = g_drawnUids[0];
      ObjectDelete(0, OBJ_PREFIX+"entry_"+uid);
      ObjectDelete(0, OBJ_PREFIX+"sl_"+uid);
      ObjectDelete(0, OBJ_PREFIX+"tp_"+uid);
      ObjectDelete(0, OBJ_PREFIX+"arrow_"+uid);
      ObjectDelete(0, OBJ_PREFIX+"text_"+uid);
      ArrayRemove(g_drawnUids, 0, 1);
   }
}

// Mirrors the Pine label tooltip: SL / TP with their pip distances.
void DrawSignal(bool isLong, datetime barTime, double barLow, double barHigh, double scaledATR,
                double entry, double sl, double tp, double risk, string tag)
{
   int    digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   double pip    = PipSize();
   string uid    = TimeToString(barTime, TIME_DATE|TIME_MINUTES) + "_" + tag;
   StringReplace(uid, " ", "_");

   if(ObjectFind(0, OBJ_PREFIX+"entry_"+uid) >= 0)
      return;                                  // already drawn on a previous recalculation

   double riskPips = (pip>0) ? risk/pip : 0;
   string tip = StringFormat("%s %s\nEntry: %.*f\nSL: %.*f (%.1f pips)\nTP (%.2gR): %.*f (%.1f pips)",
                             isLong?"Buy":"Sell", tag,
                             digits, entry,
                             digits, sl, riskPips,
                             InpTPRMultiple, digits, tp, riskPips*InpTPRMultiple);

   // Pine drew each level 2 bars forward from the signal bar.
   datetime t2 = barTime + 2*PeriodSeconds(_Period);
   DrawLevelLine(OBJ_PREFIX+"entry_"+uid, barTime, t2, entry, InpColEntry, tip);
   DrawLevelLine(OBJ_PREFIX+"sl_"+uid,    barTime, t2, sl,    InpColSL,    tip);
   DrawLevelLine(OBJ_PREFIX+"tp_"+uid,    barTime, t2, tp,    InpColTP,    tip);

   // Arrow sits just off the signal candle, like Pine's label at low / high.
   double gap       = 0.3 * scaledATR;
   string arrowName = OBJ_PREFIX+"arrow_"+uid;
   double arrowPx   = isLong ? (barLow - gap) : (barHigh + gap);
   if(ObjectCreate(0, arrowName, isLong ? OBJ_ARROW_UP : OBJ_ARROW_DOWN, 0, barTime, arrowPx))
   {
      ObjectSetInteger(0, arrowName, OBJPROP_COLOR,      isLong ? clrLime : clrRed);
      ObjectSetInteger(0, arrowName, OBJPROP_WIDTH,      InpArrowWidth);
      ObjectSetInteger(0, arrowName, OBJPROP_ANCHOR,     isLong ? ANCHOR_TOP : ANCHOR_BOTTOM);
      ObjectSetInteger(0, arrowName, OBJPROP_SELECTABLE, false);
      ObjectSetString (0, arrowName, OBJPROP_TOOLTIP,    tip);
   }

   if(InpShowTextLabel)
   {
      string txtName = OBJ_PREFIX+"text_"+uid;
      double txtPx   = isLong ? (barLow - gap*3.0) : (barHigh + gap*3.0);
      if(ObjectCreate(0, txtName, OBJ_TEXT, 0, barTime, txtPx))
      {
         ObjectSetString (0, txtName, OBJPROP_TEXT,       tag);
         ObjectSetString (0, txtName, OBJPROP_FONT,       "Arial Bold");
         ObjectSetInteger(0, txtName, OBJPROP_FONTSIZE,   8);
         ObjectSetInteger(0, txtName, OBJPROP_COLOR,      isLong ? clrLime : clrRed);
         ObjectSetInteger(0, txtName, OBJPROP_ANCHOR,     isLong ? ANCHOR_UPPER : ANCHOR_LOWER);
         ObjectSetInteger(0, txtName, OBJPROP_SELECTABLE, false);
         ObjectSetString (0, txtName, OBJPROP_TOOLTIP,    tip);
      }
   }

   int n = ArraySize(g_drawnUids);
   ArrayResize(g_drawnUids, n+1);
   g_drawnUids[n] = uid;
   PruneOldSignals();
   ChartRedraw(0);
}

// Pine's bottom-right dashboard table.
void UpdateDashboard(bool trendBull, bool ready)
{
   Comment(StringFormat("Trend Following EA\nTrend:  %s\nStatus: %s",
                        trendBull ? "BULLISH" : "BEARISH",
                        ready ? "READY" : "LOCKED"));
}

//------------------------------------------------------------------
// 10. MAIN BAR-CLOSE PROCESSING  (Pine sections 2-4 and 6)
//
// Every call replays the full arm-state (can_take_long/short) across the
// loaded history, exactly like TrendFollowing_Visual.mq5's OnCalculate does,
// then acts (trades + optionally draws) only on the newest confirmed bar.
// Earlier bars in the window only update the running lock state (and, if
// InpShowChartObjects, draw - deduped for free against the indicator via
// the shared OBJ_PREFIX + ObjectFind guard in DrawSignal()).
//------------------------------------------------------------------
void ProcessClosedBar()
{
   int total = MathMin(Bars(_Symbol, _Period), HISTORY_BARS);
   int needed = InpTrendLen + InpSlopeBars + 10;
   if(total < needed)
   {
      PrintFormat("TrendFollowing_EA: only %d bars of history available, need at least %d - waiting for more history to load", total, needed);
      return;
   }

   MqlRates rates[];
   ArraySetAsSeries(rates, false);                  // ascending: index 0 = oldest
   int gotRates = CopyRates(_Symbol, _Period, 0, total, rates);
   if(gotRates < total)
   {
      PrintFormat("TrendFollowing_EA: CopyRates returned %d of %d requested bars - skipping this bar", gotRates, total);
      return;
   }

   double open[], high[], low[], close[];
   ArrayResize(open,  total); ArrayResize(high, total);
   ArrayResize(low,   total); ArrayResize(close, total);
   for(int i=0; i<total; i++)
   {
      open[i]=rates[i].open; high[i]=rates[i].high;
      low[i]=rates[i].low;   close[i]=rates[i].close;
   }

   double emaFast[], emaSlow[], emaTrend[];
   ArraySetAsSeries(emaFast,  false);
   ArraySetAsSeries(emaSlow,  false);
   ArraySetAsSeries(emaTrend, false);
   int gotFast  = CopyBuffer(hFastEMA,  0, 0, total, emaFast);
   int gotSlow  = CopyBuffer(hSlowEMA,  0, 0, total, emaSlow);
   int gotTrend = CopyBuffer(hTrendEMA, 0, 0, total, emaTrend);
   if(gotFast < total || gotSlow < total || gotTrend < total)
   {
      PrintFormat("TrendFollowing_EA: EMA buffers returned fewer bars than requested (fast=%d slow=%d trend=%d, needed %d) - skipping this bar",
                  gotFast, gotSlow, gotTrend, total);
      return;
   }

   double atrBands[];
   CalcWilderATR(high, low, close, atrBands, total, InpAtrPeriodBands);

   double haOpen[], haClose[];
   CalcHeikinAshi(open, high, low, close, haOpen, haClose, total);

   bool canTakeLong  = true;
   bool canTakeShort = true;
   bool trendBull    = false;

   int lastClosed  = total - 2;                    // total-1 is the still-forming bar
   int signalStart = MathMax(InpTrendLen, InpSlopeBars) + 1;

   for(int i=signalStart; i<=lastClosed; i++)
   {
      int pSlope = i - InpSlopeBars;
      if(pSlope < 0) continue;

      double close1 = close[i];
      double low1   = low[i];
      double high1  = high[i];
      double ema21  = emaFast[i];
      double ema50  = emaSlow[i];
      double ema200 = emaTrend[i];

      trendBull = close1 > ema200;                 // display only, matches the source

      bool stackBull = (ema21 > ema50 && ema50 > ema200);
      bool stackBear = (ema21 < ema50 && ema50 < ema200);

      bool ema50Up    = (emaSlow[i]  - emaSlow[pSlope])  > 0;
      bool ema200Up   = (emaTrend[i] - emaTrend[pSlope]) > 0;
      bool ema50Down  = (emaSlow[i]  - emaSlow[pSlope])  < 0;
      bool ema200Down = (emaTrend[i] - emaTrend[pSlope]) < 0;
      bool emaDirBull = ema50Up   && ema200Up;
      bool emaDirBear = ema50Down && ema200Down;

      bool touchA1Bull = (low1  <= ema21 && low1  >= ema50);
      bool touchA1Bear = (high1 >= ema21 && high1 <= ema50);
      bool touchA2Bull = (low1  <  ema50 && low1  >= ema200);
      bool touchA2Bear = (high1 >  ema50 && high1 <= ema200);

      bool haGreen1 = haClose[i]   > haOpen[i];
      bool haRed1   = haClose[i]   < haOpen[i];
      bool haGreen2 = (i>0) && (haClose[i-1] > haOpen[i-1]);
      bool haRed2   = (i>0) && (haClose[i-1] < haOpen[i-1]);
      bool haLongValid  = InpUseDoubleHA ? (haGreen1 && haGreen2) : haGreen1;
      bool haShortValid = InpUseDoubleHA ? (haRed1   && haRed2)   : haRed1;

      // --- Re-arming (runs before signal evaluation, as in the source) -----
      if(close1 > ema21) canTakeLong  = true;
      if(close1 < ema21) canTakeShort = true;

      bool buyA1  = stackBull && touchA1Bull && haLongValid  && canTakeLong  && emaDirBull;
      bool buyA2  = stackBull && touchA2Bull && haLongValid  && canTakeLong  && emaDirBull;
      bool sellA1 = stackBear && touchA1Bear && haShortValid && canTakeShort && emaDirBear;
      bool sellA2 = stackBear && touchA2Bear && haShortValid && canTakeShort && emaDirBear;

      bool   isLive  = (i == lastClosed);
      double buffer    = InpEntryBufferPips * PipSize();
      double scaledATR = atrBands[i] * InpAtrMultBands;

      if(buyA1 || buyA2)
      {
         bool   isMarket = !(close1 > (ema21 + buffer));
         double entry    = isMarket ? close1 : (ema21 + buffer);
         double sl       = close1 - scaledATR;        // Pine's lowerATRBand_b
         double risk     = entry - sl;
         double tp       = entry + risk*InpTPRMultiple;
         string tag      = buyA1 ? InpTxtA1 : InpTxtA2;

         if(risk > 0)
         {
            if(isLive) ExecuteSignal(true, entry, sl, tp, isMarket, tag);
            if(InpShowChartObjects)
               DrawSignal(true, rates[i].time, low1, high1, scaledATR, entry, sl, tp, risk, tag);
         }
         canTakeLong = false;                          // Pine locks unconditionally
      }

      if(sellA1 || sellA2)
      {
         bool   isMarket = !(close1 < (ema21 - buffer));
         double entry    = isMarket ? close1 : (ema21 - buffer);
         double sl       = close1 + scaledATR;         // Pine's upperATRBand_b
         double risk     = sl - entry;
         double tp       = entry - risk*InpTPRMultiple;
         string tag      = sellA1 ? InpTxtA1 : InpTxtA2;

         if(risk > 0)
         {
            if(isLive) ExecuteSignal(false, entry, sl, tp, isMarket, tag);
            if(InpShowChartObjects)
               DrawSignal(false, rates[i].time, low1, high1, scaledATR, entry, sl, tp, risk, tag);
         }
         canTakeShort = false;
      }
   }

   UpdateDashboard(trendBull, canTakeLong || canTakeShort);
}
//+------------------------------------------------------------------+
