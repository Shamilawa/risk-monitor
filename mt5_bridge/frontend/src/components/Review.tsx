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

interface StoryItem {
  id: number;
  magic: number;
  time: string;
  mode: string;
  symbol: string;
  action: string;
  entry: number;
  sl: number;
  tp1: number;
  tp2: number;
  timeframe: string;
  status: string;
  pl: number;
  t1_pl: number | null;
  t2_pl: number | null;
}

interface StoryNotesData {
  summary: {
    total_profit: number;
    total_trades: number;
    win_trades: number;
    loss_trades: number;
  };
  stories: StoryItem[];
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

  // Story Notes Data States
  const [storyData, setStoryData] = useState<StoryNotesData | null>(null);
  const [isLoadingStory, setIsLoadingStory] = useState(false);

  // Fetch dates on mount
  useEffect(() => {
    const fetchDates = async () => {
      try {
        const res = await fetch('/api/story_dates');
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

    const loadStoryNotes = async () => {
      setIsLoadingStory(true);
      try {
        const url = `/api/story_notes?date=${selectedDate}&instance_id=${selectedInstance}`;
        const res = await fetch(url);
        const json = await res.json();
        if (json.summary && json.stories) {
          setStoryData(json);
        } else {
          setStoryData(null);
        }
      } catch (err) {
        console.error('Error loading story notes:', err);
        setStoryData(null);
      } finally {
        setIsLoadingStory(false);
      }
    };

    loadPerformance();
    loadStoryNotes();
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

  const getReportGrade = (wr: number, tradesCount: number) => {
    if (tradesCount === 0) return { letter: '--', desc: 'No trades recorded.' };
    if (wr >= 75) return { letter: 'A+', desc: 'Outstanding execution and win profile.' };
    if (wr >= 60) return { letter: 'A', desc: 'Highly profitable routing window.' };
    if (wr >= 50) return { letter: 'B', desc: 'Positive expectancy maintained.' };
    if (wr >= 40) return { letter: 'C', desc: 'Sub-optimal strategy parameters.' };
    return { letter: 'F', desc: 'Critical drawdown threshold exceeded.' };
  };

  const grade = getReportGrade(metrics.win_rate, metrics.total_trades);

  return (
    <div className="workspace workspace-review" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', padding: '4px', height: 'calc(100vh - 36px)', overflow: 'hidden' }}>
      
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

      {/* Right Pane: Report Chronology Sheet */}
      <section className="pane" style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <div className="pane-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0 }}>
          <span>Chronological Audit Log</span>
          <button className="btn-toolbar" style={{ borderColor: 'var(--border-color)' }} onClick={() => window.print()}>
            Export PDF (Print)
          </button>
        </div>
        
        <div className="pane-content" style={{ padding: '15px', background: 'var(--bg-app)', flexGrow: 1, overflowY: 'auto' }}>
          
          <div className="a4-sheet" style={{ background: 'var(--bg-panel)', border: '1px solid var(--border-color)', padding: '20px', minHeight: '100%', fontFamily: 'monospace', display: 'flex', flexDirection: 'column' }}>
            
            {/* Report Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '15px' }}>
              <div>
                <span style={{ fontSize: '8px', fontWeight: 'bold', letterSpacing: '1px', color: 'var(--text-muted)' }}>REPORT ID: VTC-{selectedDate.replace(/-/g, '')}</span>
                <h2 style={{ margin: '3px 0 0 0', fontSize: '15px', color: 'var(--text-main)', fontWeight: 'bold' }}>DAILY SIGNAL & EXECUTION AUDIT</h2>
              </div>
              <div style={{ textAlign: 'right' }}>
                <span style={{ fontSize: '8px', color: 'var(--text-muted)' }}>STATUS: SYSTEM VERIFIED</span>
                <div style={{ fontSize: '9px', color: 'var(--text-main)', marginTop: '2px' }}>
                  {new Date().toLocaleTimeString('en-US', { hour12: false })}
                </div>
              </div>
            </div>

            {/* Meta Metadata Header */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '6px', background: 'var(--bg-toolbar)', border: '1px solid var(--border-color)', padding: '6px', fontSize: '9px', marginBottom: '15px' }}>
              <div>
                <div style={{ color: 'var(--text-muted)', fontSize: '8px' }}>DATE</div>
                <strong style={{ color: 'var(--text-main)' }}>{selectedDate}</strong>
              </div>
              <div>
                <div style={{ color: 'var(--text-muted)', fontSize: '8px' }}>CHANNEL</div>
                <strong style={{ color: 'var(--text-main)' }}>{selectedInstance === 'all' ? 'All Channels' : storeInstances.find(i => i.id.toString() === selectedInstance)?.name || 'Filtered'}</strong>
              </div>
              <div>
                <div style={{ color: 'var(--text-muted)', fontSize: '8px' }}>NET SUM</div>
                <strong style={{ color: storyData?.summary.total_profit && storyData.summary.total_profit >= 0 ? 'var(--color-buy)' : 'var(--color-sell)' }}>
                  ${storyData?.summary.total_profit.toFixed(2) || '0.00'}
                </strong>
              </div>
              <div>
                <div style={{ color: 'var(--text-muted)', fontSize: '8px' }}>WIN RATE</div>
                <strong style={{ color: 'var(--text-main)' }}>
                  {storyData?.summary.total_trades && storyData.summary.total_trades > 0 
                    ? ((storyData.summary.win_trades / storyData.summary.total_trades) * 100).toFixed(1) + '%'
                    : '0.0%'}
                </strong>
              </div>
            </div>

            <div style={{ borderTop: '2px double var(--border-color)', marginBottom: '15px' }}></div>

            {/* Performance metrics breakdown */}
            <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 0.8fr', gap: '15px', marginBottom: '20px' }}>
              <div>
                <h4 style={{ fontSize: '10px', color: 'var(--text-main)', borderBottom: '1px solid var(--border-color)', paddingBottom: '3px', marginBottom: '6px' }}>I. METRIC ANALYSIS</h4>
                <table style={{ width: '100%', fontSize: '9.5px', borderCollapse: 'collapse' }}>
                  <tbody>
                    <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                      <td style={{ padding: '3px 0', color: 'var(--text-muted)' }}>Net profit/loss of signals</td>
                      <td style={{ textAlign: 'right', fontWeight: 'bold', color: metrics.total_profit >= 0 ? 'var(--color-buy)' : 'var(--color-sell)' }}>
                        ${metrics.total_profit.toFixed(2)}
                      </td>
                    </tr>
                    <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                      <td style={{ padding: '3px 0', color: 'var(--text-muted)' }}>Total executions mapped</td>
                      <td style={{ textAlign: 'right', color: 'var(--text-main)' }}>{storyData?.summary.total_trades || 0}</td>
                    </tr>
                    <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                      <td style={{ padding: '3px 0', color: 'var(--text-muted)' }}>Profitable signal groups</td>
                      <td style={{ textAlign: 'right', color: 'var(--color-buy)' }}>{storyData?.summary.win_trades || 0}</td>
                    </tr>
                    <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                      <td style={{ padding: '3px 0', color: 'var(--text-muted)' }}>Unprofitable signal groups</td>
                      <td style={{ textAlign: 'right', color: 'var(--color-sell)' }}>{storyData?.summary.loss_trades || 0}</td>
                    </tr>
                  </tbody>
                </table>
              </div>

              {/* Visual Performance Card */}
              <div style={{ border: '1px solid var(--border-color)', background: 'var(--bg-toolbar)', borderRadius: '2px', padding: '8px', display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', textAlign: 'center' }}>
                <span style={{ fontSize: '8px', color: 'var(--text-muted)', fontWeight: 'bold' }}>PERFORMANCE RATING</span>
                <div style={{ fontSize: '24px', fontWeight: 'bold', color: metrics.win_rate >= 50 ? 'var(--color-buy)' : 'var(--color-sell)', margin: '4px 0' }}>
                  {grade.letter}
                </div>
                <span style={{ fontSize: '8px', color: 'var(--text-muted)', lineHeight: '1.2' }}>{grade.desc}</span>
              </div>
            </div>

            {/* Chronological Signals log */}
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
              <h4 style={{ fontSize: '10px', color: 'var(--text-main)', borderBottom: '1px solid var(--border-color)', paddingBottom: '3px', marginBottom: '8px' }}>II. SIGNAL TIMELINE CHRONOLOGY</h4>
              
              <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '10px', paddingRight: '4px' }}>
                {isLoadingStory ? (
                  <div style={{ color: 'var(--text-muted)', fontSize: '10px', padding: '15px 0', textAlign: 'center', fontStyle: 'italic' }}>
                    Reading signal logs...
                  </div>
                ) : !storyData || storyData.stories.length === 0 ? (
                  <div style={{ color: 'var(--text-muted)', fontSize: '10px', padding: '15px 0', textAlign: 'center', fontStyle: 'italic' }}>
                    No signals or executions logged for the selected date.
                  </div>
                ) : (
                  storyData.stories.map((s) => {
                    const isWin = s.pl >= 0;
                    const statusColor = s.status === 'FAILED_EXECUTION' ? 'var(--color-sell)' : s.status === 'CANCELLED' ? 'var(--text-muted)' : 'var(--color-buy)';
                    
                    return (
                      <div key={s.id} style={{ border: '1px solid var(--border-color)', background: 'var(--bg-toolbar)', padding: '6px' }}>
                        {/* Title Row */}
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px dashed var(--border-color)', paddingBottom: '4px', marginBottom: '4px' }}>
                          <div>
                            <span style={{ color: 'var(--text-muted)', fontSize: '8px' }}>[{s.time}]</span>{' '}
                            <strong style={{ color: 'var(--text-main)' }}>{s.symbol}</strong>{' '}
                            <span className={s.action === 'BUY' ? 'bdg-buy' : 'bdg-sell'} style={{ padding: '0 4px', fontSize: '8px', borderRadius: '1px' }}>{s.action}</span>
                          </div>
                          <span style={{ fontSize: '9px', fontWeight: 'bold', color: statusColor }}>
                            {s.status.replace(/_/g, ' ')}
                          </span>
                        </div>

                        {/* Parameter details */}
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '4px', fontSize: '8.5px', color: 'var(--text-muted)', margin: '4px 0' }}>
                          <div>ENTRY: <strong style={{ color: 'var(--text-main)' }}>{s.entry}</strong></div>
                          <div>SL: <strong style={{ color: 'var(--text-main)' }}>{s.sl}</strong></div>
                          <div>TP1: <strong style={{ color: 'var(--text-main)' }}>{s.tp1}</strong></div>
                          <div>TP2: <strong style={{ color: 'var(--text-main)' }}>{s.tp2}</strong></div>
                        </div>

                        {/* Result Row */}
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '9px', marginTop: '4px', borderTop: '1px dotted var(--border-color)', paddingTop: '4px' }}>
                          <div>
                            <span>Timeframe: <strong>{s.timeframe}</strong></span>
                            <span style={{ marginLeft: '10px' }}>Magic: <strong>#{s.magic}</strong></span>
                          </div>
                          <div>
                            NET RESULT:{' '}
                            <strong style={{ color: isWin ? 'var(--color-buy)' : 'var(--color-sell)' }}>
                              {isWin ? '+' : ''}${s.pl.toFixed(2)}
                            </strong>
                          </div>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>

            {/* Footer */}
            <div style={{ marginTop: 'auto', borderTop: '1px dashed var(--border-color)', paddingTop: '6px', display: 'flex', justifyContent: 'space-between', fontSize: '8px', color: 'var(--text-muted)' }}>
              <span>VTC BRIDGE AUDIT DOCUMENT SYSTEM</span>
              <span>CONFIDENTIAL DEEP COPIER LOG REPORT</span>
            </div>

          </div>

        </div>
      </section>

    </div>
  );
};

export default Review;
