import TrackerTable from './TrackerTable';
import InstancesOverview from './InstancesOverview';
import { useStore } from '../store/useStore';
import { FlashCell } from './FlashCell';
import type { Instance } from '../types';

const Dashboard = () => {
  const instances = useStore((state) => state.instances || []);

  const formatCurrency = (val: number) => {
    return val.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };

  return (
    <div className="workspace" style={{ padding: '4px', height: 'calc(100vh - 36px)', display: 'grid', gridTemplateColumns: '320px 1fr', gridTemplateRows: '1.2fr 4px 1fr', gridTemplateAreas: '"watchlist overview" "splitter splitter" "active active"', gap: '4px', overflow: 'hidden' }}>
      
      {/* Left Pane: Terminal Watchlist */}
      <section className="pane" style={{ gridArea: 'watchlist' }}>
        <div className="pane-header">Watchlist / Status Desk</div>
        <div className="pane-content table-container" style={{ padding: 0 }}>
          <table className="data-grid" style={{ width: '100%' }}>
            <thead>
              <tr>
                <th style={{ width: '40px' }}>Stat</th>
                <th>Instance</th>
                <th style={{ width: '60px', textAlign: 'right' }}>Margin</th>
                <th style={{ width: '50px', textAlign: 'right' }}>Trades</th>
                <th style={{ width: '80px', textAlign: 'right' }}>Equity</th>
              </tr>
            </thead>
            <tbody>
              {instances.length === 0 ? (
                <tr>
                  <td colSpan={5} style={{ textAlign: 'center', padding: '12px', color: 'var(--text-muted)' }}>
                    No instances monitor active.
                  </td>
                </tr>
              ) : (
                instances.map((inst: Instance) => {
                  const marginColor = (inst.margin_level || 0) < 100 ? 'var(--color-sell)' : (inst.margin_level || 0) < 300 ? '#f39c12' : 'var(--color-buy)';
                  const ml = inst.margin_level && inst.margin_level > 0 ? inst.margin_level.toLocaleString('en-US', { maximumFractionDigits: 1 }) + '%' : 'N/A';
                  
                  return (
                    <tr key={inst.id}>
                      <td style={{ textAlign: 'center' }}>
                        <span className="status-icon online" style={{ width: '6px', height: '6px', margin: 0 }}></span>
                      </td>
                      <td>
                        <strong style={{ color: 'var(--text-main)' }}>{inst.name}</strong>
                        {inst.copier_role === 'PROVIDER' && (
                          <span style={{ color: '#f39c12', fontSize: '8px', marginLeft: '4px', verticalAlign: 'middle' }}>[M]</span>
                        )}
                        {inst.copier_role === 'CONSUMER' && (
                          <span style={{ color: '#3498db', fontSize: '8px', marginLeft: '4px', verticalAlign: 'middle' }}>[S]</span>
                        )}
                      </td>
                      <td style={{ textAlign: 'right', color: marginColor, fontWeight: 'bold' }}>{ml}</td>
                      <td style={{ textAlign: 'right' }}>{inst.positions?.length || 0}</td>
                      <td style={{ textAlign: 'right', fontWeight: 'bold' }}>
                        $<FlashCell value={inst.equity || 0} format={formatCurrency} />
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Right Pane: Graph Overview */}
      <section className="pane pane-overview" style={{ gridArea: 'overview' }}>
        <div className="pane-header">Instances Graph Desk</div>
        <div className="pane-content" id="overview-container" style={{ padding: '4px', overflowY: 'auto', background: 'var(--bg-secondary)' }}>
          <InstancesOverview />
        </div>
      </section>

      <div className="splitter-horizontal" id="main-splitter" style={{ gridArea: 'splitter' }}></div>

      {/* Bottom Pane: Active Positions Table */}
      <section className="pane pane-positions" style={{ gridArea: 'active' }}>
        <div className="pane-header">Active Positions Spreadsheet</div>
        <TrackerTable />
      </section>

    </div>
  );
};

export default Dashboard;


