import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Panel, TermButton } from '../ui/Terminal';
import { filterKey, filterQuery, signedPct, signedUsd, usd } from './format';
import type { CalendarEntry, JournalCalendar, JournalFilters } from '../../types';

/* Month grid of daily P&L. Cheap to build, and the fastest way to spot a day-of-week or
   end-of-month pattern that a time-series chart flattens away. Clicking a day filters the
   whole page to that day. */

const DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

const fetchCalendar = async (id: number, f: JournalFilters) => {
  const res = await fetch(`/api/journal/${id}/calendar?${filterQuery(f)}`);
  if (!res.ok) throw new Error('calendar failed');
  return res.json() as Promise<JournalCalendar>;
};

/** Parsed as local parts, not `new Date(str)` — the latter reads a bare YYYY-MM-DD as UTC
 * and can shift the grid by a day. The backend already resolved the journal day. */
function parts(date: string) {
  const [y, m, d] = date.split('-').map(Number);
  return { y, m, d };
}

function monthKey(date: string) {
  return date.slice(0, 7);
}

function monthLabel(key: string) {
  const [y, m] = key.split('-').map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
}

export function CalendarHeatmap({
  instanceId,
  filters,
  onPickDay,
}: {
  instanceId: number;
  filters: JournalFilters;
  onPickDay: (date: string | undefined) => void;
}) {
  const { data, isLoading } = useQuery({
    queryKey: ['journal-calendar', instanceId, ...filterKey(filters)],
    queryFn: () => fetchCalendar(instanceId, filters),
  });

  const months = useMemo(() => {
    const set = new Set<string>();
    for (const e of data?.entries ?? []) set.add(monthKey(e.date));
    return Array.from(set).sort();
  }, [data]);

  const [monthIdx, setMonthIdx] = useState<number | null>(null);
  const activeIdx = monthIdx === null ? months.length - 1 : Math.min(monthIdx, months.length - 1);
  const activeMonth = months[activeIdx];

  const byDate = useMemo(() => {
    const map = new Map<string, CalendarEntry>();
    for (const e of data?.entries ?? []) map.set(e.date, e);
    return map;
  }, [data]);

  const maxAbs = useMemo(
    () => (data?.entries ?? []).reduce((mx, e) => Math.max(mx, Math.abs(e.profit)), 0),
    [data],
  );

  const cells = useMemo(() => {
    if (!activeMonth) return [];
    const [y, m] = activeMonth.split('-').map(Number);
    const firstDow = (new Date(y, m - 1, 1).getDay() + 6) % 7; // Monday-first
    const daysInMonth = new Date(y, m, 0).getDate();
    const out: (string | null)[] = Array(firstDow).fill(null);
    for (let d = 1; d <= daysInMonth; d++) {
      out.push(`${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`);
    }
    return out;
  }, [activeMonth]);

  const monthTotal = useMemo(() => {
    if (!activeMonth) return 0;
    return (data?.entries ?? [])
      .filter((e) => monthKey(e.date) === activeMonth)
      .reduce((s, e) => s + e.profit, 0);
  }, [data, activeMonth]);

  const bg = (profit: number) => {
    if (maxAbs === 0) return 'transparent';
    const intensity = Math.min(0.55, (Math.abs(profit) / maxAbs) * 0.55 + 0.08);
    return profit >= 0
      ? `rgba(0, 255, 102, ${intensity})`
      : `rgba(255, 59, 48, ${intensity})`;
  };

  return (
    <Panel
      title="Calendar"
      actions={
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          {filters.date && <TermButton onClick={() => onPickDay(undefined)}>Clear Day</TermButton>}
          <TermButton
            disabled={activeIdx <= 0}
            onClick={() => setMonthIdx(Math.max(0, activeIdx - 1))}
          >
            ‹
          </TermButton>
          <span style={{ fontSize: '10px', color: 'var(--text-muted)', minWidth: '110px', textAlign: 'center' }}>
            {activeMonth ? monthLabel(activeMonth) : '—'}
          </span>
          <TermButton
            disabled={activeIdx >= months.length - 1}
            onClick={() => setMonthIdx(Math.min(months.length - 1, activeIdx + 1))}
          >
            ›
          </TermButton>
        </div>
      }
      bodyStyle={{ padding: '10px' }}
    >
      {isLoading ? (
        <div style={{ color: 'var(--text-muted)', fontSize: '11px' }}>Loading…</div>
      ) : !activeMonth ? (
        <div style={{ color: 'var(--text-muted)', fontSize: '11px' }}>No trading days in this window.</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: '3px' }}>
            {DOW.map((d) => (
              <div
                key={d}
                style={{
                  fontSize: '9px',
                  letterSpacing: '0.08em',
                  textTransform: 'uppercase',
                  color: 'var(--text-muted)',
                  textAlign: 'center',
                  paddingBottom: '2px',
                }}
              >
                {d}
              </div>
            ))}
            {cells.map((date, i) => {
              if (!date) return <div key={`pad-${i}`} />;
              const entry = byDate.get(date);
              const selected = filters.date === date;
              return (
                <button
                  key={date}
                  onClick={() => entry && onPickDay(selected ? undefined : date)}
                  title={
                    entry
                      ? `${date} · ${signedUsd(entry.profit)} · ${entry.trades} trades`
                      : `${date} · no trades`
                  }
                  style={{
                    fontFamily: 'inherit',
                    background: entry ? bg(entry.profit) : 'transparent',
                    border: `1px solid ${selected ? 'var(--terminal-accent)' : 'var(--border-color)'}`,
                    padding: '4px 3px',
                    minHeight: '56px',
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'flex-start',
                    justifyContent: 'space-between',
                    cursor: entry ? 'pointer' : 'default',
                    color: 'var(--text-main)',
                    opacity: entry ? 1 : 0.35,
                  }}
                >
                  <span style={{ fontSize: '9px', color: 'var(--text-muted)' }}>{parts(date).d}</span>
                  {entry && (
                    <span
                      style={{
                        display: 'flex',
                        flexDirection: 'column',
                        fontSize: '9px',
                        fontWeight: 700,
                        lineHeight: 1.25,
                        fontVariantNumeric: 'tabular-nums',
                        color: entry.profit >= 0 ? 'var(--color-buy)' : 'var(--color-sell)',
                      }}
                    >
                      <span>
                        {entry.profit >= 0 ? '+' : '-'}
                        {usd(Math.abs(entry.profit))}
                      </span>
                      {entry.profit_pct !== null && (
                        <span style={{ fontWeight: 400, opacity: 0.8 }}>{signedPct(entry.profit_pct)}</span>
                      )}
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          <div
            style={{
              display: 'flex',
              gap: '14px',
              flexWrap: 'wrap',
              fontSize: '10px',
              color: 'var(--text-muted)',
              fontVariantNumeric: 'tabular-nums',
              borderTop: '1px solid var(--border-color)',
              paddingTop: '6px',
            }}
          >
            <span>
              Month:{' '}
              <strong style={{ color: monthTotal >= 0 ? 'var(--color-buy)' : 'var(--color-sell)' }}>
                {signedUsd(monthTotal)}
              </strong>
            </span>
            <span>Active days: {data?.active_days ?? 0}</span>
            {data?.best_day && (
              <span>
                Best {data.best_day.date}{' '}
                <strong style={{ color: 'var(--color-buy)' }}>{signedUsd(data.best_day.profit)}</strong>
              </span>
            )}
            {data?.worst_day && (
              <span>
                Worst {data.worst_day.date}{' '}
                <strong style={{ color: 'var(--color-sell)' }}>{signedUsd(data.worst_day.profit)}</strong>
              </span>
            )}
            <span>Days anchored to {data?.anchor === 'MACHINE' ? 'this machine' : data?.anchor}</span>
          </div>
        </div>
      )}
    </Panel>
  );
}
