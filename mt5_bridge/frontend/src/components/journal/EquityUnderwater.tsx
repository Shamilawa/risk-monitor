import { useMemo } from 'react';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Tooltip,
  Filler,
  type ChartOptions,
} from 'chart.js';
import { Line } from 'react-chartjs-2';
import { SectionLabel, StatusTag } from '../ui/Terminal';
import { pct, signedUsd, usd } from './format';
import type { JournalEquity } from '../../types';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Filler);

/* Equity curve plus the underwater plot beneath it, sharing an x-axis.
   Plotted alone, an equity curve hides the two things that actually matter — how deep the
   drawdowns went and how long they lasted — so the two are never shown apart. */

const GRID = 'rgba(128,128,128,0.10)';

function baseOptions(anchored: boolean, labels: string[], cumPct: (number | null)[] = []): ChartOptions<'line'> {
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      tooltip: {
        backgroundColor: '#000000',
        borderColor: 'var(--border-dark)',
        borderWidth: 1,
        titleFont: { family: 'JetBrains Mono', size: 9 },
        bodyFont: { family: 'JetBrains Mono', size: 10 },
        displayColors: false,
        callbacks: {
          title: (items) => labels[items[0].dataIndex] ?? '',
          label: (ctx) => {
            const y = Number(ctx.parsed.y ?? 0);
            // dd is plotted negated so it hangs below the axis; report it as a depth.
            if (ctx.dataset.label === 'dd') return `Drawdown ${Math.abs(y).toFixed(2)}%`;
            const p = cumPct[ctx.dataIndex];
            const money = `${anchored ? 'Equity' : 'Cum P&L'} $${usd(y)}`;
            return p === null || p === undefined
              ? money
              : `${money}  (${p >= 0 ? '+' : ''}${p.toFixed(2)}% cum.)`;
          },
        },
      },
    },
    scales: {
      x: { display: false, grid: { display: false } },
      y: {
        grid: { color: GRID },
        ticks: {
          font: { family: 'JetBrains Mono', size: 9 },
          color: 'rgba(128,128,128,0.8)',
          maxTicksLimit: 5,
        },
      },
    },
  };
}

export function EquityUnderwater({ data }: { data: JournalEquity }) {
  const { labels, equity, dd, cumPct } = useMemo(() => {
    const l: string[] = [];
    const e: number[] = [];
    const d: number[] = [];
    const c: (number | null)[] = [];
    for (const p of data.points) {
      l.push(p.label);
      e.push(p.equity);
      // Negated so the underwater plot hangs below zero, which is how the shape reads.
      d.push(-p.dd_pct);
      c.push(p.cum_pct);
    }
    return { labels: l, equity: e, dd: d, cumPct: c };
  }, [data.points]);

  if (data.points.length === 0) {
    return (
      <div style={{ padding: '30px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '11px' }}>
        No closed trades in this window.
      </div>
    );
  }

  const first = equity[0];
  const last = equity[equity.length - 1];
  const up = last >= first;

  const equityData = {
    labels,
    datasets: [
      {
        label: 'equity',
        data: equity,
        borderColor: up ? '#00ff66' : '#ff3b30',
        backgroundColor: up ? 'rgba(0, 255, 102, 0.06)' : 'rgba(255, 59, 48, 0.06)',
        fill: true,
        tension: 0.12,
        pointRadius: 0,
        borderWidth: 1.5,
      },
    ],
  };

  const ddData = {
    labels,
    datasets: [
      {
        label: 'dd',
        data: dd,
        borderColor: '#ff3b30',
        backgroundColor: 'rgba(255, 59, 48, 0.16)',
        fill: 'origin' as const,
        tension: 0.12,
        pointRadius: 0,
        borderWidth: 1,
      },
    ],
  };

  const ddOptions = baseOptions(data.anchored, labels, cumPct);
  const lastCum = cumPct[cumPct.length - 1];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '10px',
          flexWrap: 'wrap',
        }}
      >
        <SectionLabel>{data.anchored ? 'Equity Curve' : 'Cumulative P&L (no live balance)'}</SectionLabel>
        <div style={{ display: 'flex', gap: '10px', fontSize: '10px', fontVariantNumeric: 'tabular-nums' }}>
          <span style={{ color: up ? 'var(--color-buy)' : 'var(--color-sell)' }}>
            {up ? '▲' : '▼'} {signedUsd(last - first)}
            {lastCum !== null && lastCum !== undefined
              ? ` (${lastCum >= 0 ? '+' : ''}${lastCum.toFixed(2)}%)`
              : ''}
          </span>
          <span style={{ color: 'var(--text-muted)' }}>
            max DD {pct(data.max_dd_pct, 2)} (${usd(data.max_dd_usd)})
          </span>
          {!data.anchored && <StatusTag label="UNANCHORED" tone="muted" />}
        </div>
      </div>

      <div style={{ height: '190px' }}>
        <Line data={equityData} options={baseOptions(data.anchored, labels, cumPct)} />
      </div>

      <SectionLabel style={{ marginTop: '2px' }}>Underwater · drawdown from peak</SectionLabel>
      <div style={{ height: '90px' }}>
        <Line data={ddData} options={ddOptions} />
      </div>
    </div>
  );
}
