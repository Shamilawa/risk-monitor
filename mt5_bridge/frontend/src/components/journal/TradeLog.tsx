import { Fragment, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Field, Panel, StatusTag, TermButton, TermInput, TermSelect } from '../ui/Terminal';
import {
  duration, filterKey, filterQuery, getJson, moneyPct, num, signedPct, signedR, signedUsd, usd,
} from './format';
import type { BackfillStatus, JournalFilters, JournalTrade, JournalTrades } from '../../types';

/* The journal proper. Every filter on the page narrows this list, and a row expands into
   the full anatomy of the trade — prices, protection, cost breakdown, and your notes. */

const PAGE = 100;

const th: React.CSSProperties = {
  fontSize: '9px',
  fontWeight: 700,
  letterSpacing: '0.08em',
  textTransform: 'uppercase',
  color: 'var(--text-muted)',
  padding: '6px 8px',
  borderBottom: '1px solid var(--border-color)',
  whiteSpace: 'nowrap',
  textAlign: 'left',
};

const td: React.CSSProperties = {
  fontSize: '11px',
  padding: '5px 8px',
  fontVariantNumeric: 'tabular-nums',
  whiteSpace: 'nowrap',
  borderBottom: '1px solid var(--border-color)',
};

const fetchTrades = async (id: number, f: JournalFilters, offset: number) => {
  const res = await fetch(`/api/journal/${id}/trades?${filterQuery(f, { limit: PAGE, offset })}`);
  if (!res.ok) throw new Error('trades failed');
  return res.json() as Promise<JournalTrades>;
};

