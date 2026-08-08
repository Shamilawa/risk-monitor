import { MetricTile, SectionLabel, type Tone } from '../ui/Terminal';
import { duration, num, pct, signedPct, signedR, signedUsd, usd } from './format';
import type { JournalMetrics } from '../../types';

/* The 5-second read: "am I OK?". Everything here is a headline an algo operator checks
   before deciding whether to look any deeper. Ordering is deliberate — money first,
   then edge quality, then risk. */

function pfTone(pf: number | null): Tone {
  if (pf === null) return 'muted';
  if (pf >= 1.5) return 'success';
  if (pf >= 1.0) return 'warning';
  return 'error';
}

function ddTone(p: number): Tone {
  if (p >= 15) return 'error';
  if (p >= 8) return 'warning';
  return 'success';
}

function expTone(v: number | null): Tone {
  if (v === null) return 'muted';
  return v > 0 ? 'success' : v < 0 ? 'error' : 'muted';
}

/** SQN is suppressed server-side below 30 R-trades; say why rather than showing nothing. */
function sqnSub(m: JournalMetrics) {
  if (m.sqn !== null) return `${m.r_trades} R-trades`;
  return m.r_trades >= 30 ? 'no dispersion' : `needs 30 R-trades (have ${m.r_trades})`;
}

