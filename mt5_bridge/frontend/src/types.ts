export interface Position {
  ticket: number;
  symbol: string;
  type: string;
  volume: number;
  price_open: number;
  price_current: number;
  sl: number;
  tp: number;
  profit: number;
  risk_usd: number;
  dist_sl: number;
  open_price?: number;
  current_price?: number;
}

export interface Instance {
  id: number;
  name: string;
  path: string;
  copier_role: string;
  copier_risk_type?: string;
  copier_fixed_lot?: number;
  copier_risk_usd?: number;
  copier_risk_multiplier?: number;
  balance?: number;
  equity?: number;
  margin_level?: number;
  positions?: Position[];
  realized_gains?: Record<string, number>;
  symbol_mapping?: string;
  group_name?: string;
  alert_drawdown_limit?: number;
  alert_drawdown_levels?: string;
  alert_profit_ceiling_usd?: number;
  alert_profit_lock_pct?: number;
  trade_locked?: boolean;
  account_type?: string;
  news_block_before_min?: number;
  news_block_after_min?: number;
}

export interface NewsWindow {
  title: string;
  currency: string;
  event_time: number;
  start: number;
  end: number;
}

export interface NewsToday {
  status: 'AUTO' | 'MANUAL' | 'FAILED';
  date: string;
  fetched_at: number;
  events: NewsWindow[];
}

export interface BlockedAction {
  id: number;
  instance_id: number;
  instance_name: string;
  action_type: 'CLOSE' | 'MODIFY';
  ticket: number;
  symbol: string;
  volume?: number;
  sl?: number;
  tp?: number;
  reason: string;
  blocked_at: number;
  status: 'PENDING' | 'EXECUTED' | 'DISMISSED';
}

export interface DailyPnlPoint {
  date: string;
  label: string;
  profit: number;
}

export interface PortfolioRiskMetrics {
  peak_drawdown_pct: number;
  max_risk_usd: number;
  no_sl_count: number;
  total_trades: number;
  win_rate: number | null;
  profit_factor: number | null;
  largest_loss: number;
  best_trade: number;
  max_loss_streak: number;
  total_realized: number;
}

/* ---------------- Trading Journal ---------------- */

/** Null means "not computable from this sample", never a sentinel value —
 * the UI must render those as n/a rather than a number. */
export interface JournalMetrics {
  total_trades: number;
  wins: number;
  losses: number;
  scratches: number;
  win_rate: number | null;
  net_pnl: number;
  gross_profit: number;
  gross_loss: number;
  profit_factor: number | null;
  avg_win: number | null;
  avg_loss: number | null;
  payoff_ratio: number | null;
  breakeven_win_rate: number | null;
  expectancy_usd: number | null;
  expectancy_r: number | null;
  r_trades: number;
  r_coverage_pct: number;
  std_r: number | null;
  sqn: number | null;
  largest_win: number;
  largest_loss: number;
  max_win_streak: number;
  max_loss_streak: number;
  current_streak: number;
  commission_total: number;
  swap_total: number;
  cost_drag_pct: number | null;
  no_sl_count: number;
  avg_hold_win_sec: number | null;
  avg_hold_loss_sec: number | null;
  avg_hold_sec: number | null;
  total_volume: number;
  max_dd_usd: number;
  max_dd_pct: number;
  current_dd_usd: number;
  current_dd_pct: number;
  pct: JournalPercentages;
}

export interface JournalInstance {
  id: number;
  name: string;
  group_name: string;
  account_type: string;
  copier_role: string;
  trade_locked: boolean;
}

export interface JournalSummary {
  instance: JournalInstance;
  days: number;
  start_balance: number | null;
  metrics: JournalMetrics;
}

export interface EquityPoint {
  ts: number;
  equity: number;
  dd_usd: number;
  dd_pct: number;
  label: string;
  profit: number;
  /** Cumulative return to this point, so the curve reads in % as well as dollars. */
  cum_pct: number | null;
}

export interface JournalEquity {
  days: number;
  start_balance: number | null;
  anchored: boolean;
  points: EquityPoint[];
  max_dd_usd: number;
  max_dd_pct: number;
  current_dd_usd: number;
  current_dd_pct: number;
}

export interface BreakdownRow {
  key: string | number;
  label: string;
  hint?: string;
  trades: number;
  net_pnl: number;
  /** Against the window's opening capital, so rows sum to the page total. */
  net_pnl_pct: number | null;
  win_rate: number | null;
  profit_factor: number | null;
  expectancy_usd: number | null;
  expectancy_r: number | null;
  r_coverage_pct: number;
  max_dd_usd: number;
  avg_hold_sec: number | null;
  gross_profit: number;
  gross_loss: number;
}

export type BreakdownDimension = 'magic' | 'symbol' | 'direction' | 'hour' | 'weekday' | 'duration';

export interface JournalBreakdown {
  by: BreakdownDimension;
  days: number;
  rows: BreakdownRow[];
}

export interface CalendarEntry {
  date: string;
  profit: number;
  profit_pct: number | null;
  trades: number;
  wins: number;
  losses: number;
  win_rate: number | null;
}

export interface JournalCalendar {
  days: number;
  anchor: string;
  entries: CalendarEntry[];
  best_day: CalendarEntry | null;
  worst_day: CalendarEntry | null;
  active_days: number;
}

