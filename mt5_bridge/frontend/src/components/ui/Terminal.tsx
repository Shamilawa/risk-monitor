import type { CSSProperties, ReactNode } from 'react';

/* ============================================================
   Terminal UI primitives — shared vocabulary for every screen.
   Inline-styled (this app has no Tailwind) but all colors come
   from the phosphor token layer in theme/terminal.css.
   ============================================================ */

export type Tone = 'accent' | 'success' | 'error' | 'warning' | 'muted' | 'main';

const toneColor: Record<Tone, string> = {
  accent: 'var(--terminal-accent)',
  success: 'var(--color-buy)',
  error: 'var(--color-sell)',
  warning: 'var(--color-pending)',
  muted: 'var(--text-muted)',
  main: 'var(--text-main)',
};

/* ---- Bracket status tag: [ACTIVE] ---- */
export function StatusTag({
  label,
  tone = 'accent',
  style,
}: {
  label: string;
  tone?: Tone;
  style?: CSSProperties;
}) {
  return (
    <span
      style={{
        fontSize: '9px',
        fontWeight: 700,
        letterSpacing: '0.1em',
        textTransform: 'uppercase',
        color: toneColor[tone],
        whiteSpace: 'nowrap',
        ...style,
      }}
    >
      [{label}]
    </span>
  );
}

/* ---- ASCII block meter: [■■■■□□□□]  60% ---- */
export function Meter({
  value,
  width = 8,
  tone,
  showPct = true,
  style,
}: {
  value: number;
  width?: number;
  tone?: Tone;
  showPct?: boolean;
  style?: CSSProperties;
}) {
  const clamped = Math.max(0, Math.min(100, value));
  const filled = Math.round((clamped / 100) * width);
  const autoTone: Tone = clamped >= 100 ? 'success' : clamped > 0 ? 'accent' : 'muted';
  const color = toneColor[tone ?? autoTone];
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '6px',
        fontSize: '11px',
        fontVariantNumeric: 'tabular-nums',
        color,
        ...style,
      }}
    >
      <span>
        [{'■'.repeat(filled)}
        {'□'.repeat(width - filled)}]
      </span>
      {showPct && <span>{String(Math.round(clamped)).padStart(3, ' ')}%</span>}
    </span>
  );
}

/* ---- Bordered stat tile: label + big value, optional sub-line ---- */
export function MetricTile({
  label,
  value,
  tone = 'main',
  sub,
  style,
}: {
  label: string;
  value: ReactNode;
  tone?: Tone;
  sub?: string;
  style?: CSSProperties;
}) {
  return (
    <div
      style={{
        border: '1px solid var(--border-color)',
        background: 'var(--bg-app)',
        padding: '8px 10px',
        display: 'flex',
        flexDirection: 'column',
        gap: '4px',
        minWidth: 0,
        ...style,
      }}
    >
      <span
        style={{
          fontSize: '9px',
          fontWeight: 700,
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
          color: 'var(--text-muted)',
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
        }}
      >
        {label}
      </span>
      <span
        style={{
          fontSize: '14px',
          fontWeight: 700,
          fontVariantNumeric: 'tabular-nums',
          color: toneColor[tone],
          whiteSpace: 'nowrap',
        }}
      >
        {value}
      </span>
      {sub && <span style={{ fontSize: '9px', color: 'var(--text-muted)' }}>{sub}</span>}
    </div>
  );
}

/* ---- Section label: ── LABEL ---- */
export function SectionLabel({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
        fontSize: '10px',
        letterSpacing: '0.22em',
        textTransform: 'uppercase',
        color: 'var(--text-muted)',
        userSelect: 'none',
        ...style,
      }}
    >
      <span style={{ color: 'var(--terminal-accent)', opacity: 0.6 }}>&#9472;&#9472;</span>
      <span>{children}</span>
    </div>
  );
}

/* ---- 3-variant bracket button ---- */
type Variant = 'solid' | 'outline' | 'ghost';

export function TermButton({
  children,
  onClick,
  variant = 'outline',
  disabled,
  type = 'button',
  title,
  active,
  style,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: Variant;
  disabled?: boolean;
  type?: 'button' | 'submit';
  title?: string;
  active?: boolean;
  style?: CSSProperties;
}) {
  const base: CSSProperties = {
    fontFamily: 'inherit',
    fontSize: '10px',
    fontWeight: 700,
    letterSpacing: '0.1em',
    textTransform: 'uppercase',
    padding: '5px 12px',
    cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.45 : 1,
    transition: 'background 0.1s, border-color 0.1s, color 0.1s',
    lineHeight: 1.1,
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '6px',
    whiteSpace: 'nowrap',
  };
  const variants: Record<Variant, CSSProperties> = {
    solid: {
      background: 'var(--terminal-accent)',
      border: '1px solid var(--terminal-accent)',
      color: 'var(--on-accent)',
    },
    outline: {
      background: active ? 'var(--terminal-accent-soft)' : 'transparent',
      border: `1px solid ${active ? 'var(--terminal-accent)' : 'var(--border-color)'}`,
      color: active ? 'var(--terminal-accent)' : 'var(--text-muted)',
    },
    ghost: {
      background: 'transparent',
      border: '1px solid transparent',
      color: 'var(--text-muted)',
    },
  };
  return (
    <button
      type={type}
      title={title}
      disabled={disabled}
      onClick={onClick}
      style={{ ...base, ...variants[variant], ...style }}
      onMouseEnter={(e) => {
        if (disabled) return;
        const el = e.currentTarget;
        if (variant === 'solid') {
          el.style.filter = 'brightness(1.12)';
        } else {
          el.style.borderColor = 'var(--terminal-accent)';
          el.style.color = 'var(--terminal-accent)';
        }
      }}
      onMouseLeave={(e) => {
        const el = e.currentTarget;
        el.style.filter = 'none';
        if (variant !== 'solid') {
          el.style.borderColor = active ? 'var(--terminal-accent)' : 'var(--border-color)';
          el.style.color = active ? 'var(--terminal-accent)' : 'var(--text-muted)';
        }
      }}
    >
      {children}
    </button>
  );
}

