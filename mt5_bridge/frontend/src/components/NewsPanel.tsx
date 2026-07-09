import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { NewsToday, BlockedAction } from '../types';
import { computeWindowState } from '../utils/news';

const fetchNewsToday = async (): Promise<NewsToday> => {
  const res = await fetch('/api/news/today');
  return res.json();
};

const fetchBlockedActions = async (): Promise<BlockedAction[]> => {
  const res = await fetch('/api/news/blocked_actions?status=PENDING');
  return res.json();
};

interface ManualRow {
  title: string;
  currency: string;
  date: string;
  offset_minutes: number;
}

const TIMEZONE_OFFSETS = [
  { label: 'UTC', minutes: 0 },
  { label: 'Local (browser)', minutes: -new Date().getTimezoneOffset() },
  { label: 'EST (UTC-5)', minutes: -300 },
  { label: 'EDT (UTC-4)', minutes: -240 },
  { label: 'CET (UTC+1)', minutes: 60 },
  { label: 'CEST (UTC+2)', minutes: 120 },
];

const NewsPanel = () => {
  const queryClient = useQueryClient();
  const { data: newsToday } = useQuery<NewsToday>({
    queryKey: ['news', 'today'],
    queryFn: fetchNewsToday,
    refetchInterval: 30000,
  });
  const { data: blockedActions = [] } = useQuery<BlockedAction[]>({
    queryKey: ['news', 'blockedActions'],
    queryFn: fetchBlockedActions,
    refetchInterval: 30000,
  });

  const [manualRows, setManualRows] = useState<ManualRow[]>([]);

  const submitManualMutation = useMutation({
    mutationFn: async (events: ManualRow[]) => {
      const res = await fetch('/api/news/manual', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ events }),
      });
      if (!res.ok) throw new Error('Failed to submit manual news list.');
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['news', 'today'] });
      setManualRows([]);
    },
  });

  const executeActionMutation = useMutation({
    mutationFn: async (id: number) => {
      const res = await fetch(`/api/news/blocked_actions/${id}/execute`, { method: 'POST' });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || 'Failed to execute action.');
      }
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['news', 'blockedActions'] }),
    onError: (err: Error) => alert(err.message),
  });

  const dismissActionMutation = useMutation({
    mutationFn: async (id: number) => {
      const res = await fetch(`/api/news/blocked_actions/${id}/dismiss`, { method: 'POST' });
      if (!res.ok) throw new Error('Failed to dismiss action.');
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['news', 'blockedActions'] }),
  });

  const handleAddManualRow = () => {
    setManualRows((prev) => [...prev, { title: '', currency: '', date: '', offset_minutes: 0 }]);
  };

  const handleManualRowChange = (idx: number, field: keyof ManualRow, value: string | number) => {
    setManualRows((prev) => prev.map((row, i) => (i === idx ? { ...row, [field]: value } : row)));
  };

  const handleRemoveManualRow = (idx: number) => {
    setManualRows((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleSubmitManual = () => {
    const valid = manualRows.filter((r) => r.title && r.currency && r.date);
    if (valid.length === 0) {
      alert('Add at least one complete event (title, currency, date/time).');
      return;
    }
    submitManualMutation.mutate(valid);
  };

  const events = newsToday?.events || [];
  const status = newsToday?.status || 'FAILED';
  const statusColor = status === 'AUTO' ? 'var(--color-buy)' : status === 'MANUAL' ? 'var(--color-active)' : 'var(--color-sell)';
  const statusLabel = status === 'AUTO' ? 'Auto-Fetched' : status === 'MANUAL' ? 'Manual Entry Active' : 'FETCH FAILED';

  return (
    <section className="pane" style={{ flexShrink: 0, display: 'flex', flexDirection: 'column', maxHeight: '320px' }}>
      <div className="pane-header" style={{ fontWeight: 'normal', color: 'var(--text-muted)' }}>
        <span>PROP-FIRM NEWS BLACKOUT DESK</span>
        <span style={{ color: statusColor, fontWeight: 'bold' }}>
          {statusLabel}
          {newsToday?.fetched_at ? ` — Last update ${new Date(newsToday.fetched_at * 1000).toLocaleTimeString()}` : ''}
        </span>
      </div>

      <div style={{ padding: '8px', display: 'flex', flexDirection: 'column', gap: '10px', overflowY: 'auto' }}>

        {status === 'FAILED' && (
          <div style={{ background: 'rgba(231, 76, 60, 0.1)', border: '1px solid var(--color-sell)', padding: '8px', fontSize: '10px', color: 'var(--color-sell)' }}>
            ⚠️ Auto-fetch failed. ALL PropFirm instances are blocked from trading (open/modify/close) until this is resolved. Submit today's high-impact events manually below.
          </div>
        )}

        {/* Today's events table */}
        <div style={{ border: '1px solid var(--border-color)', background: 'var(--bg-app)', maxHeight: '140px', overflowY: 'auto' }}>
          <table className="data-grid" style={{ width: '100%' }}>
            <thead>
              <tr>
                <th style={{ width: '80px' }}>Time</th>
                <th style={{ width: '70px' }}>Currency</th>
                <th>Title</th>
                <th style={{ width: '90px', textAlign: 'center' }}>State</th>
              </tr>
            </thead>
            <tbody>
              {events.length === 0 ? (
                <tr>
                  <td colSpan={4} style={{ textAlign: 'center', padding: '12px', color: 'var(--text-muted)' }}>
                    No high-impact events today.
                  </td>
                </tr>
              ) : (
                events.map((w, i) => {
                  const state = computeWindowState(w);
                  const stateColor = state === 'active' ? 'var(--color-sell)' : state === 'upcoming' ? 'var(--color-active)' : 'var(--text-muted)';
                  return (
                    <tr key={i}>
                      <td>{new Date(w.event_time * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</td>
                      <td style={{ fontWeight: 'bold' }}>{w.currency}</td>
                      <td>{w.title}</td>
                      <td style={{ textAlign: 'center', color: stateColor, fontWeight: 'bold' }}>
                        {state === 'active' ? '⛔ ACTIVE' : state === 'upcoming' ? 'Upcoming' : 'Passed'}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Manual entry form */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '9px', color: 'var(--text-muted)', fontWeight: 'bold' }}>MANUAL NEWS ENTRY (used when auto-fetch fails)</span>
            <button className="btn-toolbar" style={{ fontSize: '9px', padding: '1px 6px', borderColor: 'var(--color-buy)', color: 'var(--color-buy)' }} onClick={handleAddManualRow}>
              + Add Row
            </button>
          </div>
          {manualRows.length > 0 && (
            <>
              {manualRows.map((row, idx) => (
                <div key={idx} style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
                  <input
                    type="text"
                    placeholder="Title"
                    value={row.title}
                    onChange={(e) => handleManualRowChange(idx, 'title', e.target.value)}
                    style={{ flex: 2, background: 'var(--bg-app)', color: 'var(--text-main)', border: '1px solid var(--border-color)', padding: '3px', fontSize: '10px', outline: 'none' }}
                  />
                  <input
                    type="text"
                    placeholder="Currency (e.g. USD)"
                    value={row.currency}
                    onChange={(e) => handleManualRowChange(idx, 'currency', e.target.value.toUpperCase())}
                    style={{ flex: 1, background: 'var(--bg-app)', color: 'var(--text-main)', border: '1px solid var(--border-color)', padding: '3px', fontSize: '10px', outline: 'none' }}
                  />
                  <input
                    type="datetime-local"
                    value={row.date}
                    onChange={(e) => handleManualRowChange(idx, 'date', e.target.value)}
                    style={{ flex: 2, background: 'var(--bg-app)', color: 'var(--text-main)', border: '1px solid var(--border-color)', padding: '3px', fontSize: '10px', outline: 'none' }}
                  />
                  <select
                    value={row.offset_minutes}
                    onChange={(e) => handleManualRowChange(idx, 'offset_minutes', parseInt(e.target.value, 10))}
                    style={{ flex: 1, background: 'var(--bg-app)', color: 'var(--text-main)', border: '1px solid var(--border-color)', padding: '3px', fontSize: '10px', outline: 'none' }}
                  >
                    {TIMEZONE_OFFSETS.map((tz) => (
                      <option key={tz.label} value={tz.minutes}>{tz.label}</option>
                    ))}
                  </select>
                  <button
                    className="btn-toolbar"
                    style={{ padding: '2px 5px', fontSize: '9px', color: 'var(--color-sell)', borderColor: 'transparent' }}
                    onClick={() => handleRemoveManualRow(idx)}
                  >
                    &times;
                  </button>
                </div>
              ))}
              <button
                className="btn-toolbar"
                style={{ alignSelf: 'flex-start', borderColor: 'var(--color-active)', color: 'var(--color-active)', fontWeight: 'bold' }}
                onClick={handleSubmitManual}
                disabled={submitManualMutation.isPending}
              >
                Submit Manual List
              </button>
            </>
          )}
        </div>

        {/* Blocked actions table */}
        {blockedActions.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <span style={{ fontSize: '9px', color: 'var(--color-sell)', fontWeight: 'bold' }}>⚠ BLOCKED ACTIONS REQUIRING MANUAL REVIEW</span>
            <div style={{ border: '1px solid var(--color-sell)', background: 'var(--bg-app)', maxHeight: '160px', overflowY: 'auto' }}>
              <table className="data-grid" style={{ width: '100%' }}>
                <thead>
                  <tr>
                    <th>Instance</th>
                    <th style={{ width: '70px' }}>Type</th>
                    <th>Symbol</th>
                    <th>Ticket</th>
                    <th>Reason</th>
                    <th style={{ width: '130px', textAlign: 'center' }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {blockedActions.map((a) => (
                    <tr key={a.id}>
                      <td>{a.instance_name}</td>
                      <td style={{ fontWeight: 'bold', color: a.action_type === 'CLOSE' ? 'var(--color-sell)' : 'var(--color-active)' }}>{a.action_type}</td>
                      <td>{a.symbol}</td>
                      <td>{a.ticket}</td>
                      <td style={{ fontSize: '9px', color: 'var(--text-muted)' }}>{a.reason}</td>
                      <td style={{ textAlign: 'center' }}>
                        <div style={{ display: 'flex', gap: '4px', justifyContent: 'center' }}>
                          <button
                            className="btn-toolbar"
                            style={{ fontSize: '9px', padding: '1px 5px', borderColor: 'var(--color-buy)', color: 'var(--color-buy)' }}
                            onClick={() => executeActionMutation.mutate(a.id)}
                            disabled={executeActionMutation.isPending}
                          >
                            Execute Now
                          </button>
                          <button
                            className="btn-toolbar"
                            style={{ fontSize: '9px', padding: '1px 5px', borderColor: 'var(--border-color)', color: 'var(--text-muted)' }}
                            onClick={() => dismissActionMutation.mutate(a.id)}
                            disabled={dismissActionMutation.isPending}
                          >
                            Dismiss
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

      </div>
    </section>
  );
};

export default NewsPanel;
