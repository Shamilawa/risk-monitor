import { useStore } from '../../store/useStore';

export function StatusLine() {
  const mt5Status = useStore((s) => s.mt5Status);
  return (
    <footer
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '16px',
        height: '22px',
        flexShrink: 0,
        padding: '0 12px',
        background: 'var(--bg-toolbar)',
        borderTop: '1px solid var(--border-color)',
        fontSize: '9px',
        letterSpacing: '0.14em',
        textTransform: 'uppercase',
        color: 'var(--text-muted)',
        userSelect: 'none',
      }}
    >
      <span style={{ color: 'var(--terminal-accent)', fontWeight: 700 }}>READY</span>
      <span>[F1-F4] NAV</span>
      <span>[◈] PHOSPHOR</span>
      <span style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
        <span
          style={{
            width: '6px',
            height: '6px',
            background: mt5Status.online ? 'var(--color-buy)' : 'var(--color-sell)',
            boxShadow: `0 0 4px ${mt5Status.online ? 'var(--color-buy)' : 'var(--color-sell)'}`,
          }}
        />
        {mt5Status.online ? 'Connected' : 'Disconnected'}
      </span>
    </footer>
  );
}
