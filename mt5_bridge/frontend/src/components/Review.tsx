import { useState, useEffect } from 'react';
import { useStore } from '../store/useStore';
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
  type ChartOptions,
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

interface PerformanceTrade {
  id: number;
  instance_id: number;
  instance_name: string;
  ticket: number;
  symbol: string;
  type: string;
  volume: number;
  profit: number;
  time: number;
  magic: number;
  comment: string;
  commission: number;
  swap: number;
  raw_profit: number;
  local_start_time: number;
  local_time: number;
}


const Review = () => {
  const storeInstances = useStore((state) => state.instances || []);
  
  // Date and Instance Filters
  const [availableDates, setAvailableDates] = useState<string[]>([]);
  const [selectedDate, setSelectedDate] = useState<string>('');
  const [selectedInstance, setSelectedInstance] = useState<string>('all');
  
  // Sync state
  const [isSyncing, setIsSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<string>('');

  // Performance Data States
  const [metrics, setMetrics] = useState({ total_profit: 0, win_rate: 0, total_trades: 0 });
  const [trades, setTrades] = useState<PerformanceTrade[]>([]);
  const [isLoadingPerf, setIsLoadingPerf] = useState(false);

  // Fetch dates on mount
  useEffect(() => {
    const fetchDates = async () => {
      try {
        const res = await fetch('/api/review_dates');
        const json = await res.json();
        if (json.dates && json.dates.length > 0) {
          setAvailableDates(json.dates);
          setSelectedDate(json.dates[0]); // Default to latest date
        } else {
          // If no dates, default to today's date formatted as YYYY-MM-DD
          const today = new Date().toISOString().split('T')[0];
          setAvailableDates([today]);
          setSelectedDate(today);
        }
      } catch (err) {
        console.error('Error fetching story dates:', err);
        const today = new Date().toISOString().split('T')[0];
        setAvailableDates([today]);
        setSelectedDate(today);
      }
    };
    fetchDates();
  }, []);

  // Fetch performance and story notes whenever date or instance changes
  useEffect(() => {
    if (!selectedDate) return;

    // Parse date into local start/end epochs
    const d = new Date(selectedDate);
    
    // start of day
    d.setHours(0, 0, 0, 0);
    const startEpoch = Math.floor(d.getTime() / 1000);

    // end of day
    d.setHours(23, 59, 59, 999);
    const endEpoch = Math.floor(d.getTime() / 1000);

    const loadPerformance = async () => {
      setIsLoadingPerf(true);
      try {
        const url = `/api/performance?instance_id=${selectedInstance}&start_time=${startEpoch}&end_time=${endEpoch}`;
        const res = await fetch(url);
        const json = await res.json();
        if (json.metrics) {
          setMetrics(json.metrics);
          setTrades(json.trades || []);
        }
      } catch (err) {
        console.error('Error loading performance details:', err);
      } finally {
        setIsLoadingPerf(false);
      }
    };

    loadPerformance();
  }, [selectedDate, selectedInstance]);

  // Sync logs mutation
  const handleSyncLogs = async () => {
    setIsSyncing(true);
    setSyncResult('Syncing...');
    try {
      const res = await fetch('/api/sync_log', { method: 'POST' });
      const json = await res.json();
      if (json.status === 'success') {
        setSyncResult(`Synced ${json.synced} deals.`);
        // Re-trigger fetch by refreshing date state or simple reload
        const temp = selectedDate;
        setSelectedDate('');
        setTimeout(() => setSelectedDate(temp), 50);
      } else {
        setSyncResult('Sync failed.');
      }
    } catch (err) {
      console.error(err);
      setSyncResult('Error syncing.');
    } finally {
      setIsSyncing(false);
      setTimeout(() => setSyncResult(''), 3000);
    }
  };

  // Reconstruct Cumulative P&L and Drawdown charts
  const sortedTrades = [...trades].sort((a, b) => (a.local_time || a.time) - (b.local_time || b.time));
  
  let currentProfit = 0;
  const pnlDataPoints = sortedTrades.map((t) => {
    currentProfit += t.profit;
    return parseFloat(currentProfit.toFixed(2));
  });

  let peak = 0;
  const ddDataPoints = pnlDataPoints.map((pnl) => {
    if (pnl > peak) peak = pnl;
    return parseFloat((pnl - peak).toFixed(2));
  });

  const chartLabels = sortedTrades.map((t) => {
    const dateObj = new Date((t.local_time || t.time) * 1000);
    return dateObj.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
  });

  // Fallback for charts if no trades exist
  const finalLabels = chartLabels.length > 0 ? chartLabels : ['00:00', '06:00', '12:00', '18:00', '24:00'];
  const finalPnlData = pnlDataPoints.length > 0 ? pnlDataPoints : [0, 0, 0, 0, 0];
  const finalDdData = ddDataPoints.length > 0 ? ddDataPoints : [0, 0, 0, 0, 0];

  const pnlChartData = {
    labels: finalLabels,
    datasets: [
      {
        fill: true,
        label: 'Cumulative P&L',
        data: finalPnlData,
        borderColor: '#0cf277',
        backgroundColor: 'rgba(12, 242, 119, 0.05)',
        tension: 0.15,
        pointRadius: finalPnlData.length > 30 ? 0 : 2,
        borderWidth: 2,
      },
    ],
  };

  const ddChartData = {
    labels: finalLabels,
    datasets: [
      {
        fill: true,
        label: 'Peak Drawdown',
        data: finalDdData,
        borderColor: '#ff4a5a',
        backgroundColor: 'rgba(255, 74, 90, 0.05)',
        tension: 0.15,
        pointRadius: finalDdData.length > 30 ? 0 : 2,
        borderWidth: 2,
      },
    ],
  };

  const chartOptions: ChartOptions<'line'> = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: 'rgba(11, 13, 16, 0.95)',
        titleFont: { family: 'Consolas, monospace', size: 10 },
        bodyFont: { family: 'Consolas, monospace', size: 10 },
        borderColor: 'var(--border-color)',
        borderWidth: 1,
        displayColors: false,
      },
    },
    scales: {
      y: {
        display: true,
        grid: { color: 'rgba(26, 29, 34, 0.8)' },
        ticks: {
          color: 'var(--text-muted)',
          font: { family: 'Consolas, monospace', size: 9 },
        },
      },
      x: {
        display: true,
        grid: { display: false },
        ticks: {
          color: 'var(--text-muted)',
          font: { family: 'Consolas, monospace', size: 9 },
        },
      },
    },
  };



  return (
    <div className="workspace workspace-review" style={{ display: 'flex', flexDirection: 'column', gap: '8px', padding: '4px', height: 'calc(100vh - 36px)', overflow: 'hidden' }}>
      
      {/* Left Pane: Analytics Desk */}
      <section className="pane" style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        
        {/* Filters and Controls */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'var(--bg-toolbar)', borderBottom: '1px solid var(--border-color)', padding: '5px 8px', flexShrink: 0 }}>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <label style={{ fontSize: '10px', color: 'var(--text-muted)', fontWeight: 'bold' }}>DATE:</label>
            <select
              value={selectedDate}
              onChange={(e) => setSelectedDate(e.target.value)}
              style={{ background: 'var(--bg-app)', border: '1px solid var(--border-color)', color: 'var(--text-main)', fontSize: '10px', padding: '2px 4px', cursor: 'pointer', outline: 'none' }}
            >
              {availableDates.map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>

            <label style={{ fontSize: '10px', color: 'var(--text-muted)', fontWeight: 'bold', marginLeft: '8px' }}>NODE:</label>
            <select
              value={selectedInstance}
              onChange={(e) => setSelectedInstance(e.target.value)}
              style={{ background: 'var(--bg-app)', border: '1px solid var(--border-color)', color: 'var(--text-main)', fontSize: '10px', padding: '2px 4px', cursor: 'pointer', outline: 'none' }}
            >
              <option value="all">All Channels</option>
              {storeInstances.map((inst) => (
                <option key={inst.id} value={inst.id}>{inst.name}</option>
              ))}
            </select>
          </div>
          
          <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
            {syncResult && <span style={{ fontSize: '9px', color: 'var(--text-muted)', fontFamily: 'monospace' }}>{syncResult}</span>}
            <button
              className="btn-toolbar"
              style={{ borderColor: 'var(--color-active)', color: 'var(--color-active)', padding: '2px 8px' }}
              onClick={handleSyncLogs}
              disabled={isSyncing}
            >
              {isSyncing ? 'Syncing...' : 'Sync Logs'}
            </button>
          </div>
        </div>

        {/* Dashboard Performance Metrics */}
        <div className="pane-content" style={{ display: 'flex', flexDirection: 'column', gap: '8px', padding: '6px', overflowY: 'auto' }}>
          
          {/* KPI Dashboard */}
          <div className="summary-cards" style={{ padding: 0, display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '6px', background: 'transparent' }}>
            <div className="metric-card" style={{ borderLeft: '3px solid var(--color-active)', padding: '6px' }}>
              <div className="metric-label">TOTAL NET PROFIT</div>
              <div className="metric-value" style={{ color: metrics.total_profit >= 0 ? 'var(--color-buy)' : 'var(--color-sell)', fontSize: '15px', marginTop: '2px' }}>
                {metrics.total_profit >= 0 ? '+' : ''}${metrics.total_profit.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
            </div>
            <div className="metric-card" style={{ borderLeft: '3px solid var(--color-pending)', padding: '6px' }}>
              <div className="metric-label">WIN RATE</div>
              <div className="metric-value" style={{ fontSize: '15px', marginTop: '2px', color: 'var(--text-main)' }}>
                {metrics.win_rate.toFixed(1)}%
              </div>
            </div>
            <div className="metric-card" style={{ borderLeft: '3px solid var(--text-muted)', padding: '6px' }}>
              <div className="metric-label">TOTAL EXITS</div>
              <div className="metric-value" style={{ fontSize: '15px', marginTop: '2px', color: 'var(--text-main)' }}>
                {metrics.total_trades} Trades
              </div>
            </div>
          </div>

          {/* Neon Charts */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px', height: '180px', flexShrink: 0 }}>
            <div style={{ background: 'var(--bg-panel)', border: '1px solid var(--border-color)', padding: '6px', display: 'flex', flexDirection: 'column' }}>
              <div className="metric-label" style={{ fontSize: '9px', color: 'var(--text-muted)', marginBottom: '4px', fontWeight: 'bold' }}>CUMULATIVE NET P&L ($)</div>
              <div style={{ flex: 1, position: 'relative', minHeight: 0 }}>
                <Line options={chartOptions} data={pnlChartData} />
              </div>
            </div>
            <div style={{ background: 'var(--bg-panel)', border: '1px solid var(--border-color)', padding: '6px', display: 'flex', flexDirection: 'column' }}>
              <div className="metric-label" style={{ fontSize: '9px', color: 'var(--text-muted)', marginBottom: '4px', fontWeight: 'bold' }}>CLOSED DRAWDOWN WINDOW ($)</div>
              <div style={{ flex: 1, position: 'relative', minHeight: 0 }}>
                <Line options={chartOptions} data={ddChartData} />
              </div>
            </div>
          </div>

          {/* Closed Deal Spreadsheet Table */}
          <div className="table-container" style={{ border: '1px solid var(--border-color)', minHeight: '180px' }}>
            <table className="data-grid" style={{ width: '100%' }}>
              <thead>
                <tr>
                  <th style={{ width: '75px' }}>Ticket</th>
                  <th style={{ width: '70px' }}>Time</th>
                  <th style={{ width: '75px' }}>Instance</th>
                  <th style={{ width: '60px' }}>Symbol</th>
                  <th style={{ width: '55px' }}>Type</th>
                  <th style={{ width: '55px', textAlign: 'right' }}>Volume</th>
                  <th style={{ width: '60px', textAlign: 'right' }}>Comm</th>
                  <th style={{ width: '60px', textAlign: 'right' }}>Swap</th>
                  <th style={{ width: '80px', textAlign: 'right' }}>Profit</th>
                  <th>Comment</th>
                </tr>
              </thead>
              <tbody>
                {isLoadingPerf ? (
                  <tr>
                    <td colSpan={10} style={{ textAlign: 'center', padding: '16px', color: 'var(--text-muted)' }}>Querying database logs...</td>
                  </tr>
                ) : trades.length === 0 ? (
                  <tr>
                    <td colSpan={10} style={{ textAlign: 'center', padding: '16px', color: 'var(--text-muted)' }}>No database entries match current filters.</td>
                  </tr>
                ) : (
                  sortedTrades.reverse().map((t) => {
                    const profitColor = t.profit >= 0 ? 'var(--color-buy)' : 'var(--color-sell)';
                    const dateObj = new Date((t.local_time || t.time) * 1000);
                    const formattedTime = dateObj.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
                    
                    return (
                      <tr key={t.id}>
                        <td style={{ fontFamily: 'monospace', color: 'var(--text-muted)' }}>#{t.ticket}</td>
                        <td style={{ fontFamily: 'monospace' }}>{formattedTime}</td>
                        <td style={{ fontWeight: 'bold' }}>{t.instance_name}</td>
                        <td><strong>{t.symbol}</strong></td>
                        <td>
                          <span className={`badge-dense ${t.type === 'BUY' ? 'bdg-buy' : t.type === 'SELL' ? 'bdg-sell' : 'bdg-active'}`}>
                            {t.type}
                          </span>
                        </td>
                        <td style={{ textAlign: 'right', fontFamily: 'monospace' }}>{t.volume.toFixed(2)}</td>
                        <td style={{ textAlign: 'right', fontFamily: 'monospace', color: 'var(--text-muted)' }}>${t.commission.toFixed(2)}</td>
                        <td style={{ textAlign: 'right', fontFamily: 'monospace', color: 'var(--text-muted)' }}>${t.swap.toFixed(2)}</td>
                        <td style={{ textAlign: 'right', color: profitColor, fontWeight: 'bold', fontFamily: 'monospace' }}>
                          {t.profit >= 0 ? '+' : ''}${t.profit.toFixed(2)}
                        </td>
                        <td style={{ color: 'var(--text-muted)', fontStyle: 'italic', fontSize: '9px' }}>{t.comment || '--'}</td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

        </div>
      </section>

    </div>
  );
};

export default Review;
