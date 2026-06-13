import { useState, useEffect, useRef } from 'react';
import { useStore } from '../store/useStore';
import type { Instance } from '../types';
import { FlashCell } from './FlashCell';

interface LeaderLineInstance {
  remove: () => void;
  position: () => void;
}

const InstancesOverview = () => {
  const instances = useStore((state) => state.instances || []);
  const [selectedPeriods, setSelectedPeriods] = useState<Record<number, string>>({});

  const activeLinesRef = useRef<Record<string, LeaderLineInstance>>({});
  const prevConnectionsKeyRef = useRef<string>('');

  useEffect(() => {
    const LeaderLineClass = (window as unknown as { LeaderLine: new (start: HTMLElement, end: HTMLElement, options: Record<string, unknown>) => LeaderLineInstance }).LeaderLine;
    if (!LeaderLineClass) return;

    const masters = instances.filter((i) => i.copier_role === 'PROVIDER');
    const subs = instances.filter((i) => i.copier_role === 'CONSUMER');

    const connectionsKey = masters.map((m) => m.id).join(',') + '->' + subs.map((s) => s.id).join(',');

    let timerId: ReturnType<typeof setTimeout> | null = null;

    if (connectionsKey !== prevConnectionsKeyRef.current) {
      prevConnectionsKeyRef.current = connectionsKey;

      const recreateLines = () => {
        // Remove old lines
        Object.values(activeLinesRef.current).forEach((line) => {
          try {
            line.remove();
          } catch {
            // Ignored
          }
        });
        activeLinesRef.current = {};

        if (masters.length > 0 && subs.length > 0) {
          const masterCard = document.getElementById(`health-card-${masters[0].id}`);
          if (masterCard) {
            subs.forEach((sub) => {
              const subCard = document.getElementById(`health-card-${sub.id}`);
              if (subCard) {
                const lineKey = `${masters[0].id}-${sub.id}`;
                try {
                  activeLinesRef.current[lineKey] = new LeaderLineClass(
                    masterCard,
                    subCard,
                    {
                      color: 'rgba(52, 152, 219, 0.4)',
                      size: 2,
                      path: 'fluid',
                      startSocket: 'bottom',
                      endSocket: 'top',
                      dropShadow: true,
                      dash: { animation: true }
                    }
                  );
                } catch (err) {
                  console.error('Error creating leader line:', err);
                }
              }
            });
          }
        }
      };

      // Recreate after a small timeout to let DOM/layout settle
      timerId = setTimeout(recreateLines, 100);
    } else {
      // Just update positions of existing lines in place without recreating them
      Object.values(activeLinesRef.current).forEach((line) => {
        try {
          line.position();
        } catch {
          // Ignored
        }
      });
    }

    const handleUpdate = () => {
      Object.values(activeLinesRef.current).forEach((line) => {
        try {
          line.position();
        } catch {
          // Ignored
        }
      });
    };

    window.addEventListener('resize', handleUpdate);
    window.addEventListener('scroll', handleUpdate, true);

    return () => {
      if (timerId) clearTimeout(timerId);
      window.removeEventListener('resize', handleUpdate);
      window.removeEventListener('scroll', handleUpdate, true);
    };
  }, [instances]);

  // Clean up overlays when component unmounts
  useEffect(() => {
    return () => {
      Object.values(activeLinesRef.current).forEach((line) => {
        try {
          line.remove();
        } catch {
          // Ignored
        }
      });
      activeLinesRef.current = {};
      prevConnectionsKeyRef.current = '';
    };
  }, []);

  const handlePeriodChange = (id: number, period: string) => {
    setSelectedPeriods((prev) => ({ ...prev, [id]: period }));
  };

  const renderCard = (inst: Instance) => {
    const period = selectedPeriods[inst.id] || 'today';
    const realizedVal = inst.realized_gains?.[period] || 0.0;
    const gainColor = realizedVal > 0 ? 'var(--color-buy)' : (realizedVal < 0 ? 'var(--color-sell)' : 'var(--text-secondary)');

    const floatingPnl = (inst.equity || 0) - (inst.balance || 0);
    const pnlColor = floatingPnl > 0 ? 'var(--color-buy)' : (floatingPnl < 0 ? 'var(--color-sell)' : 'var(--text-main)');

    const cardClass = `setting-card ${floatingPnl > 0 ? 'in-profit' : floatingPnl < 0 ? 'in-drawdown' : ''}`;

    let roleBadge = null;
    let flexStyle = {};

    if (inst.copier_role === 'PROVIDER') {
      roleBadge = (
        <>
          <span className="badge-dense" style={{ background: 'rgba(243, 156, 18, 0.15)', color: '#f39c12', marginLeft: '5px', fontSize: '9px', verticalAlign: 'middle' }}>👑 MASTER</span>
          <span className="badge-dense" style={{ background: 'rgba(46, 204, 113, 0.15)', color: '#2ecc71', marginLeft: '5px', fontSize: '8px', verticalAlign: 'middle', display: 'inline-flex', alignItems: 'center' }}>
            <span style={{ display: 'inline-block', width: '6px', height: '6px', background: '#2ecc71', borderRadius: '#50%', marginRight: '3px' }}></span>ZMQ
          </span>
        </>
      );
      flexStyle = { width: '260px', flexShrink: 0 };
    } else if (inst.copier_role === 'CONSUMER') {
      roleBadge = (
        <span className="badge-dense" style={{ background: 'rgba(52, 152, 219, 0.15)', color: '#3498db', marginLeft: '5px', fontSize: '9px', verticalAlign: 'middle' }}>👥 SUB</span>
      );
      flexStyle = { width: '220px', flexShrink: 0 };
    }

    let copierInfoHtml = null;
    if (inst.copier_role === 'CONSUMER') {
      let riskStr = '';
      if (inst.copier_risk_type === 'FIXED') riskStr = `Fixed ${inst.copier_fixed_lot || 0.01} Lots`;
      else if (inst.copier_risk_type === 'MULTIPLIER') riskStr = `${inst.copier_risk_multiplier || 1.0}x Multi`;
      else if (inst.copier_risk_type === 'USD') riskStr = `$${inst.copier_risk_usd || 100.0} USD`;

      copierInfoHtml = (
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '2px' }}>
          <span style={{ color: '#3498db', fontSize: '10px', fontWeight: 'bold' }}>Copier Risk</span>
          <strong style={{ fontSize: '10px', color: 'var(--text-secondary)' }}>{riskStr}</strong>
        </div>
      );
    }

    const formatCurrency = (val: number) => {
      return val.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    };

    const formatPnl = (val: number) => {
      const pnlAbs = Math.abs(val);
      const pnlSign = val > 0 ? '+' : (val < 0 ? '-' : '');
      const pnlPct = (inst.balance && inst.balance > 0) ? ((pnlAbs / inst.balance) * 100).toFixed(2) : '0.00';
      return `${pnlSign}$${pnlAbs.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} (${pnlPct}%)`;
    };

    const formatRealized = (val: number) => {
      const sign = val > 0 ? '+' : '';
      return `${sign}$${val.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    };

    return (
      <div key={inst.id} id={`health-card-${inst.id}`} className={cardClass} style={{ padding: 0, margin: 0, ...flexStyle, background: 'var(--bg-panel)', border: '1px solid var(--border-color)', display: 'flex', flexDirection: 'column' }}>
        <div className="card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 8px', borderBottom: '1px solid var(--border-color)', background: 'var(--bg-toolbar)', fontWeight: 'bold' }}>
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <strong style={{ color: 'var(--text-main)', fontSize: '11px' }}>{inst.name}</strong>
            {roleBadge}
          </div>
        </div>
        <div style={{ padding: '6px 8px', display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '10px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ color: 'var(--text-muted)' }}>Balance</span>
            <strong style={{ color: 'var(--text-main)' }}>$<FlashCell value={inst.balance || 0} format={formatCurrency} /></strong>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ color: 'var(--text-muted)' }}>Equity</span>
            <strong style={{ color: 'var(--text-main)' }}>$<FlashCell value={inst.equity || 0} format={formatCurrency} /></strong>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ color: 'var(--text-muted)' }}>Trades</span>
            <strong style={{ color: 'var(--text-main)' }}>{inst.positions?.length || 0}</strong>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ color: 'var(--text-muted)' }}>P&L</span>
            <strong style={{ color: pnlColor }}><FlashCell value={floatingPnl} format={formatPnl} /></strong>
          </div>
          {copierInfoHtml}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '4px', paddingTop: '4px', borderTop: '1px solid var(--border-color)' }}>
            <select
              value={period}
              onChange={(e) => handlePeriodChange(inst.id, e.target.value)}
              style={{ fontSize: '9px', padding: '2px', background: 'var(--bg-panel)', color: 'var(--text-main)', border: '1px solid var(--border-color)', borderRadius: '3px', outline: 'none', cursor: 'pointer' }}
            >
              <option value="today">Realized (Today)</option>
              <option value="yesterday">Realized (Yest.)</option>
              <option value="week">Realized (Week)</option>
              <option value="last_week">Realized (L.Week)</option>
              <option value="month">Realized (Month)</option>
            </select>
            <strong style={{ color: gainColor, fontSize: '10px' }}><FlashCell value={realizedVal} format={formatRealized} /></strong>
          </div>
        </div>
      </div>
    );
  };

  const masters = instances.filter((inst) => inst.copier_role === 'PROVIDER');
  const subs = instances.filter((inst) => inst.copier_role === 'CONSUMER');
  const others = instances.filter((inst) => inst.copier_role !== 'PROVIDER' && inst.copier_role !== 'CONSUMER');

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '15px', width: '100%', padding: '10px 0', alignItems: 'center' }}>
      {masters.length > 0 && (
        <div style={{ display: 'flex', justifyContent: 'center', gap: '15px', width: '100%', marginTop: '30px', marginBottom: '60px', flexWrap: 'wrap' }}>
          {masters.map(renderCard)}
        </div>
      )}

      {subs.length > 0 && (
        <div style={{ display: 'flex', justifyContent: 'center', gap: '15px', width: '100%', marginBottom: '60px', flexWrap: 'wrap' }}>
          {subs.map(renderCard)}
        </div>
      )}

      {others.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', width: '100%', maxWidth: '1200px', marginTop: '20px' }}>
          <div style={{ fontSize: '10px', fontWeight: 'bold', color: 'var(--text-muted)', borderBottom: '1px solid var(--border-color)', paddingBottom: '3px' }}>⚙ UNASSIGNED INSTANCES</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '8px' }}>
            {others.map(renderCard)}
          </div>
        </div>
      )}

      {instances.length === 0 && (
        <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '20px' }}>
          No configured MT5 instances found. Go to the Settings or Copier tabs to configure them.
        </div>
      )}
    </div>
  );
};

export default InstancesOverview;
