import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
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
import { Page } from './shell/Page';
import { Panel, StatusTag, MetricTile, Meter, TermSelect, SectionLabel, type Tone } from './ui/Terminal';
import { useStore } from '../store/useStore';
import type { PortfolioOverviewItem } from '../types';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Filler);

const fetchOverview = async (days: number): Promise<PortfolioOverviewItem[]> => {
  const res = await fetch(`/api/portfolio_overview?days=${days}`);
  return res.json();
};

const usd = (v: number) =>
  v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const signedUsd = (v: number) => (v >= 0 ? '+' : '-') + '$' + usd(Math.abs(v));

/** Reconstruct a running-equity curve from daily P&L deltas, anchored to
 * live equity when available (last point always snaps to it), otherwise
 * falls back to a relative cumulative-P&L curve starting at 0. */
function buildEquityCurve(item: PortfolioOverviewItem, liveEquity: number | undefined) {
  const points = item.daily_pnl;
  const totalPeriodProfit = points.reduce((sum, d) => sum + d.profit, 0);
  const anchor = liveEquity ?? totalPeriodProfit;
  const startBalance = anchor - totalPeriodProfit;

  let running = startBalance;
  const labels: string[] = [];
  const data: number[] = [];
  points.forEach((d, i) => {
    labels.push(d.label);
    const isLast = i === points.length - 1;
    if (isLast && liveEquity !== undefined) {
      data.push(liveEquity);
    } else {
      running += d.profit;
      data.push(parseFloat(running.toFixed(2)));
    }
  });
  return { labels, data, isLive: liveEquity !== undefined };
}

function EquityChart({ labels, data }: { labels: string[]; data: number[] }) {
  const first = data[0] ?? 0;
  const last = data[data.length - 1] ?? 0;
  const up = last >= first;
  const lineColor = up ? 'var(--color-buy)' : 'var(--color-sell)';

  const chartData = {
    labels,
    datasets: [
      {
        data,
        borderColor: up ? '#00ff66' : '#ff3b30',
        backgroundColor: up ? 'rgba(0, 255, 102, 0.06)' : 'rgba(255, 59, 48, 0.06)',
        fill: true,
        tension: 0.15,
        pointRadius: 0,
        borderWidth: 1.5,
      },
    ],
  };

  const options: ChartOptions<'line'> = {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    plugins: {
      tooltip: {
        backgroundColor: '#000000',
        borderColor: 'var(--border-dark)',
        borderWidth: 1,
        titleFont: { family: 'JetBrains Mono', size: 9 },
        bodyFont: { family: 'JetBrains Mono', size: 10 },
        displayColors: false,
        callbacks: {
          label: (ctx) => `$${usd(Number(ctx.parsed.y))}`,
        },
      },
    },
    scales: {
      x: { display: false },
      y: { display: false },
    },
  };

  return (
    <div style={{ height: '90px', position: 'relative' }}>
      <Line data={chartData} options={options} />
      <span
        style={{
          position: 'absolute',
          top: 0,
          right: 0,
          fontSize: '9px',
          fontVariantNumeric: 'tabular-nums',
          color: lineColor,
        }}
      >
        {up ? '▲' : '▼'} {signedUsd(last - first)}
      </span>
    </div>
  );
}

function profitFactorTone(pf: number | null): Tone {
  if (pf === null) return 'muted';
  if (pf >= 1.5) return 'success';
  if (pf >= 1.0) return 'warning';
  return 'error';
}

function drawdownTone(pct: number): Tone {
  if (pct >= 8) return 'error';
  if (pct >= 4) return 'warning';
  return 'success';
}

