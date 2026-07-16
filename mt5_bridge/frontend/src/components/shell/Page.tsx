import type { CSSProperties, ReactNode } from 'react';

/** Uniform page header + scroll container for full-width routes. */
export function Page({
  title,
  description,
  actions,
  children,
  maxWidth = 1320,
  contentStyle,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
  maxWidth?: number;
  contentStyle?: CSSProperties;
}) {
  return (
    <div style={{ height: '100%', overflowY: 'auto', background: 'var(--bg-app)' }}>
      <div style={{ maxWidth, margin: '0 auto', padding: '18px 24px 28px' }}>
        <header
          style={{
            display: 'flex',
            alignItems: 'flex-end',
            justifyContent: 'space-between',
            gap: '16px',
            borderBottom: '1px solid var(--border-color)',
            paddingBottom: '12px',
          }}
        >
          <div style={{ minWidth: 0 }}>
            <h1
              className="term-glow"
              style={{
                fontSize: '17px',
                fontWeight: 700,
                letterSpacing: '0.12em',
                textTransform: 'uppercase',
                color: 'var(--text-main)',
                margin: 0,
              }}
            >
              <span style={{ color: 'var(--terminal-accent)', marginRight: '8px' }}>&gt;</span>
              {title}
            </h1>
            {description && (
              <p style={{ fontSize: '11px', color: 'var(--text-muted)', margin: '6px 0 0' }}>{description}</p>
            )}
          </div>
          {actions && <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>{actions}</div>}
        </header>
        <div style={{ marginTop: '18px', ...contentStyle }}>{children}</div>
      </div>
    </div>
  );
}
