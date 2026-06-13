import { useState } from 'react';
import { useStore } from '../store/useStore';
import type { Position } from '../types';
import { FlashCell } from './FlashCell';

const TrackerTable = () => {
  const instances = useStore((state) => state.instances || []);
  const [expandedInsts, setExpandedInsts] = useState<Record<number, boolean>>({});

  const toggleExpand = (id: number) => {
    setExpandedInsts((prev) => ({
      ...prev,
      [id]: prev[id] === false ? true : false, // Default to true (expanded)
    }));
  };

  const hasAnyPositions = instances.some((inst) => inst.positions && inst.positions.length > 0);

  const formatCurrency = (val: number) => {
    return val.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };

  const formatPrice = (val: number) => {
    if (!val) return '0.00';
    // Match common fx/crypto decimals dynamically
    const decimals = val.toString().split('.')[1]?.length || 2;
    return val.toLocaleString('en-US', { 
      minimumFractionDigits: Math.max(2, Math.min(decimals, 5)), 
      maximumFractionDigits: Math.max(2, Math.min(decimals, 5)) 
    });
  };

  return (
    <div className="pane-content table-container" style={{ padding: 0 }}>
      <table className="data-grid" id="active-positions-table">
        <thead>
          <tr>
            <th style={{ width: '20%' }}>Symbol / Ticket</th>
            <th style={{ width: '10%' }}>Type</th>
            <th style={{ width: '10%' }}>Volume</th>
            <th style={{ width: '15%' }}>Open Price</th>
            <th style={{ width: '15%' }}>Current Price</th>
            <th style={{ width: '10%' }}>Dist. SL</th>
            <th style={{ width: '10%' }}>Risk ($)</th>
            <th style={{ width: '10%' }}>Floating P&L</th>
          </tr>
        </thead>
        <tbody>
          {!hasAnyPositions ? (
            <tr>
              <td colSpan={8} style={{ textAlign: 'center', padding: '20px', color: 'var(--text-muted)' }}>
                No active positions found.
              </td>
            </tr>
          ) : (
            instances.map((inst) => {
              if (!inst.positions || inst.positions.length === 0) return null;
              
              const isExpanded = expandedInsts[inst.id] !== false; // Default to true (expanded)
              const instProfit = inst.positions.reduce((sum: number, p: Position) => sum + (p.profit || 0), 0);
              const profitColor = instProfit >= 0 ? 'var(--color-buy)' : 'var(--color-sell)';
              
              let roleBadge = null;
              if (inst.copier_role === 'PROVIDER') {
                roleBadge = <span className="badge-dense" style={{ background: 'rgba(243, 156, 18, 0.15)', color: '#f39c12', marginLeft: '5px', fontSize: '9px', verticalAlign: 'middle' }}>👑 MASTER</span>;
              } else if (inst.copier_role === 'CONSUMER') {
                roleBadge = <span className="badge-dense" style={{ background: 'rgba(52, 152, 219, 0.15)', color: '#3498db', marginLeft: '5px', fontSize: '9px', verticalAlign: 'middle' }}>👥 SUB</span>;
              }

              return (
                <tr key={`group-${inst.id}`} style={{ display: 'contents' }}>
                  <td colSpan={8} style={{ padding: 0, border: 'none' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', tableLayout: 'fixed' }}>
                      <tbody>
                        {/* Instance Header Row */}
                        <tr className="tree-header tree-toggle" style={{ cursor: 'pointer' }} onClick={() => toggleExpand(inst.id)}>
                          <td colSpan={8} style={{ padding: '4px 8px' }}>
                            <span className={`toggle-icon ${isExpanded ? '' : 'collapsed'}`}>▼</span>
                            <strong>{inst.name}</strong>
                            {roleBadge}
                            <span style={{ fontSize: '9px', color: 'var(--text-muted)', marginLeft: '10px' }}>{inst.positions.length} Trades</span>
                            <span style={{ float: 'right', color: profitColor, fontWeight: 'bold' }}>
                              $<FlashCell value={instProfit} format={formatCurrency} />
                            </span>
                          </td>
                        </tr>
                        
                        {/* Position Rows */}
                        {isExpanded && inst.positions.map((p: Position) => {
                          const pColor = p.profit >= 0 ? 'var(--color-buy)' : 'var(--color-sell)';
                          const tClass = p.type === 'BUY' ? 'bdg-buy' : 'bdg-sell';
                          const distSlStr = p.dist_sl >= 0 ? p.dist_sl.toFixed(1) : 'No SL';
                          
                          return (
                            <tr key={p.ticket}>
                              <td className="indent-1" style={{ width: '20%', padding: '4px 8px' }}>
                                <strong>{p.symbol}</strong> <span style={{ color: 'var(--text-muted)', fontSize: '8px' }}>({p.ticket})</span>
                              </td>
                              <td style={{ width: '10%' }}><span className={`badge-dense ${tClass}`}>{p.type}</span></td>
                              <td style={{ width: '10%' }}>{p.volume}</td>
                              <td style={{ width: '15%' }}>{formatPrice(p.price_open)}</td>
                              <td style={{ width: '15%' }}>
                                <FlashCell value={p.price_current} format={formatPrice} />
                              </td>
                              <td style={{ width: '10%' }}>{distSlStr}</td>
                              <td style={{ width: '10%' }}>${p.risk_usd?.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                              <td style={{ width: '10%', color: pColor, fontWeight: 'bold' }}>
                                $<FlashCell value={p.profit} format={formatCurrency} />
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </td>
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
};

export default TrackerTable;

