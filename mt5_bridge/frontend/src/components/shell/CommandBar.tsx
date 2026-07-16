import { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useStore } from '../../store/useStore';
import type { NewsToday } from '../../types';
import { findActiveWindow } from '../../utils/news';
import { PhosphorPicker } from '../../theme/PhosphorPicker';
import { moduleCodeFor } from './nav';

const fetchNewsToday = async (): Promise<NewsToday> => {
  const res = await fetch('/api/news/today');
  return res.json();
};

function useClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  const pad = (n: number) => String(n).padStart(2, '0');
  const date = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
  const time = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
  return `${date} · ${time}`;
}

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
      <span style={{ fontSize: '9px', fontWeight: 700, letterSpacing: '0.08em', color: 'var(--text-muted)' }}>{label}</span>
      <span
        style={{
          fontSize: '11px',
          fontWeight: 700,
          fontVariantNumeric: 'tabular-nums',
          color: color ?? 'var(--text-main)',
        }}
      >
        {value}
      </span>
    </div>
  );
}

const divider = (
  <span style={{ width: '1px', height: '16px', background: 'var(--border-color)', flexShrink: 0 }} />
);

export function CommandBar() {
  const { pathname } = useLocation();
  const instances = useStore((s) => s.instances || []);
  const clock = useClock();

  const { data: newsToday } = useQuery<NewsToday>({
    queryKey: ['news', 'today'],
    queryFn: fetchNewsToday,
    refetchInterval: 30000,
  });
  const newsFailed = newsToday?.status === 'FAILED';
  const activeBlackout = newsToday ? findActiveWindow(newsToday.events) : undefined;

  const totalEq = instances.reduce((a, i) => a + (i.equity || 0), 0);
  const totalBal = instances.reduce((a, i) => a + (i.balance || 0), 0);
  const pnl = totalEq - totalBal;
  const activeTrades = instances.reduce((a, i) => a + (i.positions?.length || 0), 0);

  const usd = (v: number) => v.toLocaleString('en-US', { style: 'currency', currency: 'USD' });
  const pnlColor = pnl > 0 ? 'var(--color-buy)' : pnl < 0 ? 'var(--color-sell)' : 'var(--text-main)';

  return (
    <header
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '12px',
        height: '42px',
        flexShrink: 0,
        padding: '0 12px',
        background: 'var(--bg-toolbar)',
        borderBottom: '1px solid var(--border-dark)',
        userSelect: 'none',
      }}
    >
      {/* Left: brand + active module */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', minWidth: 0 }}>
        <strong
          className="term-glow"
          style={{
            fontSize: '12px',
            fontWeight: 700,
            letterSpacing: '0.2em',
            textTransform: 'uppercase',
            color: 'var(--terminal-accent)',
            whiteSpace: 'nowrap',
          }}
        >
          RISK//MON
        </strong>
        <span style={{ fontSize: '9px', color: 'var(--text-muted)' }}>v2.0</span>
        {divider}
        <span style={{ fontSize: '10px', letterSpacing: '0.1em', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
          &#9666; {moduleCodeFor(pathname)}
        </span>
      </div>

      {/* Center: aggregate portfolio stats */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', overflow: 'hidden' }}>
        <Stat label="EQ" value={usd(totalEq)} />
        <Stat label="P&L" value={(pnl >= 0 ? '+' : '') + usd(pnl)} color={pnlColor} />
        <Stat label="POS" value={String(activeTrades)} />
      </div>

      {/* Right: news warn · clock · phosphor · status */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        {(newsFailed || activeBlackout) && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
            <span
              style={{
                width: '7px',
                height: '7px',
                background: newsFailed ? 'var(--color-sell)' : 'var(--color-pending)',
                boxShadow: `0 0 5px ${newsFailed ? 'var(--color-sell)' : 'var(--color-pending)'}`,
              }}
            />
            <span
              style={{
                fontSize: '9px',
                fontWeight: 700,
                letterSpacing: '0.08em',
                textTransform: 'uppercase',
                color: newsFailed ? 'var(--color-sell)' : 'var(--color-pending)',
                whiteSpace: 'nowrap',
              }}
            >
              {newsFailed ? '[NEWS FEED DOWN]' : `[BLACKOUT ${activeBlackout?.currency}]`}
            </span>
          </div>
        )}
        <span
          style={{
            fontSize: '10px',
            fontVariantNumeric: 'tabular-nums',
            letterSpacing: '0.05em',
            color: 'var(--text-muted)',
            whiteSpace: 'nowrap',
          }}
        >
          {clock}
        </span>
        {divider}
        <PhosphorPicker />
      </div>
    </header>
  );
}
