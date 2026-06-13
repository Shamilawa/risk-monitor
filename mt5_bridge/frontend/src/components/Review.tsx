
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Filler,
  Legend,
} from 'chart.js';
import { Line } from 'react-chartjs-2';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Filler,
  Legend
);

const chartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: { display: false },
  },
  scales: {
    y: { display: true, grid: { color: 'rgba(255, 255, 255, 0.1)' } },
    x: { display: true, grid: { display: false } },
  },
  elements: {
    point: { radius: 0 },
    line: { tension: 0.2, borderWidth: 2 },
  },
};

const Review = () => {

  const dummyEquityData = {
    labels: ['10:00', '11:00', '12:00', '13:00', '14:00', '15:00'],
    datasets: [
      {
        fill: true,
        label: 'Equity',
        data: [10000, 10050, 9980, 10120, 10200, 10150],
        borderColor: '#2ecc71',
        backgroundColor: 'rgba(46, 204, 113, 0.1)',
      },
    ],
  };

  const dummyDrawdownData = {
    labels: ['10:00', '11:00', '12:00', '13:00', '14:00', '15:00'],
    datasets: [
      {
        fill: true,
        label: 'Drawdown',
        data: [0, -0.5, -1.2, 0, 0, -0.3],
        borderColor: '#e74c3c',
        backgroundColor: 'rgba(231, 76, 60, 0.1)',
      },
    ],
  };

  return (
    <div className="workspace workspace-review" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', padding: '8px', height: '100%' }}>
      
      {/* Trading Log Pane */}
      <section className="pane" style={{ display: 'flex', flexDirection: 'column' }}>
        <div className="pane-header">Trading History & Logs</div>
        <div className="pane-content" style={{ display: 'flex', flexDirection: 'column', gap: '8px', padding: '8px' }}>
          
          <div className="summary-cards" style={{ display: 'flex', gap: '8px', overflowX: 'auto' }}>
            <div className="metric-card" style={{ borderLeftColor: 'var(--color-active)' }}>
              <div className="metric-label">Total Profit</div>
              <div className="metric-value">$150.00</div>
            </div>
            <div className="metric-card" style={{ borderLeftColor: 'var(--color-pending)' }}>
              <div className="metric-label">Win Rate</div>
              <div className="metric-value">65%</div>
            </div>
          </div>

          <div className="charts-container" style={{ display: 'flex', gap: '8px', height: '200px' }}>
            <div className="chart-box" style={{ flex: 1, background: 'var(--bg-panel)', border: '1px solid var(--border-color)', padding: '8px' }}>
              <div className="metric-label" style={{ fontSize: '10px', color: 'var(--text-muted)', marginBottom: '4px' }}>Equity Curve</div>
              <div style={{ position: 'relative', height: '160px' }}>
                <Line options={chartOptions} data={dummyEquityData} />
              </div>
            </div>
            <div className="chart-box" style={{ flex: 1, background: 'var(--bg-panel)', border: '1px solid var(--border-color)', padding: '8px' }}>
              <div className="metric-label" style={{ fontSize: '10px', color: 'var(--text-muted)', marginBottom: '4px' }}>Drawdown</div>
              <div style={{ position: 'relative', height: '160px' }}>
                <Line options={chartOptions} data={dummyDrawdownData} />
              </div>
            </div>
          </div>

          <div className="table-container" style={{ flexGrow: 1, overflow: 'auto' }}>
            <table className="data-grid">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Instance</th>
                  <th>Symbol</th>
                  <th>Action</th>
                  <th>Profit</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td colSpan={5} style={{ textAlign: 'center', padding: '20px', color: 'var(--text-muted)' }}>No logs found for this period.</td>
                </tr>
              </tbody>
            </table>
          </div>

        </div>
      </section>

      {/* Story Notes Pane */}
      <section className="pane" style={{ display: 'flex', flexDirection: 'column' }}>
        <div className="pane-header">Story Notes</div>
        <div className="pane-content" style={{ padding: '20px', background: 'var(--bg-app)', flexGrow: 1, overflowY: 'auto' }}>
          
          <div className="a4-sheet">
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '20px' }}>
              <div>
                <span style={{ fontSize: '9px', fontWeight: 'bold', letterSpacing: '1.5px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>MT5 System Report</span>
                <h2 style={{ margin: '4px 0 0 0', fontSize: '18px', color: 'var(--text-main)', fontWeight: 800 }}>DAILY PERFORMANCE LOG</h2>
              </div>
            </div>

            <div style={{ borderTop: '3px double var(--border-color)', margin: '20px 0' }}></div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
              <div style={{ color: 'var(--text-muted)', fontSize: '11px', textAlign: 'center', fontStyle: 'italic', padding: '20px 0' }}>
                No signals or executions logged for the selected date.
              </div>
            </div>
          </div>

        </div>
      </section>

    </div>
  );
};

export default Review;