function Detail({ t, instanceId }: { t: JournalTrade; instanceId: number }) {
  const qc = useQueryClient();
  const [tags, setTags] = useState(t.tags);
  const [grade, setGrade] = useState(t.grade);
  const [note, setNote] = useState(t.note);

  const save = useMutation({
    mutationFn: async () => {
      const res = await fetch(`/api/journal/${instanceId}/annotation`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ position_id: t.position_id, tags, grade, note }),
      });
      if (!res.ok) throw new Error('save failed');
      return res.json();
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['journal-trades'] }),
  });

  const rows: [string, string][] = [
    ['Opened', t.open_label ?? 'n/a'],
    ['Closed', t.close_label],
    ['Duration', duration(t.duration_sec)],
    ['Entry price', t.entry_price ? t.entry_price.toFixed(5) : 'n/a'],
    ['Exit price', t.exit_price ? t.exit_price.toFixed(5) : 'n/a'],
    ['SL at open', t.sl_at_open ? t.sl_at_open.toFixed(5) : 'none'],
    ['TP at open', t.tp_at_open ? t.tp_at_open.toFixed(5) : 'none'],
    [
      'Risk at open',
      t.entry_risk_usd
        ? `$${usd(t.entry_risk_usd)}${t.risk_pct !== null ? ` · ${t.risk_pct.toFixed(2)}% of capital` : ''}`
        : 'n/a',
    ],
    ['R multiple', signedR(t.r_multiple)],
    // null = not backfilled yet; 0 is a real value (never went against you), so they read
    // differently on purpose.
    ['MAE (worst)', t.mae_usd === null ? 'not backfilled' : `${signedUsd(t.mae_usd)}${t.mae_r !== null ? `  (${t.mae_r.toFixed(2)}R)` : ''}`],
    ['MFE (best)', t.mfe_usd === null ? 'not backfilled' : `${signedUsd(t.mfe_usd)}${t.mfe_r !== null ? `  (${t.mfe_r.toFixed(2)}R)` : ''}`],
    ['Gross P&L', signedUsd(t.raw_profit)],
    ['Commission', signedUsd(t.commission)],
    ['Swap', signedUsd(t.swap)],
    ['Net P&L', moneyPct(t.profit, t.profit_pct)],
    ['Volume', num(t.volume, 2)],
    ['Magic', t.magic === null ? 'n/a' : String(t.magic)],
    ['Comment', t.comment || '—'],
    ['Deal ticket', String(t.ticket)],
    ['Position ID', t.position_id === null ? 'not synced' : String(t.position_id)],
  ];

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(280px, 1.4fr) minmax(240px, 1fr)',
        gap: '16px',
        padding: '10px 12px 14px',
        background: 'var(--bg-app)',
        borderBottom: '1px solid var(--border-color)',
      }}
    >
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '2px 14px' }}>
        {rows.map(([k, v]) => (
          <div key={k} style={{ display: 'flex', justifyContent: 'space-between', gap: '10px', fontSize: '10px' }}>
            <span style={{ color: 'var(--text-muted)' }}>{k}</span>
            <span style={{ color: 'var(--text-main)', fontVariantNumeric: 'tabular-nums' }}>{v}</span>
          </div>
        ))}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {t.position_id === null ? (
          // Annotations key on position_id, which only exists after a post-Phase-0 sync.
          // Better to say so than to silently drop what the user types.
          <div style={{ fontSize: '10px', color: 'var(--color-pending)', lineHeight: 1.5 }}>
            Notes need a position ID, which this trade does not have yet. It was logged before the
            journal sync change — run a log resync and it will attach.
          </div>
        ) : (
          <>
            <Field label="Tags" hint="comma separated">
              <TermInput value={tags} onChange={(e) => setTags(e.target.value)} placeholder="breakout, london" />
            </Field>
            <Field label="Grade">
              <TermSelect value={grade} onChange={(e) => setGrade(e.target.value)}>
                <option value="">—</option>
                {['A', 'B', 'C', 'D'].map((g) => (
                  <option key={g} value={g}>
                    {g}
                  </option>
                ))}
              </TermSelect>
            </Field>
            <Field label="Note">
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                rows={3}
                style={{
                  width: '100%',
                  background: 'var(--bg-app)',
                  color: 'var(--text-main)',
                  border: '1px solid var(--border-color)',
                  padding: '6px 8px',
                  fontFamily: 'inherit',
                  fontSize: '11px',
                  outline: 'none',
                  boxSizing: 'border-box',
                  resize: 'vertical',
                }}
              />
            </Field>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              <TermButton variant="solid" onClick={() => save.mutate()} disabled={save.isPending}>
                {save.isPending ? 'Saving…' : 'Save'}
              </TermButton>
              {save.isSuccess && <StatusTag label="SAVED" tone="success" />}
              {save.isError && <StatusTag label="FAILED" tone="error" />}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/** Kicks off the M1-bar reconstruction of MAE/MFE and polls until it finishes.
 * Runs server-side in a background thread that takes mt5_lock per trade, so it never
 * stalls the live poller. */
function BackfillControl({ instanceId }: { instanceId: number }) {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ['journal-backfill', instanceId],
    queryFn: () => getJson<BackfillStatus>(`/api/journal/${instanceId}/backfill_status`),
    // Only poll while work is in flight; idle pages shouldn't hit the server every 2s.
    refetchInterval: (q) => (q.state.data?.status === 'RUNNING' ? 2000 : false),
    retry: false,
  });

  const start = useMutation({
    mutationFn: async () => {
      const res = await fetch(`/api/journal/${instanceId}/backfill_mae`, { method: 'POST' });
      if (!res.ok) throw new Error('backfill failed to start');
      return res.json();
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['journal-backfill', instanceId] });
      qc.invalidateQueries({ queryKey: ['journal-distribution'] });
    },
  });

  if (!data) return null;
  const running = data.status === 'RUNNING';

  if (running) {
    const done = data.done ?? 0;
    const total = data.total ?? 0;
    return (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
        <StatusTag label="BACKFILL" tone="warning" />
        <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
          MAE/MFE {done}/{total}
        </span>
      </span>
    );
  }

  if (data.pending === 0) {
    return data.filled > 0 ? <StatusTag label={`MAE/MFE ${data.filled}`} tone="success" /> : null;
  }

  return (
    <TermButton
      onClick={() => start.mutate()}
      disabled={start.isPending}
      title="Reconstruct max adverse/favourable excursion from M1 bars for trades that lack it"
    >
      {start.isPending ? 'Starting…' : `Backfill MAE/MFE (${data.pending})`}
    </TermButton>
  );
}

