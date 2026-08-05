//+------------------------------------------------------------------+
//|                                        TrendFollowing_Visual.mq5 |
//|  Chart plots for the Trend Following system.                      |
//|  Reproduces the Pine script's plot() / fill() block: EMA 21/50/200,|
//|  the shaded Flow Zone, and the ATR bands used as the stop source.  |
//|  Purely visual - the EA does the trading.                          |
//+------------------------------------------------------------------+
#property copyright "Converted from Pine Script v6 indicator"
#property version   "2.00"
#property strict
#property indicator_chart_window
#property indicator_buffers 10
#property indicator_plots   6

//--- plot 0: Flow Zone fill between EMA21 and EMA50
#property indicator_label1  "Flow Zone"
#property indicator_type1   DRAW_FILLING
#property indicator_color1  clrGreen, clrRed

//--- plot 1: Trend EMA 200
#property indicator_label2  "Trend 200"
#property indicator_type2   DRAW_LINE
#property indicator_color2  clrWhite
#property indicator_width2  2

//--- plot 2: Fast EMA 21
#property indicator_label3  "Fast 21"
#property indicator_type3   DRAW_LINE
#property indicator_color3  clrLimeGreen
#property indicator_width3  1

//--- plot 3: Slow EMA 50
#property indicator_label4  "Slow 50"
#property indicator_type4   DRAW_LINE
#property indicator_color4  clrCrimson
#property indicator_width4  1

//--- plot 4/5: ATR bands (the stop-loss levels the EA uses)
#property indicator_label5  "Upper ATR Band"
#property indicator_type5   DRAW_LINE
#property indicator_color5  clrDimGray
#property indicator_style5  STYLE_DOT

#property indicator_label6  "Lower ATR Band"
#property indicator_type6   DRAW_LINE
#property indicator_color6  clrDimGray
#property indicator_style6  STYLE_DOT

//------------------------------------------------------------------
// INPUTS - keep the strategy/ATR inputs identical to the EA's
//------------------------------------------------------------------
input group "Strategy Definitions"
input int    InpFastLen        = 21;   // Fast EMA (Flow Zone)
input int    InpSlowLen        = 50;   // Slow EMA (Value Zone)
input int    InpTrendLen       = 200;  // Trend EMA (Trend Filter)
input int    InpSlopeBars      = 5;    // EMA slope lookback (bars)

input group "Filters & Confirmation"
input bool   InpUseDoubleHA    = true; // Require Double HA Confirmation?

input group "Risk Management (for the drawn levels only - no trading here)"
input int    InpEntryBufferPips = 5;   // Entry Tolerance (Pips)
input double InpTPRMultiple     = 1.8; // Take Profit R-multiple

input group "ATR Bands (Stop Loss Source)"
input int    InpAtrPeriodBands = 14;   // ATR Period (Bands)
input double InpAtrMultBands   = 3.0;  // ATR Band Scale Factor
input bool   InpShowBands      = true; // Show ATR Bands

input group "Signals"
input bool   InpShowSignals    = true;    // Draw Entry / SL / TP on signals
input string InpTxtA1          = "FLOW";  // Name for A1 Entry (shallow pullback)
input string InpTxtA2          = "VALUE"; // Name for A2 Entry (deep pullback)
input color  InpColEntry       = clrSilver; // Entry Line Color
input color  InpColSL          = clrRed;    // SL Line Color
input color  InpColTP          = clrLime;   // TP Line Color
input int    InpArrowWidth     = 2;       // Signal Arrow Size (1-5)
input bool   InpShowTextLabel  = true;    // Show FLOW/VALUE text next to arrow
input int    InpMaxSignalsOnChart = 500;  // Max signals kept drawn (oldest pruned, matches Pine's max_lines_count)

//------------------------------------------------------------------
// BUFFERS (non-series: index 0 = oldest)
//------------------------------------------------------------------
double BufFillA[];   // 0 - fill edge (EMA21, blanked when stack not aligned)
double BufFillB[];   // 1 - fill edge (EMA50, blanked when stack not aligned)
double BufEma200[];  // 2
double BufEma21[];   // 3
double BufEma50[];   // 4
double BufUpper[];   // 5
double BufLower[];   // 6
double BufAtr[];     // 7 - calculation only (Wilder ATR)
double BufHaOpen[];  // 8 - calculation only (Heikin Ashi)
double BufHaClose[]; // 9 - calculation only (Heikin Ashi)