export function VerdictBar({ m, startBalance }: { m: JournalMetrics; startBalance: number | null }) {
  const holdSkew =
    m.avg_hold_win_sec !== null && m.avg_hold_loss_sec !== null && m.avg_hold_win_sec > 0
      ? m.avg_hold_loss_sec / m.avg_hold_win_sec
      : null;

  const p = m.pct ?? ({} as JournalMetrics['pct']);

  const tiles = [
    {
      label: 'Net P&L',
      value: signedUsd(m.net_pnl),
      tone: m.net_pnl >= 0 ? 'success' : 'error',
      // The percentage lives with the dollars rather than in a separate tile, so the two
      // can never drift apart or be read against different bases.
      sub: p.net_pnl === null || p.net_pnl === undefined
        ? `${m.total_trades} trades`
        : `${signedPct(p.net_pnl)} · ${m.total_trades} trades`,
    },
    {
      label: 'Return',
      value: signedPct(p.net_pnl),
      tone: (p.net_pnl ?? 0) >= 0 ? 'success' : 'error',
      sub: p.reference_balance ? `on $${usd(p.reference_balance)} capital` : 'no balance to measure against',
    },
    {
      label: 'Expectancy',
      value: signedR(m.expectancy_r),
      tone: expTone(m.expectancy_r),
      // Coverage sits with the metric, never apart from it: an expectancy computed over
      // 60% of trades is a different claim from one computed over all of them.
      sub: `${pct(m.r_coverage_pct, 0)} of trades had a stop`,
    },
    {
      label: 'Expectancy $',
      value: m.expectancy_usd === null ? 'n/a' : signedUsd(m.expectancy_usd),
      tone: expTone(m.expectancy_usd),
      sub: p.expectancy === null || p.expectancy === undefined
        ? 'per trade'
        : `${signedPct(p.expectancy, 3)} per trade`,
    },
    {
      label: 'Profit Factor',
      value: num(m.profit_factor),
      tone: pfTone(m.profit_factor),
      sub: m.profit_factor === null
        ? 'no losing trades'
        : p.gross_profit !== null && p.gross_profit !== undefined
          ? `+${p.gross_profit.toFixed(2)}% / ${(p.gross_loss ?? 0).toFixed(2)}%`
          : `$${usd(m.gross_profit)} / $${usd(Math.abs(m.gross_loss))}`,
    },
    {
      label: 'Win Rate',
      value: pct(m.win_rate),
      tone: 'main',
      // The number that says whether the win rate is actually good enough.
      sub: m.breakeven_win_rate === null ? `${m.wins}W / ${m.losses}L` : `breakeven ${pct(m.breakeven_win_rate)}`,
    },
    {
      label: 'Max Drawdown',
      value: pct(m.max_dd_pct, 2),
      tone: ddTone(m.max_dd_pct),
      sub: startBalance === null ? `$${usd(m.max_dd_usd)} (unanchored)` : `$${usd(m.max_dd_usd)}`,
    },
    {
      label: 'Current DD',
      value: pct(m.current_dd_pct, 2),
      tone: ddTone(m.current_dd_pct),
      sub: `$${usd(m.current_dd_usd)} off peak`,
    },
    {
      label: 'SQN',
      value: num(m.sqn),
      tone: m.sqn === null ? 'muted' : m.sqn >= 2.5 ? 'success' : m.sqn >= 1.6 ? 'warning' : 'error',
      sub: sqnSub(m),
    },
  ] as const;

  const secondary = [
    {
      label: 'Payoff Ratio',
      value: num(m.payoff_ratio),
      tone: 'main' as Tone,
      sub:
        p.avg_win !== null && p.avg_win !== undefined
          ? `avg ${signedPct(p.avg_win)} / ${signedPct(p.avg_loss)}`
          : `avg ${m.avg_win === null ? 'n/a' : signedUsd(m.avg_win)} / ${m.avg_loss === null ? 'n/a' : signedUsd(m.avg_loss)}`,
    },
    {
      label: 'Loss Streak',
      value: String(m.max_loss_streak),
      tone: (m.max_loss_streak >= 5 ? 'error' : m.max_loss_streak >= 3 ? 'warning' : 'muted') as Tone,
      sub: `current ${m.current_streak > 0 ? `+${m.current_streak}W` : m.current_streak < 0 ? `${-m.current_streak}L` : 'flat'}`,
    },
    {
      label: 'Largest Loss',
      value: m.largest_loss === 0 ? '$0.00' : signedUsd(m.largest_loss),
      tone: 'error' as Tone,
      sub:
        p.largest_loss !== null && p.largest_loss !== undefined
          ? `${signedPct(p.largest_loss)} · best ${signedPct(p.largest_win)}`
          : `best ${signedUsd(m.largest_win)}`,
    },
    {
      label: 'Trades w/o SL',
      value: String(m.no_sl_count),
      tone: (m.no_sl_count > 0 ? 'error' : 'muted') as Tone,
      sub: m.no_sl_count > 0 ? 'excluded from R metrics' : 'every trade had a stop',
    },
    {
      label: 'Cost Drag',
      value: pct(m.cost_drag_pct, 2),
      tone: (m.cost_drag_pct !== null && m.cost_drag_pct > 20 ? 'warning' : 'muted') as Tone,
      // Swap is broken out because it is what quietly kills carry-holding EAs.
      sub:
        p.commission !== null && p.commission !== undefined
          ? `comm ${signedPct(p.commission)} · swap ${signedPct(p.swap)}`
          : `comm $${usd(Math.abs(m.commission_total))} · swap $${usd(Math.abs(m.swap_total))}`,
    },
    {
      label: 'Avg Hold (Win)',
      value: duration(m.avg_hold_win_sec),
      tone: 'main' as Tone,
      sub: `loss ${duration(m.avg_hold_loss_sec)}`,
    },
    {
      label: 'Hold Skew',
      value: holdSkew === null ? 'n/a' : `${holdSkew.toFixed(2)}x`,
      // Losers held much longer than winners is the signature of an EA that has stopped
      // honouring its stop — worth flagging before it becomes a drawdown.
      tone: (holdSkew !== null && holdSkew >= 2 ? 'warning' : 'muted') as Tone,
      sub: 'loser vs winner hold time',
    },
    {
      label: 'Volume',
      value: m.total_volume.toFixed(2),
      tone: 'muted' as Tone,
      sub: 'total lots closed',
    },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '8px' }}>
        {tiles.map((t) => (
          <MetricTile key={t.label} label={t.label} value={t.value} tone={t.tone as Tone} sub={t.sub} />
        ))}
      </div>
      <SectionLabel>Secondary</SectionLabel>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '8px' }}>
        {secondary.map((t) => (
          <MetricTile key={t.label} label={t.label} value={t.value} tone={t.tone} sub={t.sub} />
        ))}
      </div>
    </div>
  );
}
