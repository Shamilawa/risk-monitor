import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Page } from './shell/Page';
import { Panel, Field, TermInput, TermButton, SectionLabel } from './ui/Terminal';

interface GlobalSettings {
  trade_disable: boolean;
  disable_time_start: string;
  disable_time_end: string;
  auto_close_enabled: boolean;
}

const fetchSettings = async (): Promise<GlobalSettings> => {
  const res = await fetch('/api/global_settings');
  return res.json();
};

/** Terminal bracket toggle: [ ENABLED ] / [ DISABLED ]. */
function Toggle({
  value,
  onChange,
  danger,
}: {
  value: boolean;
  onChange: (v: boolean) => void;
  danger?: boolean;
}) {
  const onColor = danger ? 'var(--color-sell)' : 'var(--color-buy)';
  return (
    <button
      onClick={() => onChange(!value)}
      style={{
        fontFamily: 'inherit',
        fontSize: '10px',
        fontWeight: 700,
        letterSpacing: '0.12em',
        textTransform: 'uppercase',
        padding: '6px 14px',
        cursor: 'pointer',
        background: value ? (danger ? 'var(--color-sell-bg)' : 'var(--color-buy-bg)') : 'transparent',
        border: `1px solid ${value ? onColor : 'var(--border-color)'}`,
        color: value ? onColor : 'var(--text-muted)',
        minWidth: '112px',
      }}
    >
      [ {value ? 'ENABLED' : 'DISABLED'} ]
    </button>
  );
}

function SettingRow({
  title,
  subtitle,
  control,
}: {
  title: string;
  subtitle: string;
  control: React.ReactNode;
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '16px',
        padding: '12px 14px',
        border: '1px solid var(--border-color)',
        background: 'var(--bg-app)',
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: '3px', minWidth: 0 }}>
        <span style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-main)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          {title}
        </span>
        <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{subtitle}</span>
      </div>
      <div style={{ flexShrink: 0 }}>{control}</div>
    </div>
  );
}

const DEFAULTS: GlobalSettings = {
  trade_disable: false,
  disable_time_start: '',
  disable_time_end: '',
  auto_close_enabled: true,
};

export default function Settings() {
  const queryClient = useQueryClient();
  const { data } = useQuery<GlobalSettings>({ queryKey: ['global_settings'], queryFn: fetchSettings });

  // Local edits layered over the fetched settings — no effect needed to sync.
  const [edits, setEdits] = useState<Partial<GlobalSettings>>({});
  const [saved, setSaved] = useState(false);
  const form: GlobalSettings = { ...DEFAULTS, ...data, ...edits };

  const mutation = useMutation({
    mutationFn: async (payload: GlobalSettings) => {
      const res = await fetch('/api/global_settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error('Failed to save settings');
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['global_settings'] });
      setEdits({});
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    },
  });

  const patch = (p: Partial<GlobalSettings>) => setEdits((e) => ({ ...e, ...p }));

  return (
    <Page
      title="Settings"
      description="Global controls applied across every connected MT5 terminal."
      maxWidth={760}
      actions={
        <>
          {saved && (
            <span style={{ fontSize: '10px', color: 'var(--color-buy)', letterSpacing: '0.1em' }}>[SAVED]</span>
          )}
          <TermButton variant="solid" onClick={() => mutation.mutate(form)} disabled={mutation.isPending}>
            {mutation.isPending ? 'Saving…' : 'Save Changes'}
          </TermButton>
        </>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
        <Panel title="Copier Controls">
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', padding: '12px' }}>
            <SettingRow
              title="Auto-Close on Profit Lock"
              subtitle="When an armed profit-lock target is hit, close the instance's positions automatically."
              control={<Toggle value={form.auto_close_enabled} onChange={(v) => patch({ auto_close_enabled: v })} />}
            />
            <SettingRow
              title="Global Trade Disable"
              subtitle="Block all copier trade execution during the configured window below."
              control={<Toggle danger value={form.trade_disable} onChange={(v) => patch({ trade_disable: v })} />}
            />
          </div>
        </Panel>

        <Panel title="Trade-Disable Window">
          <div style={{ padding: '14px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <SectionLabel>Daily Blackout (local time)</SectionLabel>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <Field label="Start Time">
                <TermInput
                  type="time"
                  value={form.disable_time_start}
                  onChange={(e) => patch({ disable_time_start: e.target.value })}
                />
              </Field>
              <Field label="End Time">
                <TermInput
                  type="time"
                  value={form.disable_time_end}
                  onChange={(e) => patch({ disable_time_end: e.target.value })}
                />
              </Field>
            </div>
            <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
              Leave both blank to apply the trade-disable toggle at all times.
            </span>
          </div>
        </Panel>
      </div>
    </Page>
  );
}
