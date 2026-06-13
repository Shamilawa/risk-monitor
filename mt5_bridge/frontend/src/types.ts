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
}