export interface JournalTrade {
  position_id: number | null;
  ticket: number;
  symbol: string;
  direction: number;
  side: 'LONG' | 'SHORT';
  volume: number;
  profit: number;
  /** This trade as a percentage of the window's opening capital. */
  profit_pct: number | null;
  risk_pct: number | null;
  raw_profit: number;
  commission: number;
  swap: number;
  close_ts: number;
  open_ts: number | null;
  duration_sec: number | null;
  magic: number | null;
  comment: string;
  sl_at_open: number;
  tp_at_open: number;
  entry_risk_usd: number;
  entry_price: number;
  exit_price: number;
  r_multiple: number | null;
  /** null until the M1 backfill has run — 0 is a legitimate value, so the two differ. */
  mae_usd: number | null;
  mfe_usd: number | null;
  mae_r: number | null;
  mfe_r: number | null;
  tags: string;
  grade: string;
  note: string;
  date: string;
  close_label: string;
  open_label: string | null;
}

export interface JournalTrades {
  days: number;
  total: number;
  offset: number;
  limit: number;
  trades: JournalTrade[];
}

export interface JournalFilterOptions {
  symbols: string[];
  magics: number[];
  days: number;
}

/* ---- Phase 2: distribution shape, risk-adjusted ratios, Monte Carlo ---- */

export interface RBin {
  start: number;
  end: number;
  label: string;
  count: number;
  is_loss: boolean;
}

export interface EdgeRatio {
  edge_ratio: number | null;
  avg_mfe_r: number | null;
  avg_mae_r: number | null;
  sample: number;
}

export interface JournalDistribution {
  days: number;
  bin_size: number;
  bins: RBin[];
  r_trades: number;
  coverage_pct: number;
  min_r: number | null;
  max_r: number | null;
  median_r: number | null;
  /** Share of gross profit from the single best / best three / best decile of winners.
   * High values mean the "edge" is a handful of outliers. */
  top1_share_pct: number | null;
  top3_share_pct: number | null;
  top_decile_share_pct: number | null;
  winners: number;
  edge: EdgeRatio;
}

export interface RiskAdjustedMetrics {
  sharpe: number | null;
  sortino: number | null;
  calmar: number | null;
  ulcer_index: number | null;
  volatility_annual_pct: number | null;
  return_annual_pct: number | null;
  total_return_pct: number | null;
  max_dd_pct: number | null;
  observations: number;
  periods_per_year: number | null;
  /** False when there are too few observations to publish the estimators. */
  sufficient: boolean;
  min_observations: number;
  /** Legitimately 0 when the account was funded inside the window — which is exactly why
   * total_return_pct is time-weighted rather than a simple end/start ratio. */
  opening_balance: number | null;
  closing_balance: number | null;
  funding_total: number | null;
}

export interface DailyReturn {
  date: string;
  start_balance: number;
  pnl: number;
  funding: number;
  ret: number;
}

export interface JournalRiskAdjusted {
  days: number;
  basis: string;
  risk_free_rate: number;
  anchored: boolean;
  metrics: RiskAdjustedMetrics;
  series: DailyReturn[];
}

export interface JournalMonteCarlo {
  days: number;
  sufficient: boolean;
  min_trades: number;
  trades: number;
  iterations: number;
  start_balance?: number;
  actual_max_dd_pct: number | null;
  /** Where the real drawdown sits among reshuffled orderings of the same trades. */
  actual_percentile: number | null;
  prob_worse: number | null;
  percentiles: Record<string, number>;
  bootstrap?: {
    final_percentiles: Record<string, number>;
    dd_percentiles: Record<string, number>;
    prob_losing: number;
    actual_total: number;
  };
}

export interface BackfillStatus {
  status: 'IDLE' | 'RUNNING';
  total?: number;
  done?: number;
  filled: number;
  failed?: number;
  pending: number;
  message?: string;
}

/** Page-wide filter state. Every panel reads the same object, so a click on an EA row
 * rescopes the whole page rather than just one panel. */
export interface JournalFilters {
  days: number;
  symbol?: string;
  magic?: number;
  direction?: 0 | 1;
  outcome?: 'win' | 'loss' | 'scratch';
  date?: string;
  /** Live account balance, sent with every request so all panels derive percentages from
   * the same opening capital. Not a filter — it never narrows the trade set. */
  balance?: number;
}

/** Dollar figures with their percentage twins, all against `reference_balance`. */
export interface JournalPercentages {
  reference_balance: number | null;
  net_pnl: number | null;
  gross_profit: number | null;
  gross_loss: number | null;
  expectancy: number | null;
  avg_win: number | null;
  avg_loss: number | null;
  largest_win: number | null;
  largest_loss: number | null;
  commission: number | null;
  swap: number | null;
}

export interface PortfolioOverviewItem {
  id: number;
  name: string;
  group_name: string;
  account_type: string;
  copier_role: string;
  days: number;
  daily_pnl: DailyPnlPoint[];
  risk: PortfolioRiskMetrics;
}

/** One open copier reconciliation incident (see mt5_bridge/copier_monitor.py). */
export interface CopierIncident {
  id: number;
  type: string;
  severity: 'CRITICAL' | 'WARN' | 'INFO';
  instance_id: number;
  instance_name: string;
  signal_id: string | null;
  provider_ticket: number | null;
  fingerprint: string | null;
  detail: Record<string, string>;
  first_seen: number;
  last_seen: number;
  status: 'OPEN' | 'ACKED';
}