// Pine's `var bool can_take_long = true` / `can_take_short = true`
bool     g_canTakeLong  = true;
bool     g_canTakeShort = true;
string   g_drawnUids[];             // ring buffer of drawn signal ids, for pruning

// Shared with TrendFollowing_EA.mq5 on purpose: if both are attached to the
// same chart with signals enabled, whichever computes a given signal first
// "owns" the object name, and the other's DrawSignal() no-ops on it (see the
// ObjectFind guard below) instead of drawing a second, slightly offset copy.
#define OBJ_PREFIX "TF_"

//------------------------------------------------------------------
int OnInit()
{
   if(InpFastLen < 1 || InpSlowLen < 1 || InpTrendLen < 1 || InpAtrPeriodBands < 1)
      return(INIT_PARAMETERS_INCORRECT);

   SetIndexBuffer(0, BufFillA,   INDICATOR_DATA);
   SetIndexBuffer(1, BufFillB,   INDICATOR_DATA);
   SetIndexBuffer(2, BufEma200,  INDICATOR_DATA);
   SetIndexBuffer(3, BufEma21,   INDICATOR_DATA);
   SetIndexBuffer(4, BufEma50,   INDICATOR_DATA);
   SetIndexBuffer(5, BufUpper,   INDICATOR_DATA);
   SetIndexBuffer(6, BufLower,   INDICATOR_DATA);
   SetIndexBuffer(7, BufAtr,     INDICATOR_CALCULATIONS);
   SetIndexBuffer(8, BufHaOpen,  INDICATOR_CALCULATIONS);
   SetIndexBuffer(9, BufHaClose, INDICATOR_CALCULATIONS);

   // 0.0 marks "don't draw" - prices are never 0, so this is safe.
   for(int p=0; p<6; p++)
      PlotIndexSetDouble(p, PLOT_EMPTY_VALUE, 0.0);

   PlotIndexSetInteger(1, PLOT_DRAW_BEGIN, InpTrendLen);
   PlotIndexSetInteger(2, PLOT_DRAW_BEGIN, InpFastLen);
   PlotIndexSetInteger(3, PLOT_DRAW_BEGIN, InpSlowLen);
   PlotIndexSetInteger(4, PLOT_DRAW_BEGIN, InpAtrPeriodBands);
   PlotIndexSetInteger(5, PLOT_DRAW_BEGIN, InpAtrPeriodBands);

   IndicatorSetString(INDICATOR_SHORTNAME,
      StringFormat("Trend Following (%d/%d/%d)", InpFastLen, InpSlowLen, InpTrendLen));
   IndicatorSetInteger(INDICATOR_DIGITS, (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS));

   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   if(reason==REASON_REMOVE || reason==REASON_CHARTCLOSE || reason==REASON_CLOSE)
      ObjectsDeleteAll(0, OBJ_PREFIX);
}

//------------------------------------------------------------------
// EMA with an SMA seed, matching Pine's ta.ema().
// buf[] and price[] are non-series; seeds at index period-1.
//------------------------------------------------------------------
void CalcEMA(const double &price[], double &buf[], int total, int period, int start)
{
   if(total < period) return;
   double alpha = 2.0 / (period + 1.0);

   int i = start;
   if(i < period-1) i = period-1;

   if(start <= period-1)          // (re)seed
   {
      double sum = 0;
      for(int k=0; k<period; k++) sum += price[k];
      buf[period-1] = sum / period;
      i = period;
      for(int k=0; k<period-1; k++) buf[k] = 0.0;
   }

   for(; i<total; i++)
      buf[i] = alpha*price[i] + (1.0-alpha)*buf[i-1];
}

//------------------------------------------------------------------
// Wilder/RMA ATR, matching Pine's ta.atr().
// (MT5's built-in iATR uses a simple MA of true range - different result.)
//------------------------------------------------------------------
void CalcAtr(const double &high[], const double &low[], const double &close[],
             double &buf[], int total, int period, int start)
{
   if(total < period+1) return;

   if(start <= period)             // (re)seed with SMA of the first `period` true ranges
   {
      double sum = 0;
      for(int k=0; k<period; k++)
      {
         double tr = (k==0) ? (high[k]-low[k])
                            : MathMax(high[k]-low[k],
                              MathMax(MathAbs(high[k]-close[k-1]), MathAbs(low[k]-close[k-1])));
         sum += tr;
         buf[k] = 0.0;
      }
      buf[period-1] = sum / period;
      start = period;
   }

   for(int i=start; i<total; i++)
   {
      double tr = MathMax(high[i]-low[i],
                  MathMax(MathAbs(high[i]-close[i-1]), MathAbs(low[i]-close[i-1])));
      buf[i] = (buf[i-1]*(period-1) + tr) / period;
   }
}

