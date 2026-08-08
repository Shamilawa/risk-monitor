import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Panel, TermButton } from '../ui/Terminal';
import { duration, filterKey, filterQuery, num, pct, signedPct, signedR, signedUsd } from './format';
import type {
  BreakdownDimension,
  BreakdownRow,
  JournalBreakdown,
  JournalFilters,
} from '../../types';

/* Tables rather than charts, on purpose. This is the panel you scan to find which EA or
   session is bleeding, and scanning is what a sorted table is for — a bar chart of 20
   magic numbers answers nothing faster. */

const DIMENSIONS: { key: BreakdownDimension; label: string }[] = [
  { key: 'magic', label: 'By EA' },
  { key: 'symbol', label: 'Symbol' },
  { key: 'direction', label: 'Direction' },
  { key: 'hour', label: 'Hour' },
  { key: 'weekday', label: 'Weekday' },
  { key: 'duration', label: 'Duration' },
];

type SortKey =
  | 'label' | 'trades' | 'net_pnl' | 'net_pnl_pct' | 'win_rate' | 'profit_factor' | 'expectancy_r';

const COLUMNS: { key: SortKey; label: string; align: 'left' | 'right' }[] = [
  { key: 'label', label: '', align: 'left' },
  { key: 'trades', label: 'Trades', align: 'right' },
  { key: 'net_pnl', label: 'Net P&L', align: 'right' },
  { key: 'net_pnl_pct', label: 'Return', align: 'right' },
  { key: 'win_rate', label: 'Win %', align: 'right' },
  { key: 'profit_factor', label: 'PF', align: 'right' },
  { key: 'expectancy_r', label: 'Exp R', align: 'right' },
];

const th: React.CSSProperties = {
  fontSize: '9px',
  fontWeight: 700,
  letterSpacing: '0.08em',
  textTransform: 'uppercase',
  color: 'var(--text-muted)',
  padding: '6px 8px',
  borderBottom: '1px solid var(--border-color)',
  whiteSpace: 'nowrap',
  cursor: 'pointer',
  userSelect: 'none',
};

const td: React.CSSProperties = {
  fontSize: '11px',
  padding: '5px 8px',
  fontVariantNumeric: 'tabular-nums',
  whiteSpace: 'nowrap',
  borderBottom: '1px solid var(--border-color)',
};

const fetchBreakdown = async (id: number, by: BreakdownDimension, f: JournalFilters) => {
  const res = await fetch(`/api/journal/${id}/breakdown?${filterQuery(f, { by })}`);
  if (!res.ok) throw new Error('breakdown failed');
  return res.json() as Promise<JournalBreakdown>;
};

/** Signed P&L bar so relative size is readable without doing arithmetic. */
function PnlBar({ value, max }: { value: number; max: number }) {
  const w = max > 0 ? Math.min(100, (Math.abs(value) / max) * 100) : 0;
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '6px' }}>
      <span style={{ color: value >= 0 ? 'var(--color-buy)' : 'var(--color-sell)' }}>{signedUsd(value)}</span>
      <span
        style={{
          width: '46px',
          height: '6px',
          background: 'var(--bg-app)',
          border: '1px solid var(--border-color)',
          position: 'relative',
          flexShrink: 0,
        }}
      >
        <span
          style={{
            position: 'absolute',
            inset: 0,
            width: `${w}%`,
            background: value >= 0 ? 'var(--color-buy)' : 'var(--color-sell)',
            opacity: 0.55,
          }}
        />
      </span>
    </div>
  );
}

