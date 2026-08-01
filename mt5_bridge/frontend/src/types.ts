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