export function TradeLog({ instanceId, filters }: { instanceId: number; filters: JournalFilters }) {
  const [offset, setOffset] = useState(0);
  const [openId, setOpenId] = useState<number | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ['journal-trades', instanceId, offset, ...filterKey(filters)],
    queryFn: () => fetchTrades(instanceId, filters, offset),
  });

  const trades = data?.trades ?? [];
  const total = data?.total ?? 0;

  return (
    <Panel
      title="Trade Log"
      actions={
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '10px', color: 'var(--text-muted)' }}>
          <BackfillControl instanceId={instanceId} />
          <span>
            {total === 0 ? '0' : `${offset + 1}–${Math.min(offset + PAGE, total)}`} of {total}
          </span>
          <TermButton disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
            ‹ Prev
          </TermButton>
          <TermButton disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>
            Next ›
          </TermButton>
        </div>
      }
      bodyStyle={{ padding: 0, overflowX: 'auto' }}
    >
      {isLoading ? (
        <div style={{ padding: '20px', color: 'var(--text-muted)', fontSize: '11px' }}>Loading…</div>
      ) : trades.length === 0 ? (
        <div style={{ padding: '20px', color: 'var(--text-muted)', fontSize: '11px' }}>
          No trades match the current filters.
        </div>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '860px' }}>
          <thead>
            <tr>
              {['Closed', 'Symbol', 'Side', 'Vol', 'Entry', 'Exit', 'Net P&L', '%', 'R', 'Hold', 'EA', ''].map(
                (h, i) => (
                  <th key={h + i} style={{ ...th, textAlign: i >= 3 && i <= 9 ? 'right' : 'left' }}>
                    {h}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            {trades.map((t) => {
              const open = openId === t.ticket;
              return (
                <Fragment key={t.ticket}>
                  <tr
                    onClick={() => setOpenId(open ? null : t.ticket)}
                    style={{ cursor: 'pointer', background: open ? 'var(--bg-toolbar)' : 'transparent' }}
                  >
                    <td style={{ ...td, color: 'var(--text-muted)' }}>{t.close_label}</td>
                    <td style={{ ...td, color: 'var(--text-main)' }}>{t.symbol}</td>
                    <td style={{ ...td }}>
                      <StatusTag label={t.side} tone={t.side === 'LONG' ? 'success' : 'error'} />
                    </td>
                    <td style={{ ...td, textAlign: 'right', color: 'var(--text-muted)' }}>{t.volume.toFixed(2)}</td>
                    <td style={{ ...td, textAlign: 'right', color: 'var(--text-muted)' }}>
                      {t.entry_price ? t.entry_price.toFixed(5) : '—'}
                    </td>
                    <td style={{ ...td, textAlign: 'right', color: 'var(--text-muted)' }}>
                      {t.exit_price ? t.exit_price.toFixed(5) : '—'}
                    </td>
                    <td
                      style={{
                        ...td,
                        textAlign: 'right',
                        fontWeight: 700,
                        color: t.profit > 0 ? 'var(--color-buy)' : t.profit < 0 ? 'var(--color-sell)' : 'var(--text-muted)',
                      }}
                    >
                      {signedUsd(t.profit)}
                    </td>
                    <td
                      style={{
                        ...td,
                        textAlign: 'right',
                        color:
                          t.profit > 0 ? 'var(--color-buy)' : t.profit < 0 ? 'var(--color-sell)' : 'var(--text-muted)',
                      }}
                    >
                      {t.profit_pct === null ? '—' : signedPct(t.profit_pct)}
                    </td>
                    <td
                      style={{
                        ...td,
                        textAlign: 'right',
                        color:
                          t.r_multiple === null
                            ? 'var(--text-muted)'
                            : t.r_multiple >= 0
                              ? 'var(--color-buy)'
                              : 'var(--color-sell)',
                      }}
                    >
                      {t.r_multiple === null ? '—' : signedR(t.r_multiple)}
                    </td>
                    <td style={{ ...td, textAlign: 'right', color: 'var(--text-muted)' }}>
                      {duration(t.duration_sec)}
                    </td>
                    <td style={{ ...td, color: 'var(--text-muted)' }}>{t.magic ?? '—'}</td>
                    <td style={{ ...td, color: 'var(--text-muted)' }}>
                      {!t.sl_at_open && <StatusTag label="NO SL" tone="error" />}
                      {t.grade && <StatusTag label={t.grade} tone="accent" style={{ marginLeft: '4px' }} />}
                      {t.tags && <StatusTag label="TAG" tone="muted" style={{ marginLeft: '4px' }} />}
                    </td>
                  </tr>
                  {open && (
                    <tr>
                      <td colSpan={12} style={{ padding: 0 }}>
                        <Detail t={t} instanceId={instanceId} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      )}
    </Panel>
  );
}