export function Breakdowns({
  instanceId,
  filters,
  onDrill,
}: {
  instanceId: number;
  filters: JournalFilters;
  /** Clicking a row rescopes the entire page, not just this panel. */
  onDrill: (patch: Partial<JournalFilters>) => void;
}) {
  const [by, setBy] = useState<BreakdownDimension>('magic');
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: 'net_pnl', dir: 1 });

  const { data, isLoading } = useQuery({
    queryKey: ['journal-breakdown', instanceId, by, ...filterKey(filters)],
    queryFn: () => fetchBreakdown(instanceId, by, filters),
  });

  const rows = useMemo(() => {
    const list = [...(data?.rows ?? [])];
    list.sort((a, b) => {
      const av = a[sort.key as keyof BreakdownRow];
      const bv = b[sort.key as keyof BreakdownRow];
      // Nulls always sort last regardless of direction — an uncomputable metric is not
      // "worst", it is absent, and burying it keeps the ranking honest.
      if (av === null && bv === null) return 0;
      if (av === null) return 1;
      if (bv === null) return -1;
      if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * sort.dir;
      return String(av).localeCompare(String(bv)) * sort.dir;
    });
    return list;
  }, [data, sort]);

  const maxAbs = useMemo(
    () => rows.reduce((mx, r) => Math.max(mx, Math.abs(r.net_pnl)), 0),
    [rows],
  );

  const drillFor = (row: BreakdownRow): Partial<JournalFilters> | null => {
    if (by === 'magic') return { magic: Number(row.key) };
    if (by === 'symbol') return { symbol: String(row.key) };
    if (by === 'direction') return { direction: row.key === 'LONG' ? 0 : 1 };
    return null; // hour/weekday/duration aren't stored filters — drilling would lie
  };

  return (
    <Panel
      title="Breakdown"
      actions={
        <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
          {DIMENSIONS.map((d) => (
            <TermButton key={d.key} active={by === d.key} onClick={() => setBy(d.key)}>
              {d.label}
            </TermButton>
          ))}
        </div>
      }
      bodyStyle={{ padding: 0, overflowX: 'auto' }}
    >
      {isLoading ? (
        <div style={{ padding: '20px', color: 'var(--text-muted)', fontSize: '11px' }}>Loading…</div>
      ) : rows.length === 0 ? (
        <div style={{ padding: '20px', color: 'var(--text-muted)', fontSize: '11px' }}>
          No trades in this window.
        </div>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '620px' }}>
          <thead>
            <tr>
              {COLUMNS.map((col) => (
                <th
                  key={col.key}
                  style={{ ...th, textAlign: col.align }}
                  onClick={() =>
                    setSort((s) => (s.key === col.key ? { key: col.key, dir: (s.dir * -1) as 1 | -1 } : { key: col.key, dir: 1 }))
                  }
                >
                  {col.key === 'label' ? DIMENSIONS.find((d) => d.key === by)?.label : col.label}
                  {sort.key === col.key ? (sort.dir === 1 ? ' ▲' : ' ▼') : ''}
                </th>
              ))}
              <th style={{ ...th, textAlign: 'right', cursor: 'default' }}>Avg Hold</th>
              <th style={{ ...th, textAlign: 'right', cursor: 'default' }}>R Cov</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const drill = drillFor(r);
              return (
                <tr
                  key={String(r.key)}
                  onClick={() => drill && onDrill(drill)}
                  style={{ cursor: drill ? 'pointer' : 'default' }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--bg-toolbar)')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                >
                  <td style={{ ...td, color: 'var(--text-main)' }}>
                    {r.label}
                    {r.hint ? (
                      <span style={{ color: 'var(--text-muted)', marginLeft: '6px', fontSize: '9px' }}>
                        {r.hint.slice(0, 24)}
                      </span>
                    ) : null}
                  </td>
                  <td style={{ ...td, textAlign: 'right', color: 'var(--text-muted)' }}>{r.trades}</td>
                  <td style={{ ...td, textAlign: 'right' }}>
                    <PnlBar value={r.net_pnl} max={maxAbs} />
                  </td>
                  <td
                    style={{
                      ...td,
                      textAlign: 'right',
                      color: r.net_pnl >= 0 ? 'var(--color-buy)' : 'var(--color-sell)',
                    }}
                  >
                    {signedPct(r.net_pnl_pct)}
                  </td>
                  <td style={{ ...td, textAlign: 'right', color: 'var(--text-main)' }}>{pct(r.win_rate)}</td>
                  <td
                    style={{
                      ...td,
                      textAlign: 'right',
                      color:
                        r.profit_factor === null
                          ? 'var(--text-muted)'
                          : r.profit_factor >= 1
                            ? 'var(--color-buy)'
                            : 'var(--color-sell)',
                    }}
                  >
                    {num(r.profit_factor)}
                  </td>
                  <td
                    style={{
                      ...td,
                      textAlign: 'right',
                      color:
                        r.expectancy_r === null
                          ? 'var(--text-muted)'
                          : r.expectancy_r >= 0
                            ? 'var(--color-buy)'
                            : 'var(--color-sell)',
                    }}
                  >
                    {signedR(r.expectancy_r)}
                  </td>
                  <td style={{ ...td, textAlign: 'right', color: 'var(--text-muted)' }}>
                    {duration(r.avg_hold_sec)}
                  </td>
                  <td style={{ ...td, textAlign: 'right', color: 'var(--text-muted)' }}>
                    {pct(r.r_coverage_pct, 0)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </Panel>
  );
}
