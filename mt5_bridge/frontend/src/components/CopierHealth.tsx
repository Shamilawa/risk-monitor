import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { CopierIncident } from '../types';

const fetchIncidents = async (): Promise<CopierIncident[]> => {
  const res = await fetch('/api/copier/incidents');
  const json = await res.json();
  return json.incidents || [];
};

const SEVERITY_COLOR: Record<string, string> = {
  CRITICAL: 'var(--color-sell)',
  WARN: 'var(--color-active)',
  INFO: 'var(--text-muted)',
};

/** Incidents whose dedupe key ends in a local ticket can be closed from here. */
const CLOSEABLE = new Set(['CLOSE_NOT_MIRRORED', 'ORPHAN_POSITION', 'WRONG_DIRECTION']);
const RETRYABLE = new Set(['COPY_MISSING', 'COPY_REJECTED']);

const relTime = (epoch: number) => {
  const secs = Math.max(0, Math.floor(Date.now() / 1000 - epoch));
  if (secs < 60) return `${secs}s`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m`;
  return `${Math.floor(secs / 3600)}h ${Math.floor((secs % 3600) / 60)}m`;
};

const CopierHealth = () => {
  const queryClient = useQueryClient();
  const [showLog, setShowLog] = useState(false);
  const [logText, setLogText] = useState('');

  const { data: incidents = [] } = useQuery<CopierIncident[]>({
    queryKey: ['copier', 'incidents'],
    queryFn: fetchIncidents,
    refetchInterval: 15000,
  });

  const actionMutation = useMutation({
    mutationFn: async ({ id, action }: { id: number; action: string }) => {
      const res = await fetch(`/api/copier/incidents/${id}/${action}`, { method: 'POST' });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.error || 'Action failed.');
      return json.message as string;
    },
    onSuccess: (message) => {
      queryClient.invalidateQueries({ queryKey: ['copier', 'incidents'] });
      if (message) alert(message);
    },
    onError: (err: Error) => alert(err.message),
  });

  const openLog = async () => {
    const res = await fetch('/api/copier/issue_log');
    setLogText(await res.text());
    setShowLog(true);
  };

  const criticals = incidents.filter((i) => i.severity === 'CRITICAL').length;
  const healthy = incidents.length === 0;

  return (
    <section className="pane" style={{ flexShrink: 0, display: 'flex', flexDirection: 'column', maxHeight: '300px' }}>
      <div className="pane-header" style={{ fontWeight: 'normal', color: 'var(--text-muted)' }}>
        <span>COPIER HEALTH</span>
        <span style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
          <span style={{ color: healthy ? 'var(--color-buy)' : 'var(--color-sell)', fontWeight: 'bold' }}>
            {healthy ? 'ALL MIRRORS RECONCILED' : `${criticals} CRITICAL / ${incidents.length} OPEN`}
          </span>
          <button className="btn-toolbar" onClick={openLog}>Issue Log</button>
        </span>
      </div>

      <div style={{ padding: '8px', overflowY: 'auto' }}>
        {healthy ? (
          <div style={{ padding: '12px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '10px' }}>
            Every provider position has a matching mirror on every online consumer.
            Reconciled every 15s against live positions — independent of the copier's own reporting.
          </div>
        ) : (
          <table className="data-grid" style={{ width: '100%' }}>
            <thead>
              <tr>
                <th style={{ width: '150px' }}>Instance</th>
                <th style={{ width: '150px' }}>Issue</th>
                <th>Detail</th>
                <th style={{ width: '60px', textAlign: 'center' }}>Open</th>
                <th style={{ width: '150px', textAlign: 'center' }}>Action</th>
              </tr>
            </thead>
            <tbody>
              {incidents.map((inc) => (
                <tr key={inc.id}>
                  <td style={{ fontWeight: 'bold' }}>{inc.instance_name}</td>
                  <td style={{ color: SEVERITY_COLOR[inc.severity] || 'var(--text-muted)', fontWeight: 'bold' }}>
                    {inc.type}
                    {inc.status === 'ACKED' && (
                      <span style={{ color: 'var(--text-muted)', fontWeight: 'normal' }}> (ignored)</span>
                    )}
                  </td>
                  <td style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                    <div>{inc.detail.cause}</div>
                    {inc.detail.consumer && <div>{inc.detail.consumer}</div>}
                    {inc.detail.retcode && (
                      <div style={{ color: 'var(--color-sell)' }}>
                        {inc.detail.retcode} {inc.detail.broker}
                      </div>
                    )}
                  </td>
                  <td style={{ textAlign: 'center' }}>{relTime(inc.first_seen)}</td>
                  <td style={{ textAlign: 'center', display: 'flex', gap: '4px', justifyContent: 'center' }}>
                    {RETRYABLE.has(inc.type) && (
                      <button
                        className="btn-toolbar"
                        disabled={actionMutation.isPending}
                        onClick={() => actionMutation.mutate({ id: inc.id, action: 'retry' })}
                      >
                        Retry
                      </button>
                    )}
                    {CLOSEABLE.has(inc.type) && (
                      <button
                        className="btn-toolbar"
                        disabled={actionMutation.isPending}
                        onClick={() => {
                          if (confirm(`Close position on ${inc.instance_name}?`)) {
                            actionMutation.mutate({ id: inc.id, action: 'close' });
                          }
                        }}
                      >
                        Close
                      </button>
                    )}
                    {inc.status !== 'ACKED' && (
                      <button
                        className="btn-toolbar"
                        disabled={actionMutation.isPending}
                        onClick={() => actionMutation.mutate({ id: inc.id, action: 'ack' })}
                      >
                        Ignore
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {showLog && (
        <div
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.8)', zIndex: 1000,
            display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '40px',
          }}
          onClick={() => setShowLog(false)}
        >
          <div
            className="pane"
            style={{ width: '100%', maxWidth: '900px', maxHeight: '100%', display: 'flex', flexDirection: 'column' }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="pane-header">
              <span>ISSUE LOG — TODAY</span>
              <button className="btn-toolbar" onClick={() => setShowLog(false)}>Close</button>
            </div>
            <pre
              style={{
                margin: 0, padding: '10px', overflow: 'auto', fontSize: '10px',
                whiteSpace: 'pre-wrap', color: 'var(--text-muted)', background: 'var(--bg-app)',
              }}
            >
              {logText}
            </pre>
          </div>
        </div>
      )}
    </section>
  );
};

export default CopierHealth;