/* ---- Flat bordered panel with optional header ---- */
export function Panel({
  title,
  actions,
  children,
  tone,
  bodyStyle,
  style,
  bodyRef,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  tone?: 'accent' | 'success' | 'error';
  bodyStyle?: CSSProperties;
  style?: CSSProperties;
  bodyRef?: React.Ref<HTMLDivElement>;
}) {
  const topBorder =
    tone === 'success'
      ? '2px solid var(--color-buy)'
      : tone === 'error'
        ? '2px solid var(--color-sell)'
        : tone === 'accent'
          ? '2px solid var(--terminal-accent)'
          : undefined;
  return (
    <section
      style={{
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--bg-panel)',
        border: '1px solid var(--border-color)',
        borderTop: topBorder,
        minHeight: 0,
        overflow: 'hidden',
        ...style,
      }}
    >
      {(title || actions) && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '8px',
            padding: '6px 10px',
            background: 'var(--bg-toolbar)',
            borderBottom: '1px solid var(--border-color)',
            flexShrink: 0,
          }}
        >
          <span
            style={{
              fontSize: '10px',
              fontWeight: 700,
              letterSpacing: '0.14em',
              textTransform: 'uppercase',
              color: 'var(--text-main)',
            }}
          >
            {title}
          </span>
          {actions && <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>{actions}</div>}
        </div>
      )}
      <div ref={bodyRef} style={{ flex: 1, minHeight: 0, ...bodyStyle }}>
        {children}
      </div>
    </section>
  );
}

/* ---- Form field wrapper + shared control styles ---- */
const controlStyle: CSSProperties = {
  width: '100%',
  background: 'var(--bg-app)',
  color: 'var(--text-main)',
  border: '1px solid var(--border-color)',
  padding: '6px 8px',
  fontFamily: 'inherit',
  fontSize: '11px',
  outline: 'none',
  boxSizing: 'border-box',
};

export function Field({
  label,
  hint,
  children,
  style,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
  style?: CSSProperties;
}) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: '4px', ...style }}>
      <span
        style={{
          fontSize: '9px',
          fontWeight: 700,
          letterSpacing: '0.1em',
          textTransform: 'uppercase',
          color: 'var(--text-muted)',
        }}
      >
        {label}
      </span>
      {children}
      {hint && <span style={{ fontSize: '9px', color: 'var(--text-muted)', opacity: 0.85 }}>{hint}</span>}
    </label>
  );
}

/** Text/number input that focuses to the accent border. */
export function TermInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  const { style, ...rest } = props;
  return (
    <input
      {...rest}
      style={{ ...controlStyle, ...style }}
      onFocus={(e) => {
        e.currentTarget.style.borderColor = 'var(--terminal-accent)';
        rest.onFocus?.(e);
      }}
      onBlur={(e) => {
        e.currentTarget.style.borderColor = 'var(--border-color)';
        rest.onBlur?.(e);
      }}
    />
  );
}

export function TermSelect(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  const { style, children, ...rest } = props;
  return (
    <select
      {...rest}
      style={{ ...controlStyle, cursor: 'pointer', ...style }}
      onFocus={(e) => {
        e.currentTarget.style.borderColor = 'var(--terminal-accent)';
        rest.onFocus?.(e);
      }}
      onBlur={(e) => {
        e.currentTarget.style.borderColor = 'var(--border-color)';
        rest.onBlur?.(e);
      }}
    >
      {children}
    </select>
  );
}

/* ---- Terminal modal shell ---- */
export function Modal({
  title,
  onClose,
  children,
  footer,
  width = 460,
  tone,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  width?: number;
  tone?: 'accent' | 'success' | 'error';
}) {
  const topBorder =
    tone === 'success'
      ? '2px solid var(--color-buy)'
      : tone === 'error'
        ? '2px solid var(--color-sell)'
        : '2px solid var(--terminal-accent)';
  return (
    <div
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0, 0, 0, 0.7)',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        zIndex: 1100,
        padding: '16px',
      }}
    >
      <div
        style={{
          width,
          maxWidth: '100%',
          maxHeight: '90vh',
          display: 'flex',
          flexDirection: 'column',
          background: 'var(--bg-panel)',
          border: '1px solid var(--border-dark)',
          borderTop: topBorder,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '8px 12px',
            background: 'var(--bg-toolbar)',
            borderBottom: '1px solid var(--border-color)',
            flexShrink: 0,
          }}
        >
          <strong
            style={{
              fontSize: '11px',
              fontWeight: 700,
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              color: 'var(--text-main)',
            }}
          >
            <span style={{ color: 'var(--terminal-accent)', marginRight: '6px' }}>&gt;</span>
            {title}
          </strong>
          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--text-muted)',
              cursor: 'pointer',
              fontSize: '16px',
              lineHeight: 1,
              padding: '0 4px',
            }}
          >
            &times;
          </button>
        </div>
        <div style={{ padding: '14px', overflowY: 'auto', flex: 1 }}>{children}</div>
        {footer && (
          <div
            style={{
              display: 'flex',
              gap: '8px',
              justifyContent: 'flex-end',
              padding: '10px 12px',
              background: 'var(--bg-header)',
              borderTop: '1px solid var(--border-color)',
              flexShrink: 0,
            }}
          >
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}
