import { NavLink } from 'react-router-dom';
import { useStore } from '../../store/useStore';
import { usePhosphor } from '../../theme/themeContext';
import { NAV_SECTIONS } from './nav';

export function Sidebar() {
  const mt5Status = useStore((s) => s.mt5Status);
  const { phosphor } = usePhosphor();

  return (
    <aside
      style={{
        width: '204px',
        flexShrink: 0,
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--bg-toolbar)',
        borderRight: '1px solid var(--border-color)',
      }}
    >
      <nav style={{ display: 'flex', flexDirection: 'column', gap: '14px', padding: '14px 0', flex: 1, overflowY: 'auto' }}>
        {NAV_SECTIONS.map((section) => (
          <div key={section.label} style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                padding: '0 12px 4px',
                fontSize: '9px',
                letterSpacing: '0.24em',
                textTransform: 'uppercase',
                color: 'var(--text-muted)',
              }}
            >
              <span style={{ color: 'var(--terminal-accent)', opacity: 0.6 }}>&#9472;&#9472;</span>
              {section.label}
            </div>
            {section.items.map((item) => (
              <NavLink key={item.href} to={item.href} end={item.href === '/'} style={{ textDecoration: 'none' }}>
                {({ isActive }) => (
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px',
                      padding: '7px 12px',
                      background: isActive ? 'var(--terminal-accent)' : 'transparent',
                      color: isActive ? 'var(--on-accent)' : 'var(--text-muted)',
                      fontSize: '11px',
                      fontWeight: 700,
                      letterSpacing: '0.06em',
                      textTransform: 'uppercase',
                      cursor: 'pointer',
                      transition: 'background 0.1s, color 0.1s',
                    }}
                    onMouseEnter={(e) => {
                      if (!isActive) {
                        e.currentTarget.style.background = 'var(--bg-row-hover)';
                        e.currentTarget.style.color = 'var(--text-main)';
                      }
                    }}
                    onMouseLeave={(e) => {
                      if (!isActive) {
                        e.currentTarget.style.background = 'transparent';
                        e.currentTarget.style.color = 'var(--text-muted)';
                      }
                    }}
                  >
                    <span style={{ width: '10px', textAlign: 'center' }}>{isActive ? '>' : ''}</span>
                    <span style={{ fontSize: '9px', opacity: 0.85, fontVariantNumeric: 'tabular-nums' }}>{item.fkey}</span>
                    <span style={{ flex: 1 }}>{item.label}</span>
                    <span style={{ fontSize: '9px', opacity: isActive ? 0.85 : 0.5 }}>{item.code}</span>
                  </div>
                )}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      {/* System status block */}
      <div style={{ padding: '10px', borderTop: '1px solid var(--border-color)' }}>
        <div
          style={{
            border: '1px solid var(--border-color)',
            background: 'var(--bg-panel)',
            padding: '8px 10px',
            display: 'flex',
            flexDirection: 'column',
            gap: '6px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span
              style={{
                width: '7px',
                height: '7px',
                background: mt5Status.online ? 'var(--color-buy)' : 'var(--color-sell)',
                boxShadow: `0 0 5px ${mt5Status.online ? 'var(--color-buy)' : 'var(--color-sell)'}`,
              }}
            />
            <span
              style={{
                fontSize: '10px',
                fontWeight: 700,
                letterSpacing: '0.1em',
                textTransform: 'uppercase',
                color: mt5Status.online ? 'var(--color-buy)' : 'var(--color-sell)',
              }}
            >
              {mt5Status.online ? 'Nominal' : 'Offline'}
            </span>
          </div>
          <div style={{ fontSize: '9px', color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums' }}>
            {mt5Status.text}
          </div>
          <div style={{ fontSize: '9px', color: 'var(--text-muted)' }}>
            <span style={{ color: 'var(--terminal-accent)' }}>$</span> phosphor::{phosphor}
          </div>
        </div>
      </div>
    </aside>
  );
}