//------------------------------------------------------------------
// Heikin Ashi, recomputed forward from raw OHLC (ascending arrays here,
// so the recursion runs the natural direction: haOpen[i] depends on i-1).
//------------------------------------------------------------------
void CalcHA(const double &o[], const double &h[], const double &l[], const double &c[],
           double &haOpen[], double &haClose[], int total, int start)
{
   for(int i=start; i<total; i++)
   {
      haClose[i] = (o[i]+h[i]+l[i]+c[i]) / 4.0;
      if(i == 0)
         haOpen[i] = (o[i]+c[i]) / 2.0;
      else
         haOpen[i] = (haOpen[i-1]+haClose[i-1]) / 2.0;
   }
}

// Pine: entry_buffer_pips * syminfo.mintick * 10  -> one "pip"
double PipSize()
{
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   return (digits==3 || digits==5) ? point*10.0 : point;
}

//------------------------------------------------------------------
// CHART DRAWING  (the MT5 equivalent of the Pine line.new/label.new block)
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

void DrawSignal(bool isLong, datetime barTime, double barLow, double barHigh, double scaledATR,
               double entry, double sl, double tp, double risk, string tag)
{
   string uid = TimeToString(barTime, TIME_DATE|TIME_MINUTES) + "_" + tag;
   StringReplace(uid, " ", "_");

   if(ObjectFind(0, OBJ_PREFIX+"entry_"+uid) >= 0)
      return;                                  // already drawn on a previous recalculation

   int    digits   = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   double pip      = PipSize();
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
}

//------------------------------------------------------------------
// Re-arm + signal detection + drawing, one confirmed bar at a time.
// Mirrors ProcessClosedBar() in TrendFollowing_EA.mq5 exactly, just
// walked forward across the whole loaded history instead of only the
// latest closed bar, so the indicator renders every past signal too -
// the same way the original Pine script draws on load/replay.
//------------------------------------------------------------------
void DetectAndDrawSignals(const double &open[], const double &high[], const double &low[],
                          const double &close[], const datetime &time[], int rates_total, int start)
{
   int signalStart = MathMax(start, MathMax(InpTrendLen, InpSlopeBars) + 1);
   double buffer = InpEntryBufferPips * PipSize();

   // The last index (rates_total-1) is the still-forming bar - never a confirmed signal.
   for(int i=signalStart; i<rates_total-1; i++)
   {
      int pSlope = i - InpSlopeBars;
      if(pSlope < 0) continue;

      double close1 = close[i];
      double low1   = low[i];
      double high1  = high[i];
      double ema21  = BufEma21[i];
      double ema50  = BufEma50[i];
      double ema200 = BufEma200[i];

      bool stackBull = (ema21 > ema50 && ema50 > ema200);
      bool stackBear = (ema21 < ema50 && ema50 < ema200);

      bool ema50Up    = (BufEma50[i]  - BufEma50[pSlope])  > 0;
      bool ema200Up   = (BufEma200[i] - BufEma200[pSlope]) > 0;
      bool ema50Down  = (BufEma50[i]  - BufEma50[pSlope])  < 0;
      bool ema200Down = (BufEma200[i] - BufEma200[pSlope]) < 0;
      bool emaDirBull = ema50Up   && ema200Up;
      bool emaDirBear = ema50Down && ema200Down;

      bool touchA1Bull = (low1  <= ema21 && low1  >= ema50);
      bool touchA1Bear = (high1 >= ema21 && high1 <= ema50);
      bool touchA2Bull = (low1  <  ema50 && low1  >= ema200);
      bool touchA2Bear = (high1 >  ema50 && high1 <= ema200);

      bool haGreen1 = BufHaClose[i]   > BufHaOpen[i];
      bool haRed1   = BufHaClose[i]   < BufHaOpen[i];
      bool haGreen2 = (i>0) && (BufHaClose[i-1] > BufHaOpen[i-1]);
      bool haRed2   = (i>0) && (BufHaClose[i-1] < BufHaOpen[i-1]);
      bool haLongValid  = InpUseDoubleHA ? (haGreen1 && haGreen2) : haGreen1;
      bool haShortValid = InpUseDoubleHA ? (haRed1   && haRed2)   : haRed1;

      if(close1 > ema21) g_canTakeLong  = true;
      if(close1 < ema21) g_canTakeShort = true;

      bool buyA1  = stackBull && touchA1Bull && haLongValid  && g_canTakeLong  && emaDirBull;
      bool buyA2  = stackBull && touchA2Bull && haLongValid  && g_canTakeLong  && emaDirBull;
      bool sellA1 = stackBear && touchA1Bear && haShortValid && g_canTakeShort && emaDirBear;
      bool sellA2 = stackBear && touchA2Bear && haShortValid && g_canTakeShort && emaDirBear;

      double scaledATR = BufAtr[i] * InpAtrMultBands;

      if(buyA1 || buyA2)
      {
         bool   isMarket = !(close1 > (ema21 + buffer));
         double entry    = isMarket ? close1 : (ema21 + buffer);
         double sl       = close1 - scaledATR;
         double risk     = entry - sl;
         double tp       = entry + risk*InpTPRMultiple;
         string tag      = buyA1 ? InpTxtA1 : InpTxtA2;

         if(risk > 0 && InpShowSignals)
            DrawSignal(true, time[i], low1, high1, scaledATR, entry, sl, tp, risk, tag);
         g_canTakeLong = false;
      }

      if(sellA1 || sellA2)
      {
         bool   isMarket = !(close1 < (ema21 - buffer));
         double entry    = isMarket ? close1 : (ema21 - buffer);
         double sl       = close1 + scaledATR;
         double risk     = sl - entry;
         double tp       = entry - risk*InpTPRMultiple;
         string tag      = sellA1 ? InpTxtA1 : InpTxtA2;

         if(risk > 0 && InpShowSignals)
            DrawSignal(false, time[i], low1, high1, scaledATR, entry, sl, tp, risk, tag);
         g_canTakeShort = false;
      }
   }
}

