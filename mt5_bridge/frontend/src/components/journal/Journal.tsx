import { useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Page } from '../shell/Page';
import { Panel, SectionLabel, StatusTag, TermButton, TermSelect } from '../ui/Terminal';
import { useStore } from '../../store/useStore';
import { VerdictBar } from './VerdictBar';
import { EquityUnderwater } from './EquityUnderwater';
import { Breakdowns } from './Breakdowns';
import { CalendarHeatmap } from './CalendarHeatmap';
import { TradeLog } from './TradeLog';
import { ApiError, explainError, filterKey, filterQuery, getJson, signedUsd, usd } from './format';
import type {
  JournalEquity,
  JournalFilterOptions,
  JournalFilters,
  JournalSummary,
} from '../../types';

/* Per-instance trading journal, reached by clicking a Portfolio card.

   One period selector and one filter object govern the whole page — click an EA row or a
   calendar day and every panel rescopes together. Panels that disagreed about what they
   were showing would be worse than no panels at all. */

const PERIODS = [
  { label: '7D', value: 7 },
  { label: '30D', value: 30 },
  { label: '90D', value: 90 },
  { label: '180D', value: 180 },
  { label: '1Y', value: 365 },
  { label: 'ALL', value: 0 },
];

export default function Journal() {
  const { id } = useParams();
  const navigate = useNavigate();
  const instanceId = Number(id);

  const [filterState, setFilterState] = useState<JournalFilters>({ days: 90 });

  // Live balance comes off the socket the app already runs. It lets the backend express
  // drawdown and every P&L figure as a real percentage of the account, and it is folded
  // into the filter object so that *all* panels send the same one — percentages derived
  // from different denominators would not add up.
  const instances = useStore((s) => s.instances || []);
  const live = instances.find((i) => i.id === instanceId);
  const balance = live?.balance;

  // Not memoised: every consumer keys off filterKey(), which is an array of primitives, so
  // a fresh object identity each render costs nothing and never triggers a refetch.
  const filters: JournalFilters = { ...filterState, balance };
  const balanceParam: Record<string, string> = balance !== undefined ? { balance: balance.toFixed(2) } : {};

  const { data: summary, isLoading, error } = useQuery({
    queryKey: ['journal-summary', instanceId, ...filterKey(filters), balance ?? null],
    queryFn: () =>
      getJson<JournalSummary>(`/api/journal/${instanceId}/summary?${filterQuery(filters, balanceParam)}`),
    enabled: Number.isFinite(instanceId),
    // A missing route or unmigrated DB will not fix itself on retry; failing fast keeps
    // the real reason on screen instead of burying it behind three silent retries.
    retry: false,
  });

  const { data: equity } = useQuery({
    queryKey: ['journal-equity', instanceId, ...filterKey(filters), balance ?? null],
    queryFn: () =>
      getJson<JournalEquity>(`/api/journal/${instanceId}/equity?${filterQuery(filters, balanceParam)}`),
    enabled: Number.isFinite(instanceId),
    retry: false,
  });

  const { data: options } = useQuery({
    queryKey: ['journal-filters', instanceId, filters.days],
    queryFn: () => getJson<JournalFilterOptions>(`/api/journal/${instanceId}/filters?days=${filters.days}`),
    enabled: Number.isFinite(instanceId),
    retry: false,
  });

  const patch = (p: Partial<JournalFilters>) => setFilterState((f) => ({ ...f, ...p }));

  /** Active narrowings, rendered as removable chips so it is always obvious what the
   * numbers on screen are actually describing. */
  const chips = useMemo(() => {
    const f = filterState;
    const out: { label: string; clear: () => void }[] = [];
    if (f.symbol) out.push({ label: `symbol: ${f.symbol}`, clear: () => patch({ symbol: undefined }) });
    if (f.magic !== undefined) out.push({ label: `EA: ${f.magic}`, clear: () => patch({ magic: undefined }) });
    if (f.direction !== undefined)
      out.push({ label: f.direction === 0 ? 'LONG only' : 'SHORT only', clear: () => patch({ direction: undefined }) });
    if (f.outcome) out.push({ label: `${f.outcome} only`, clear: () => patch({ outcome: undefined }) });
    if (f.date) out.push({ label: `day: ${f.date}`, clear: () => patch({ date: undefined }) });
    return out;
  }, [filterState]);

  if (!Number.isFinite(instanceId)) {
    return (
      <Page title="Journal">
        <div style={{ color: 'var(--color-sell)', fontSize: '12px' }}>Invalid instance id.</div>
      </Page>
    );
  }

  const inst = summary?.instance;

  return (
    <Page
      title={inst ? inst.name : 'Journal'}
      description="Closed-trade analytics for this account. Every panel honours the filters above."
      maxWidth={1600}
      actions={
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
          <TermButton onClick={() => navigate('/portfolio')}>‹ Portfolio</TermButton>
          {PERIODS.map((p) => (
            <TermButton key={p.value} active={filters.days === p.value} onClick={() => patch({ days: p.value })}>
              {p.label}
            </TermButton>
          ))}
        </div>
      }
    >
      {error ? (
        (() => {
          const { headline, detail } = explainError(error);
          return (
            <Panel title="Journal Unavailable" tone="error" bodyStyle={{ padding: '18px 20px' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', maxWidth: '620px' }}>
                <strong style={{ fontSize: '12px', color: 'var(--color-sell)' }}>{headline}</strong>
                <span style={{ fontSize: '11px', color: 'var(--text-muted)', lineHeight: 1.6 }}>{detail}</span>
                <code
                  style={{
                    fontSize: '10px',
                    color: 'var(--text-muted)',
                    background: 'var(--bg-app)',
                    border: '1px solid var(--border-color)',
                    padding: '6px 8px',
                    wordBreak: 'break-all',
                  }}
                >
                  {error instanceof ApiError ? `${error.status} ${error.url}` : String(error)}
                </code>
                <div style={{ display: 'flex', gap: '8px' }}>
                  <TermButton variant="solid" onClick={() => window.location.reload()}>
                    Reload
                  </TermButton>
                  <TermButton onClick={() => navigate('/portfolio')}>‹ Portfolio</TermButton>
                </div>
              </div>
            </Panel>
          );
        })()
      ) : isLoading || !summary ? (
        <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>Loading journal…</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          {/* Identity + live state */}
          <Panel
            title={
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                {inst?.name}
                {inst?.account_type === 'PROPFIRM' && <StatusTag label="PROPFIRM" tone="error" />}
                {inst?.copier_role === 'PROVIDER' && <StatusTag label="MASTER" tone="warning" />}
                {inst?.copier_role === 'CONSUMER' && <StatusTag label="SUB" tone="accent" />}
                {inst?.trade_locked && <StatusTag label="LOCKED" tone="error" />}
                {!live && <StatusTag label="OFFLINE" tone="muted" />}
              </span>
            }
            actions={
              <div style={{ display: 'flex', gap: '14px', fontSize: '10px', color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums' }}>
                {live ? (
                  <>
                    <span>
                      BAL <strong style={{ color: 'var(--text-main)' }}>${usd(live.balance || 0)}</strong>
                    </span>
                    <span>
                      EQ <strong style={{ color: 'var(--text-main)' }}>${usd(live.equity || 0)}</strong>
                    </span>
                    <span>
                      FLOAT{' '}
                      <strong
                        style={{
                          color: (live.equity || 0) - (live.balance || 0) >= 0 ? 'var(--color-buy)' : 'var(--color-sell)',
                        }}
                      >
                        {signedUsd((live.equity || 0) - (live.balance || 0))}
                      </strong>
                    </span>
                  </>
                ) : (
                  <span>No live connection — metrics are from stored history</span>
                )}
              </div>
            }
            bodyStyle={{ padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: '10px' }}
          >
            {/* Filter controls */}
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
              <TermSelect
                value={filters.symbol ?? ''}
                onChange={(e) => patch({ symbol: e.target.value || undefined })}
                style={{ width: '150px' }}
              >
                <option value="">All symbols</option>
                {(options?.symbols ?? []).map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </TermSelect>
              <TermSelect
                value={filters.magic ?? ''}
                onChange={(e) => patch({ magic: e.target.value === '' ? undefined : Number(e.target.value) })}
                style={{ width: '150px' }}
              >
                <option value="">All EAs</option>
                {(options?.magics ?? []).map((m) => (
                  <option key={m} value={m}>
                    magic {m}
                  </option>
                ))}
              </TermSelect>
              <TermSelect
                value={filters.direction ?? ''}
                onChange={(e) =>
                  patch({ direction: e.target.value === '' ? undefined : (Number(e.target.value) as 0 | 1) })
                }
                style={{ width: '130px' }}
              >
                <option value="">Both sides</option>
                <option value="0">Long only</option>
                <option value="1">Short only</option>
              </TermSelect>
              <TermSelect
                value={filters.outcome ?? ''}
                onChange={(e) => patch({ outcome: (e.target.value || undefined) as JournalFilters['outcome'] })}
                style={{ width: '130px' }}
              >
                <option value="">All outcomes</option>
                <option value="win">Wins</option>
                <option value="loss">Losses</option>
                <option value="scratch">Scratches</option>
              </TermSelect>
              {chips.length > 0 && (
                <TermButton onClick={() => setFilterState({ days: filters.days })}>Clear all</TermButton>
              )}
            </div>

            {chips.length > 0 && (
              <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                {chips.map((c) => (
                  <button
                    key={c.label}
                    onClick={c.clear}
                    style={{
                      fontFamily: 'inherit',
                      fontSize: '9px',
                      letterSpacing: '0.06em',
                      textTransform: 'uppercase',
                      background: 'var(--terminal-accent-soft)',
                      border: '1px solid var(--terminal-accent)',
                      color: 'var(--terminal-accent)',
                      padding: '3px 8px',
                      cursor: 'pointer',
                    }}
                  >
                    {c.label} ×
                  </button>
                ))}
              </div>
            )}
          </Panel>

          <SectionLabel>
            Verdict · {filters.days === 0 ? 'all history' : `last ${filters.days}d`}
            {summary.start_balance !== null ? ` · anchored to $${usd(summary.start_balance)} start balance` : ''}
          </SectionLabel>
          <VerdictBar m={summary.metrics} startBalance={summary.start_balance} />

          <Panel title="Equity & Drawdown" bodyStyle={{ padding: '10px 12px' }}>
            {equity ? (
              <EquityUnderwater data={equity} />
            ) : (
              <div style={{ padding: '20px', color: 'var(--text-muted)', fontSize: '11px' }}>Loading…</div>
            )}
          </Panel>

          <Breakdowns instanceId={instanceId} filters={filters} onDrill={patch} />

          <CalendarHeatmap instanceId={instanceId} filters={filters} onPickDay={(date) => patch({ date })} />

          <TradeLog instanceId={instanceId} filters={filters} />
        </div>
      )}
    </Page>
  );
}