function PortfolioCard({ item }: { item: PortfolioOverviewItem }) {
  const instances = useStore((s) => s.instances || []);
  const live = instances.find((i) => i.id === item.id);
  const navigate = useNavigate();

  const curve = useMemo(() => buildEquityCurve(item, live?.equity), [item, live?.equity]);
  const { risk } = item;

  const floatingPnl = live ? (live.equity || 0) - (live.balance || 0) : undefined;

  let roleBadge: React.ReactNode = null;
  if (item.copier_role === 'PROVIDER') roleBadge = <StatusTag label="MASTER" tone="warning" />;
  else if (item.copier_role === 'CONSUMER') roleBadge = <StatusTag label="SUB" tone="accent" />;

  return (
    <div
      onClick={() => navigate(`/portfolio/${item.id}`)}
      role="link"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          navigate(`/portfolio/${item.id}`);
        }
      }}
      title={`Open trading journal for ${item.name}`}
      style={{ cursor: 'pointer', minWidth: 0, outline: 'none' }}
      onMouseEnter={(e) => (e.currentTarget.style.filter = 'brightness(1.18)')}
      onMouseLeave={(e) => (e.currentTarget.style.filter = 'none')}
    >
    <Panel
      style={{ minWidth: 0 }}
      title={
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', alignItems: 'flex-start' }}>
          <span style={{ whiteSpace: 'nowrap' }}>{item.name}</span>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '5px' }}>
            {roleBadge}
            {item.account_type === 'PROPFIRM' && <StatusTag label="PROPFIRM" tone="error" />}
            {!live && <StatusTag label="OFFLINE" tone="muted" />}
          </div>
        </div>
      }
      actions={
        <span style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '10px', color: 'var(--text-muted)' }}>
          {live && (
            <span>
              EQ <strong style={{ color: 'var(--text-main)' }}>${usd(live.equity || 0)}</strong>
            </span>
          )}
          <StatusTag label="JOURNAL ›" tone="accent" />
        </span>
      }
      bodyStyle={{ padding: '12px', display: 'flex', flexDirection: 'column', gap: '12px' }}
    >
      {/* Live snapshot row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px' }}>
        <MetricTile label="Balance" value={live ? `$${usd(live.balance || 0)}` : '—'} />
        <MetricTile label="Equity" value={live ? `$${usd(live.equity || 0)}` : '—'} />
        <MetricTile
          label="Floating P&L"
          value={floatingPnl !== undefined ? signedUsd(floatingPnl) : '—'}
          tone={floatingPnl === undefined ? 'muted' : floatingPnl >= 0 ? 'success' : 'error'}
        />
        <MetricTile label="Open Pos" value={live ? String(live.positions?.length || 0) : '—'} />
      </div>

      {/* Equity curve */}
      <div>
        <SectionLabel style={{ marginBottom: '4px' }}>
          Equity Curve · Last {item.days}d {curve.isLive ? '' : '(realized only, offline)'}
        </SectionLabel>
        <EquityChart labels={curve.labels} data={curve.data} />
      </div>

      {/* Risk metrics grid */}
      <div>
        <SectionLabel style={{ marginBottom: '4px' }}>Risk Metrics · Last {item.days}d</SectionLabel>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px' }}>
          <MetricTile
            label="Peak Drawdown"
            value={`${risk.peak_drawdown_pct.toFixed(2)}%`}
            tone={drawdownTone(risk.peak_drawdown_pct)}
          />
          <MetricTile label="Max Risk Exposed" value={`$${usd(risk.max_risk_usd)}`} tone="warning" />
          <MetricTile
            label="Profit Factor"
            value={risk.profit_factor === null ? 'n/a' : risk.profit_factor.toFixed(2)}
            tone={profitFactorTone(risk.profit_factor)}
          />
          <MetricTile
            label="Total Realized"
            value={signedUsd(risk.total_realized)}
            tone={risk.total_realized >= 0 ? 'success' : 'error'}
          />
          <MetricTile
            label="Max Loss Streak"
            value={String(risk.max_loss_streak)}
            tone={risk.max_loss_streak >= 5 ? 'error' : risk.max_loss_streak >= 3 ? 'warning' : 'muted'}
          />
          <MetricTile label="Largest Loss" value={risk.largest_loss === 0 ? '$0.00' : `-$${usd(Math.abs(risk.largest_loss))}`} tone="error" />
          <MetricTile
            label="Trades w/o SL"
            value={String(risk.no_sl_count)}
            tone={risk.no_sl_count > 0 ? 'error' : 'muted'}
          />
          <MetricTile label="Total Trades" value={String(risk.total_trades)} />
        </div>
        {risk.win_rate !== null && (
          <div style={{ marginTop: '8px' }}>
            <Meter value={risk.win_rate} width={16} />
          </div>
        )}
      </div>
    </Panel>
    </div>
  );
}

const DAY_OPTIONS = [
  { label: '30 Days', value: 30 },
  { label: '90 Days (Quarter)', value: 90 },
  { label: '180 Days', value: 180 },
  { label: '365 Days', value: 365 },
];

export default function PortfolioManagement() {
  const [days, setDays] = useState(90);
  const { data = [], isLoading } = useQuery<PortfolioOverviewItem[]>({
    queryKey: ['portfolio_overview', days],
    queryFn: () => fetchOverview(days),
    refetchInterval: 60000,
  });

  const groups = useMemo(() => {
    const map = new Map<string, PortfolioOverviewItem[]>();
    for (const item of data) {
      const key = item.group_name || 'Ungrouped';
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(item);
    }
    return Array.from(map.entries());
  }, [data]);

  return (
    <Page
      title="Portfolio Management"
      description="Per-account equity curve and risk exposure over the selected trailing window."
      maxWidth={1600}
      actions={
        <TermSelect value={days} onChange={(e) => setDays(Number(e.target.value))} style={{ width: '180px' }}>
          {DAY_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </TermSelect>
      }
    >
      {isLoading ? (
        <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>Loading portfolios…</div>
      ) : data.length === 0 ? (
        <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
          No instances configured. Add one from the Trade Copier page.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {groups.map(([groupName, items]) => (
            <div key={groupName} style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {groups.length > 1 && <SectionLabel>{groupName}</SectionLabel>}
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fill, minmax(420px, 1fr))',
                  gap: '14px',
                }}
              >
                {items.map((item) => (
                  <PortfolioCard key={item.id} item={item} />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </Page>
  );
}