//------------------------------------------------------------------
int OnCalculate(const int rates_total,
                const int prev_calculated,
                const datetime &time[],
                const double &open[],
                const double &high[],
                const double &low[],
                const double &close[],
                const long &tick_volume[],
                const long &volume[],
                const int &spread[])
{
   int minBars = MathMax(InpTrendLen, MathMax(InpSlowLen, MathMax(InpFastLen, InpAtrPeriodBands))) + 2;
   if(rates_total < minBars) return(0);

   int start = (prev_calculated > 1) ? prev_calculated-1 : 0;

   CalcEMA(close, BufEma21,  rates_total, InpFastLen,  start);
   CalcEMA(close, BufEma50,  rates_total, InpSlowLen,  start);
   CalcEMA(close, BufEma200, rates_total, InpTrendLen, start);
   CalcAtr(high, low, close, BufAtr, rates_total, InpAtrPeriodBands, start);
   CalcHA(open, high, low, close, BufHaOpen, BufHaClose, rates_total, start);

   for(int i=start; i<rates_total; i++)
   {
      // ATR bands: close +/- (ATR * multiplier) - the EA's stop-loss source.
      if(InpShowBands && i >= InpAtrPeriodBands)
      {
         double scaled = BufAtr[i] * InpAtrMultBands;
         BufUpper[i] = close[i] + scaled;
         BufLower[i] = close[i] - scaled;
      }
      else
      {
         BufUpper[i] = 0.0;
         BufLower[i] = 0.0;
      }

      // Flow Zone fill: only where the EMAs are fully stacked, as in the Pine fill().
      if(i < InpTrendLen)
      {
         BufFillA[i] = 0.0;
         BufFillB[i] = 0.0;
         continue;
      }

      bool stackBull = (BufEma21[i] > BufEma50[i] && BufEma50[i] > BufEma200[i]);
      bool stackBear = (BufEma21[i] < BufEma50[i] && BufEma50[i] < BufEma200[i]);

      if(stackBull || stackBear)
      {
         BufFillA[i] = BufEma21[i];   // > BufFillB when bullish  -> colour 1 (green)
         BufFillB[i] = BufEma50[i];   // < BufFillB when bearish  -> colour 2 (red)
      }
      else
      {
         BufFillA[i] = 0.0;
         BufFillB[i] = 0.0;
      }
   }

   if(InpShowSignals)
      DetectAndDrawSignals(open, high, low, close, time, rates_total, start);

   return(rates_total);
}
//+------------------------------------------------------------------+
