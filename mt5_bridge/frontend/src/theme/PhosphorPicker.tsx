import { useEffect, useRef, useState } from 'react';
import { usePhosphor } from './themeContext';
import { PHOSPHORS } from './phosphors';

/** Bracket-style dropdown for switching the phosphor accent color. */
export function PhosphorPicker() {
  const { phosphor, setPhosphor } = usePhosphor();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  const current = PHOSPHORS.find((p) => p.id === phosphor) ?? PHOSPHORS[0];

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button
        onClick={() => setOpen((o) => !o)}
        title="Switch phosphor color"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '6px',
          background: 'transparent',
          border: '1px solid var(--border-color)',
          color: 'var(--text-muted)',
          fontFamily: 'inherit',
          fontSize: '9px',
          fontWeight: 700,
          letterSpacing: '0.1em',
          textTransform: 'uppercase',
          padding: '4px 8px',
          cursor: 'pointer',
          height: '24px',
        }}
      >
        <span
          style={{
            width: '9px',
            height: '9px',
            background: 'var(--terminal-accent)',
            boxShadow: '0 0 5px var(--terminal-accent)',
          }}
        />
        <span style={{ color: 'var(--terminal-accent)' }}>[{current.label}]</span>
        <span style={{ fontSize: '8px' }}>&#9662;</span>
      </button>
      {open && (
        <div
          style={{
            position: 'absolute',
            top: '100%',
            right: 0,
            marginTop: '2px',
            background: 'var(--bg-panel)',
            border: '1px solid var(--border-dark)',
            zIndex: 1200,
            minWidth: '130px',
          }}
        >
          {PHOSPHORS.map((p) => {
            const active = p.id === phosphor;
            return (
              <button
                key={p.id}
                onClick={() => {
                  setPhosphor(p.id);
                  setOpen(false);
                }}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  width: '100%',
                  background: active ? 'var(--terminal-accent-soft)' : 'transparent',
                  border: 'none',
                  borderLeft: `2px solid ${active ? 'var(--terminal-accent)' : 'transparent'}`,
                  color: active ? 'var(--terminal-accent)' : 'var(--text-muted)',
                  fontFamily: 'inherit',
                  fontSize: '10px',
                  fontWeight: 700,
                  letterSpacing: '0.1em',
                  textTransform: 'uppercase',
                  padding: '6px 10px',
                  cursor: 'pointer',
                  textAlign: 'left',
                }}
                onMouseEnter={(e) => {
                  if (!active) e.currentTarget.style.background = 'var(--bg-row-hover)';
                }}
                onMouseLeave={(e) => {
                  if (!active) e.currentTarget.style.background = 'transparent';
                }}
              >
                <span style={{ width: '9px', height: '9px', background: p.swatch }} />
                {p.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
