import { useState, useRef, useEffect } from 'react';
import TrackerTable from './TrackerTable';
import InstancesOverview from './InstancesOverview';
import { useStore } from '../store/useStore';
import { FlashCell } from './FlashCell';
import { Panel, StatusTag } from './ui/Terminal';
import type { Instance } from '../types';

const Dashboard = () => {
  const instances = useStore((state) => state.instances || []);

  const [watchlistWidth, setWatchlistWidth] = useState(320);
  const [positionsHeight, setPositionsHeight] = useState(300);
  const [activeSplitter, setActiveSplitter] = useState<'v' | 'h' | null>(null);

  const isDraggingVertical = useRef(false);
  const isDraggingHorizontal = useRef(false);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      let changed = false;
      if (isDraggingVertical.current) {
        const newWidth = Math.max(180, Math.min(e.clientX, 600));
        setWatchlistWidth(newWidth);
        changed = true;
      }
      if (isDraggingHorizontal.current) {
        const windowHeight = window.innerHeight;
        const newHeight = Math.max(100, Math.min(windowHeight - e.clientY - 36, windowHeight - 220));
        setPositionsHeight(newHeight);
        changed = true;
      }
      if (changed) {
        window.dispatchEvent(new Event('resize'));
      }
    };

    const handleMouseUp = () => {
      isDraggingVertical.current = false;
      isDraggingHorizontal.current = false;
      setActiveSplitter(null);
      document.body.style.userSelect = '';
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, []);

  const formatCurrency = (val: number) => {
    return val.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };

  return (
    <div
      style={{
        padding: '8px',
        height: '100%',
        display: 'grid',
        gridTemplateColumns: `${watchlistWidth}px 9px 1fr`,
        gridTemplateRows: `1fr 9px ${positionsHeight}px`,
        gridTemplateAreas: '"watchlist vsplitter overview" "hsplitter hsplitter hsplitter" "active active active"',
        gap: 0,
        overflow: 'hidden',
      }}
    >
      {/* Left Pane: Watchlist */}
      <Panel
        title="Watchlist · Status Desk"
        style={{ gridArea: 'watchlist' }}
        bodyStyle={{ overflow: 'auto' }}
      >
        <table className="data-grid" style={{ width: '100%' }}>
          <thead>
            <tr>
              <th style={{ width: '34px' }}>ST</th>
              <th>Instance</th>
              <th style={{ width: '64px', textAlign: 'right' }}>Margin</th>
              <th style={{ width: '44px', textAlign: 'right' }}>Pos</th>
              <th style={{ width: '84px', textAlign: 'right' }}>Equity</th>
            </tr>
          </thead>
          <tbody>
            {instances.length === 0 ? (
              <tr>
                <td colSpan={5} style={{ textAlign: 'center', padding: '16px', color: 'var(--text-muted)' }}>
                  No instances online.
                </td>
              </tr>
            ) : (
              instances.map((inst: Instance) => {
                const marginColor =
                  (inst.margin_level || 0) < 100
                    ? 'var(--color-sell)'
                    : (inst.margin_level || 0) < 300
                      ? 'var(--color-pending)'
                      : 'var(--color-buy)';
                const ml =
                  inst.margin_level && inst.margin_level > 0
                    ? inst.margin_level.toLocaleString('en-US', { maximumFractionDigits: 1 }) + '%'
                    : 'N/A';

                return (
                  <tr key={inst.id}>
                    <td style={{ textAlign: 'center' }}>
                      <span
                        style={{
                          display: 'inline-block',
                          width: '7px',
                          height: '7px',
                          background: 'var(--color-buy)',
                          boxShadow: '0 0 4px var(--color-buy)',
                        }}
                      />
                    </td>
                    <td>
                      <strong style={{ color: 'var(--text-main)' }}>{inst.name}</strong>
                      {inst.copier_role === 'PROVIDER' && <StatusTag label="M" tone="warning" style={{ marginLeft: '5px' }} />}
                      {inst.copier_role === 'CONSUMER' && <StatusTag label="S" tone="accent" style={{ marginLeft: '5px' }} />}
                    </td>
                    <td style={{ textAlign: 'right', color: marginColor, fontWeight: 'bold', fontVariantNumeric: 'tabular-nums' }}>
                      {ml}
                    </td>
                    <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{inst.positions?.length || 0}</td>
                    <td style={{ textAlign: 'right', fontWeight: 'bold', fontVariantNumeric: 'tabular-nums' }}>
                      $<FlashCell value={inst.equity || 0} format={formatCurrency} />
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </Panel>

      {/* Vertical Splitter */}
      <div
        className={`splitter-vertical ${activeSplitter === 'v' ? 'active' : ''}`}
        style={{ gridArea: 'vsplitter' }}
        onMouseDown={(e) => {
          e.preventDefault();
          isDraggingVertical.current = true;
          setActiveSplitter('v');
          document.body.style.userSelect = 'none';
        }}
      />

      {/* Right Pane: Graph Overview */}
      <Panel
        title="Instances · Graph Desk"
        style={{ gridArea: 'overview' }}
        bodyStyle={{ overflowY: 'auto', background: 'var(--bg-secondary)', padding: '6px' }}
      >
        <InstancesOverview />
      </Panel>

      {/* Horizontal Splitter */}
      <div
        className={`splitter-horizontal ${activeSplitter === 'h' ? 'active' : ''}`}
        style={{ gridArea: 'hsplitter' }}
        onMouseDown={(e) => {
          e.preventDefault();
          isDraggingHorizontal.current = true;
          setActiveSplitter('h');
          document.body.style.userSelect = 'none';
        }}
      />

      {/* Bottom Pane: Active Positions */}
      <Panel title="Active Positions · Spreadsheet" style={{ gridArea: 'active' }} bodyStyle={{ display: 'flex', flexDirection: 'column' }}>
        <TrackerTable />
      </Panel>
    </div>
  );
};

export default Dashboard;
