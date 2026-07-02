import { useState, useEffect } from 'react';
import { useStore } from '../store/useStore';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Title,
  Tooltip,
  Filler,
  Legend,
  type ChartOptions,
} from 'chart.js';
import { Line, Bar } from 'react-chartjs-2';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
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
  const [dateRangeType, setDateRangeType] = useState<string>('this_month');
  const [availableDates, setAvailableDates] = useState<string[]>([]);
  const [selectedDate, setSelectedDate] = useState<string>('');
  const [customStartDate, setCustomStartDate] = useState<string>('');
  const [customEndDate, setCustomEndDate] = useState<string>('');
  const [selectedInstance, setSelectedInstance] = useState<string>('all');
  
  // Sync state
  const [isSyncing, setIsSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<string>('');

  // Performance Data States
  const [trades, setTrades] = useState<PerformanceTrade[]>([]);
  const [isLoadingPerf, setIsLoadingPerf] = useState(false);

  // Tradervue reports Information Architecture Tabs
  const [activeTab, setActiveTab] = useState<'overview' | 'detailed' | 'breakdowns' | 'ledger'>('overview');

  // Ledger Filter & Pagination States
  const [ledgerSearch, setLedgerSearch] = useState<string>('');
  const [ledgerTypeFilter, setLedgerTypeFilter] = useState<string>('all');
  const [ledgerOutcomeFilter, setLedgerOutcomeFilter] = useState<string>('all');
  const [ledgerPage, setLedgerPage] = useState<number>(1);
  const [ledgerPageSize, setLedgerPageSize] = useState<number>(20);
  const [ledgerSortField, setLedgerSortField] = useState<string>('time');
  const [ledgerSortOrder, setLedgerSortOrder] = useState<'asc' | 'desc'>('desc');

  // Fetch dates on mount (for Single Date filter fallback list)
  useEffect(() => {
    const fetchDates = async () => {
      try {
        const res = await fetch('/api/review_dates');
        const json = await res.json();
        if (json.dates && json.dates.length > 0) {
          setAvailableDates(json.dates);
          setSelectedDate(json.dates[0]);
        } else {
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

  // Helper: compute start and end epochs for query
  const getDateRangeEpochs = (
    rangeType: string,
    dateVal: string,
    startVal: string,
    endVal: string
  ) => {
    const now = new Date();
    let start = new Date();
    let end = new Date();

    switch (rangeType) {
      case 'today':
        start.setHours(0, 0, 0, 0);
        end.setHours(23, 59, 59, 999);
        break;
      case 'yesterday':
        start.setDate(start.getDate() - 1);
        start.setHours(0, 0, 0, 0);
        end.setDate(end.getDate() - 1);
        end.setHours(23, 59, 59, 999);
        break;
      case 'this_week': {
        const day = start.getDay();
        const diff = start.getDate() - day + (day === 0 ? -6 : 1); // Monday
        start.setDate(diff);
        start.setHours(0, 0, 0, 0);
        end.setHours(23, 59, 59, 999);
        break;
      }
      case 'this_month':
        start.setDate(1);
        start.setHours(0, 0, 0, 0);
        end.setHours(23, 59, 59, 999);
        break;
      case 'last_30_days':
        start.setDate(start.getDate() - 30);
        start.setHours(0, 0, 0, 0);
        end.setHours(23, 59, 59, 999);
        break;
      case 'all_time':
        return { startEpoch: 0, endEpoch: Math.floor(now.getTime() / 1000) };
      case 'single_date':
        if (dateVal) {
          const d = new Date(dateVal);
          d.setHours(0, 0, 0, 0);
          const sEpoch = Math.floor(d.getTime() / 1000);
          d.setHours(23, 59, 59, 999);
          const eEpoch = Math.floor(d.getTime() / 1000);
          return { startEpoch: sEpoch, endEpoch: eEpoch };
        }
        start.setHours(0, 0, 0, 0);
        end.setHours(23, 59, 59, 999);
        break;
      case 'custom':
        if (startVal) {
          const s = new Date(startVal);
          s.setHours(0, 0, 0, 0);
          start = s;
        } else {
          start.setDate(start.getDate() - 7);
          start.setHours(0, 0, 0, 0);
        }
        if (endVal) {
          const e = new Date(endVal);
          e.setHours(23, 59, 59, 999);
          end = e;
        } else {
          end.setHours(23, 59, 59, 999);
        }
        break;
      default:
        start.setDate(1);
        start.setHours(0, 0, 0, 0);
        end.setHours(23, 59, 59, 999);
    }

    return {
      startEpoch: Math.floor(start.getTime() / 1000),
      endEpoch: Math.floor(end.getTime() / 1000),
    };
  };

  // Fetch performance whenever filters change
  useEffect(() => {
    const { startEpoch, endEpoch } = getDateRangeEpochs(dateRangeType, selectedDate, customStartDate, customEndDate);

    const loadPerformance = async () => {
      setIsLoadingPerf(true);
      try {
        const url = `/api/performance?instance_id=${selectedInstance}&start_time=${startEpoch}&end_time=${endEpoch}`;
        const res = await fetch(url);
        const json = await res.json();
        if (json.trades) {
          setTrades(json.trades || []);
        } else {
          setTrades([]);
        }
      } catch (err) {
        console.error('Error loading performance details:', err);
      } finally {
        setIsLoadingPerf(false);
      }
    };

    loadPerformance();
    setLedgerPage(1);
  }, [dateRangeType, selectedDate, customStartDate, customEndDate, selectedInstance]);

  // Sync logs mutation
  const handleSyncLogs = async () => {
    setIsSyncing(true);
    setSyncResult('Syncing...');
    try {
      const res = await fetch('/api/sync_log', { method: 'POST' });
      const json = await res.json();
      if (json.status === 'success') {
        setSyncResult(`Synced ${json.synced} deals.`);
        const temp = dateRangeType;
        setDateRangeType('');
        setTimeout(() => setDateRangeType(temp), 50);
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

  // Calendar Weekly Strip Navigation Helpers
  const shiftWeekPrev = () => {
    const current = customEndDate ? new Date(customEndDate) : new Date();
    current.setDate(current.getDate() - 7);
    setCustomEndDate(current.toISOString().split('T')[0]);
    setDateRangeType('custom');
  };

  const shiftWeekNext = () => {
    const current = customEndDate ? new Date(customEndDate) : new Date();
    current.setDate(current.getDate() + 7);
    setCustomEndDate(current.toISOString().split('T')[0]);
    setDateRangeType('custom');
  };

  const shiftWeekToday = () => {
    const todayStr = new Date().toISOString().split('T')[0];
    setCustomEndDate(todayStr);
    setDateRangeType('this_week');
  };

  // --- STATS CALCULATIONS ---
  const validTrades = trades.filter((t) => t.type !== 'BALANCE');
  const sortedTrades = [...validTrades].sort((a, b) => (a.local_time || a.time) - (b.local_time || b.time));
  
  // WCAG compliant text colors
  const colorWin = '#10b981'; // emerald green (contrast > 4.5:1 on dark)
  const colorLoss = '#f87171'; // pastel red (contrast > 4.5:1 on dark)
  const colorLong = '#60a5fa'; // pastel blue (contrast > 4.5:1 on dark)
  const colorShort = '#fb923c'; // pastel orange (contrast > 4.5:1 on dark)

  // 1. Net P&L (Includes commissions & swaps)
  const totalNetProfit = validTrades.reduce((acc, t) => acc + t.profit, 0);
  
  // 2. Gross Profits & Gross Losses
  const grossProfit = validTrades.reduce((acc, t) => t.profit > 0 ? acc + t.profit : acc, 0);
  const grossLoss = validTrades.reduce((acc, t) => t.profit < 0 ? acc + t.profit : acc, 0);
  
  // 3. Profit Factor (Gross Win / Gross Loss)
  const profitFactor = Math.abs(grossLoss) > 0 ? (grossProfit / Math.abs(grossLoss)) : (grossProfit > 0 ? 99.9 : 0);
  
  // 4. Trade Count & Outcomes
  const totalTrades = validTrades.length;
  const winningTrades = validTrades.filter(t => t.profit > 0).length;
  const losingTrades = validTrades.filter(t => t.profit < 0).length;
  const breakevenTrades = validTrades.filter(t => t.profit === 0).length;
  
  // 5. Win Rate
  const winRate = totalTrades > 0 ? (winningTrades / totalTrades) * 100 : 0;
  
  // 6. Average Win / Average Loss & Ratio
  const avgWin = winningTrades > 0 ? grossProfit / winningTrades : 0;
  const avgLoss = losingTrades > 0 ? grossLoss / losingTrades : 0;
  const winLossRatio = Math.abs(avgLoss) > 0 ? Math.abs(avgWin / avgLoss) : (avgWin > 0 ? 99.9 : 0);
  
  // 7. Expectancy (Avg net profit per trade)
  const tradeExpectancy = totalTrades > 0 ? totalNetProfit / totalTrades : 0;
  
  // 8. Best Win & Worst Loss
  const bestTrade = validTrades.reduce((max, t) => t.profit > max ? t.profit : max, 0);
  const worstTrade = validTrades.reduce((min, t) => t.profit < min ? t.profit : min, 0);
  
  // 9. Total Volume / Avg Volume
  const totalVolume = validTrades.reduce((acc, t) => acc + t.volume, 0);
  const avgVolume = totalTrades > 0 ? totalVolume / totalTrades : 0;
  
  // 10. Total Fees
  const totalComm = validTrades.reduce((acc, t) => acc + t.commission, 0);
  const totalSwap = validTrades.reduce((acc, t) => acc + t.swap, 0);
  const totalFees = totalComm + totalSwap;

  // 11. Max Streaks
  let maxWinStreak = 0;
  let maxLossStreak = 0;
  let currentWinStreak = 0;
  let currentLossStreak = 0;

  sortedTrades.forEach((t) => {
    if (t.profit > 0) {
      currentWinStreak++;
      if (currentWinStreak > maxWinStreak) maxWinStreak = currentWinStreak;
      currentLossStreak = 0;
    } else if (t.profit < 0) {
      currentLossStreak++;
      if (currentLossStreak > maxLossStreak) maxLossStreak = currentLossStreak;
      currentWinStreak = 0;
    } else {
      currentWinStreak = 0;
      currentLossStreak = 0;
    }
  });

  // 12. Hold Time Calculations
  let totalHoldTime = 0;
  let winHoldTime = 0;
  let lossHoldTime = 0;
  let holdCount = 0;
  let winHoldCount = 0;
  let lossHoldCount = 0;

  // Buckets
  let scalpCount = 0;
  let scalpProfit = 0;
  let intradayCount = 0;
  let intradayProfit = 0;
  let swingCount = 0;
  let swingProfit = 0;

  validTrades.forEach((t) => {
    const openTime = t.local_start_time;
    const closeTime = t.local_time || t.time;
    if (openTime && closeTime && closeTime > openTime) {
      const durationSec = closeTime - openTime;
      totalHoldTime += durationSec;
      holdCount++;

      if (t.profit > 0) {
        winHoldTime += durationSec;
        winHoldCount++;
      } else if (t.profit < 0) {
        lossHoldTime += durationSec;
        lossHoldCount++;
      }

      // Categorizations
      const mins = durationSec / 60;
      if (mins < 5) {
        scalpCount++;
        scalpProfit += t.profit;
      } else if (mins <= 60) {
        intradayCount++;
        intradayProfit += t.profit;
      } else {
        swingCount++;
        swingProfit += t.profit;
      }
    }
  });

  const formatDuration = (sec: number) => {
    if (sec <= 0 || isNaN(sec)) return '--';
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = Math.floor(sec % 60);

    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
  };

  const avgHoldTimeStr = holdCount > 0 ? formatDuration(totalHoldTime / holdCount) : '--';
  const avgWinHoldTimeStr = winHoldCount > 0 ? formatDuration(winHoldTime / winHoldCount) : '--';
  const avgLossHoldTimeStr = lossHoldCount > 0 ? formatDuration(lossHoldTime / lossHoldCount) : '--';

  // --- LONG VS SHORT ---
  const buyTrades = validTrades.filter(t => t.type === 'BUY');
  const sellTrades = validTrades.filter(t => t.type === 'SELL');

  const buyNetProfit = buyTrades.reduce((acc, t) => acc + t.profit, 0);
  const buyTradesCount = buyTrades.length;
  const buyWinsCount = buyTrades.filter(t => t.profit > 0).length;
  const buyWinRate = buyTradesCount > 0 ? (buyWinsCount / buyTradesCount) * 100 : 0;

  const sellNetProfit = sellTrades.reduce((acc, t) => acc + t.profit, 0);
  const sellTradesCount = sellTrades.length;
  const sellWinsCount = sellTrades.filter(t => t.profit > 0).length;
  const sellWinRate = sellTradesCount > 0 ? (sellWinsCount / sellTradesCount) * 100 : 0;

  // --- WIDGET & ACCESSIBILITY COMPUTATIONS ---
  const radius = 18;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (winRate / 100) * circumference;
  const winRatio = (avgWin + Math.abs(avgLoss)) > 0 ? avgWin / (avgWin + Math.abs(avgLoss)) : 0.5;
  const pfPercentage = Math.min(100, (profitFactor / 3) * 100);
  const winsPct = totalTrades > 0 ? (winningTrades / totalTrades) * 100 : 0;
  const lossesPct = totalTrades > 0 ? (losingTrades / totalTrades) * 100 : 0;
  const bePct = totalTrades > 0 ? (breakevenTrades / totalTrades) * 100 : 0;
  const totalLongShort = buyTradesCount + sellTradesCount;
  const buyPct = totalLongShort > 0 ? (buyTradesCount / totalLongShort) * 100 : 0;
  const sellPct = totalLongShort > 0 ? (sellTradesCount / totalLongShort) * 100 : 0;

  // --- DAILY STRIP CALENDAR (LAST 7 CALENDAR DAYS) ---
  const dailyStatsMap: Record<string, { profit: number; tradesCount: number }> = {};
  sortedTrades.forEach((t) => {
    const d = new Date((t.local_time || t.time) * 1000);
    const dateStr = d.toISOString().split('T')[0];
    if (!dailyStatsMap[dateStr]) {
      dailyStatsMap[dateStr] = { profit: 0, tradesCount: 0 };
    }
    dailyStatsMap[dateStr].profit += t.profit;
    dailyStatsMap[dateStr].tradesCount += 1;
  });

  const dailyStripCards = [];
  const endDateObj = customEndDate ? new Date(customEndDate) : new Date();
  const activeMonthYearStr = endDateObj.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });

  for (let i = 6; i >= 0; i--) {
    const day = new Date(endDateObj);
    day.setDate(day.getDate() - i);
    const dateStr = day.toISOString().split('T')[0];
    const stat = dailyStatsMap[dateStr] || { profit: 0, tradesCount: 0 };

    const dayName = day.toLocaleDateString('en-US', { weekday: 'short' });
    const dayNum = day.toLocaleDateString('en-US', { day: '2-digit' });
    const monthName = day.toLocaleDateString('en-US', { month: 'short' });

    dailyStripCards.push({
      dateStr,
      dayName,
      dayNum,
      monthName,
      profit: stat.profit,
      tradesCount: stat.tradesCount,
      active: stat.tradesCount > 0,
    });
  }


  // --- CHART 1: Cumulative P&L ---
  let rollingProfit = 0;
  const pnlDataPoints = sortedTrades.map((t) => {
    rollingProfit += t.profit;
    return parseFloat(rollingProfit.toFixed(2));
  });

  const chartLabels = sortedTrades.map((t) => {
    const dateObj = new Date((t.local_time || t.time) * 1000);
    return dateObj.toLocaleDateString('en-US', { month: '2-digit', day: '2-digit' });
  });

  const finalLabels = chartLabels.length > 0 ? chartLabels : ['--/--'];
  const lineChartData = {
    labels: finalLabels,
    datasets: [
      {
        fill: true,
        label: 'Cumulative Net P&L',
        data: pnlDataPoints.length > 0 ? pnlDataPoints : [0],
        borderColor: colorWin,
        backgroundColor: 'rgba(16, 185, 129, 0.05)',
        tension: 0.15,
        pointRadius: (pnlDataPoints.length > 30) ? 0 : 2,
        borderWidth: 2,
      },
    ],
  };

  const lineChartOptions: ChartOptions<'line'> = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: '#0f1320',
        titleFont: { family: 'inherit', size: 10, weight: 'bold' },
        bodyFont: { family: 'inherit', size: 10 },
        borderColor: '#1c2230',
        borderWidth: 1,
        displayColors: false,
      },
    },
    scales: {
      y: {
        display: true,
        grid: { color: '#181f2e' },
        ticks: {
          color: '#9ca3af',
          font: { family: 'inherit', size: 9 },
        },
      },
      x: {
        display: true,
        grid: { display: false },
        ticks: {
          color: '#9ca3af',
          font: { family: 'inherit', size: 8 },
          autoSkip: true,
          maxTicksLimit: 6,
          maxRotation: 0,
          minRotation: 0,
        },
      },
    },
  };

  // --- CHART 2: Drawdown ---
  let peak = 0;
  const ddDataPoints = pnlDataPoints.map((pnl) => {
    if (pnl > peak) peak = pnl;
    return parseFloat((pnl - peak).toFixed(2));
  });

  const ddChartData = {
    labels: finalLabels,
    datasets: [
      {
        label: 'Peak Drawdown',
        data: ddDataPoints.length > 0 ? ddDataPoints : [0],
        backgroundColor: 'rgba(248, 113, 113, 0.4)',
        borderColor: colorLoss,
        borderWidth: 1.5,
        borderRadius: 3,
      },
    ],
  };

  // --- CHART 3: Net Daily P&L ---
  const dailyPnlMapForChart: Record<string, number> = {};
  sortedTrades.forEach((t) => {
    const dateStr = new Date((t.local_time || t.time) * 1000).toLocaleDateString('en-US', { month: '2-digit', day: '2-digit' });
    dailyPnlMapForChart[dateStr] = (dailyPnlMapForChart[dateStr] || 0) + t.profit;
  });

  const dailyPnlLabels = Object.keys(dailyPnlMapForChart).sort();
  const dailyPnlValues = dailyPnlLabels.map((date) => parseFloat(dailyPnlMapForChart[date].toFixed(2)));

  const dailyPnlChartData = {
    labels: dailyPnlLabels.length > 0 ? dailyPnlLabels : ['--/--'],
    datasets: [
      {
        label: 'Daily Net P&L',
        data: dailyPnlValues.length > 0 ? dailyPnlValues : [0],
        backgroundColor: dailyPnlValues.map(pnl => pnl >= 0 ? 'rgba(16, 185, 129, 0.5)' : 'rgba(248, 113, 113, 0.5)'),
        borderColor: dailyPnlValues.map(pnl => pnl >= 0 ? colorWin : colorLoss),
        borderWidth: 1.5,
        borderRadius: 3,
      }
    ]
  };

  const dailyBarChartOptions: ChartOptions<'bar'> = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: '#0f1320',
        titleFont: { family: 'inherit', size: 10, weight: 'bold' },
        bodyFont: { family: 'inherit', size: 10 },
        borderColor: '#1c2230',
        borderWidth: 1,
        displayColors: false,
      },
    },
    scales: {
      y: {
        grid: { color: '#181f2e' },
        ticks: {
          color: '#9ca3af',
          font: { family: 'inherit', size: 9 },
        },
      },
      x: {
        grid: { display: false },
        ticks: {
          color: '#9ca3af',
          font: { family: 'inherit', size: 8 },
        },
      },
    },
  };

  // --- GROUPING: Symbols Performance ---
  const symbolStats: Record<string, { netProfit: number; tradesCount: number; winsCount: number; volume: number }> = {};
  validTrades.forEach((t) => {
    const sym = t.symbol.toUpperCase();
    if (!symbolStats[sym]) {
      symbolStats[sym] = { netProfit: 0, tradesCount: 0, winsCount: 0, volume: 0 };
    }
    symbolStats[sym].netProfit += t.profit;
    symbolStats[sym].tradesCount += 1;
    if (t.profit > 0) symbolStats[sym].winsCount += 1;
    symbolStats[sym].volume += t.volume;
  });

  const symbolList = Object.entries(symbolStats).map(([symbol, stat]) => ({
    symbol,
    netProfit: stat.netProfit,
    tradesCount: stat.tradesCount,
    winRate: stat.tradesCount > 0 ? (stat.winsCount / stat.tradesCount) * 100 : 0,
    volume: stat.volume,
  })).sort((a, b) => b.netProfit - a.netProfit);

  const symbolChartData = {
    labels: symbolList.map(s => s.symbol),
    datasets: [
      {
        label: 'Net P&L ($)',
        data: symbolList.map(s => parseFloat(s.netProfit.toFixed(2))),
        backgroundColor: symbolList.map(s => s.netProfit >= 0 ? 'rgba(16, 185, 129, 0.4)' : 'rgba(248, 113, 113, 0.4)'),
        borderColor: symbolList.map(s => s.netProfit >= 0 ? colorWin : colorLoss),
        borderWidth: 1.5,
        borderRadius: 3,
      }
    ]
  };

  // --- GROUPING: Day of Week ---
  const dayStats: Record<string, { netProfit: number; tradesCount: number; winsCount: number }> = {
    'Monday': { netProfit: 0, tradesCount: 0, winsCount: 0 },
    'Tuesday': { netProfit: 0, tradesCount: 0, winsCount: 0 },
    'Wednesday': { netProfit: 0, tradesCount: 0, winsCount: 0 },
    'Thursday': { netProfit: 0, tradesCount: 0, winsCount: 0 },
    'Friday': { netProfit: 0, tradesCount: 0, winsCount: 0 },
  };

  validTrades.forEach((t) => {
    const closeTime = t.local_time || t.time;
    if (closeTime) {
      const dayName = daysOfWeek[new Date(closeTime * 1000).getDay()];
      if (dayStats[dayName] !== undefined) {
        dayStats[dayName].netProfit += t.profit;
        dayStats[dayName].tradesCount += 1;
        if (t.profit > 0) dayStats[dayName].winsCount += 1;
      }
    }
  });

  const daysLabels = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'];
  const dayPnlData = daysLabels.map(day => parseFloat((dayStats[day]?.netProfit || 0).toFixed(2)));
  const dayChartData = {
    labels: daysLabels,
    datasets: [
      {
        label: 'P&L by Day ($)',
        data: dayPnlData,
        backgroundColor: dayPnlData.map(pnl => pnl >= 0 ? 'rgba(16, 185, 129, 0.4)' : 'rgba(248, 113, 113, 0.4)'),
        borderColor: dayPnlData.map(pnl => pnl >= 0 ? colorWin : colorLoss),
        borderWidth: 1.5,
        borderRadius: 3,
      }
    ]
  };

  // --- GROUPING: Hourly Session ---
  const hourStats: Record<number, { netProfit: number; tradesCount: number }> = {};
  for (let h = 0; h < 24; h++) {
    hourStats[h] = { netProfit: 0, tradesCount: 0 };
  }

  validTrades.forEach((t) => {
    const closeTime = t.local_time || t.time;
    if (closeTime) {
      const hour = new Date(closeTime * 1000).getHours();
      hourStats[hour].netProfit += t.profit;
      hourStats[hour].tradesCount += 1;
    }
  });

  const hourLabels = Array.from({ length: 24 }, (_, i) => `${i.toString().padStart(2, '0')}:00`);
  const hourPnlData = Array.from({ length: 24 }, (_, i) => parseFloat((hourStats[i]?.netProfit || 0).toFixed(2)));
  const hourChartData = {
    labels: hourLabels,
    datasets: [
      {
        label: 'P&L by Hour ($)',
        data: hourPnlData,
        backgroundColor: hourPnlData.map(pnl => pnl >= 0 ? 'rgba(16, 185, 129, 0.4)' : 'rgba(248, 113, 113, 0.4)'),
        borderColor: hourPnlData.map(pnl => pnl >= 0 ? colorWin : colorLoss),
        borderWidth: 1.5,
        borderRadius: 2,
      }
    ]
  };

  // --- LEDGER FILTERING, SORTING & PAGINATION ---
  const handleSort = (field: string) => {
    if (ledgerSortField === field) {
      setLedgerSortOrder(ledgerSortOrder === 'asc' ? 'desc' : 'asc');
    } else {
      setLedgerSortField(field);
      setLedgerSortOrder('desc');
    }
    setLedgerPage(1);
  };

  const filteredLedgerTrades = sortedTrades.filter((t) => {
    if (ledgerSearch && !t.symbol.toLowerCase().includes(ledgerSearch.toLowerCase())) {
      return false;
    }
    if (ledgerTypeFilter !== 'all' && t.type !== ledgerTypeFilter) {
      return false;
    }
    if (ledgerOutcomeFilter === 'wins' && t.profit <= 0) return false;
    if (ledgerOutcomeFilter === 'losses' && t.profit >= 0) return false;
    if (ledgerOutcomeFilter === 'breakeven' && t.profit !== 0) return false;
    return true;
  });

  const sortedLedgerTrades = [...filteredLedgerTrades].sort((a, b) => {
    let valA: any = 0;
    let valB: any = 0;

    switch (ledgerSortField) {
      case 'ticket':
        valA = a.ticket;
        valB = b.ticket;
        break;
      case 'time':
        valA = a.local_time || a.time;
        valB = b.local_time || b.time;
        break;
      case 'symbol':
        valA = a.symbol;
        valB = b.symbol;
        break;
      case 'type':
        valA = a.type;
        valB = b.type;
        break;
      case 'volume':
        valA = a.volume;
        valB = b.volume;
        break;
      case 'profit':
        valA = a.profit;
        valB = b.profit;
        break;
      default:
        valA = a.local_time || a.time;
        valB = b.local_time || b.time;
    }

    if (typeof valA === 'string') {
      return ledgerSortOrder === 'asc' ? valA.localeCompare(valB) : valB.localeCompare(valA);
    } else {
      return ledgerSortOrder === 'asc' ? valA - valB : valB - valA;
    }
  });

  const totalLedgerItems = sortedLedgerTrades.length;
  const totalLedgerPages = Math.max(1, Math.ceil(totalLedgerItems / ledgerPageSize));
  const ledgerStartIndex = (ledgerPage - 1) * ledgerPageSize;
  const paginatedLedgerTrades = sortedLedgerTrades.slice(ledgerStartIndex, ledgerStartIndex + ledgerPageSize);


  // --- HEALTH CARD COMPUTATION ---
  let healthName = 'All Accounts';
  let healthBalance = 0;
  let healthEquity = 0;
  let healthTrades = 0;

  if (selectedInstance === 'all') {
    storeInstances.forEach(inst => {
      healthBalance += inst.balance || 0;
      healthEquity += inst.equity || 0;
      healthTrades += inst.positions?.length || 0;
    });
  } else {
    const inst = storeInstances.find(i => i.id.toString() === selectedInstance);
    if (inst) {
      healthName = inst.name;
      healthBalance = inst.balance || 0;
      healthEquity = inst.equity || 0;
      healthTrades = inst.positions?.length || 0;
    }
  }

  const healthFloatingPnl = healthEquity - healthBalance;
  const healthPnlAbs = Math.abs(healthFloatingPnl);
  const healthPnlSign = healthFloatingPnl > 0 ? '+' : (healthFloatingPnl < 0 ? '-' : '');
  const healthPnlPct = healthBalance > 0 ? ((healthPnlAbs / healthBalance) * 100).toFixed(2) : '0.00';
  const healthPnlText = `${healthPnlSign}$${healthPnlAbs.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} (${healthPnlPct}%)`;
  const healthPnlColor = healthFloatingPnl > 0 ? colorWin : (healthFloatingPnl < 0 ? colorLoss : '#9ca3af');

  const healthRealizedColor = totalNetProfit >= 0 ? colorWin : colorLoss;
  const healthRealizedText = `${totalNetProfit >= 0 ? '+' : ''}$${totalNetProfit.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;


  // --- REFINED PREMIUM STYLING ---
  const premiumCardStyle = {
    background: 'var(--bg-panel)',
    border: '1px solid var(--border-color)',
    borderRadius: '8px',
    display: 'flex',
    flexDirection: 'column' as const,
    overflow: 'hidden',
  };

  const premiumCardHeaderStyle = {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '6px 8px',
    borderBottom: '1px solid var(--border-color)',
    background: 'var(--bg-toolbar)',
    fontWeight: 'bold',
  };

  const premiumCardTitleStyle = {
    color: 'var(--text-main)',
    fontSize: '11px',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.5px'
  };

  const premiumCardBodyStyle = {
    padding: '12px 16px',
    display: 'flex',
    flexDirection: 'column' as const,
    flex: 1,
  };

  const activeTabStyle = (tab: typeof activeTab) => ({
    background: 'transparent',
    border: 'none',
    borderBottom: activeTab === tab ? `2px solid ${colorWin}` : '2px solid transparent',
    color: activeTab === tab ? '#f3f4f6' : '#9ca3af',
    padding: '8px 16px',
    fontSize: '11px',
    fontWeight: 600,
    cursor: 'pointer',
    outline: 'none',
    transition: 'color 0.15s, border-color 0.15s',
  });

  return (
    <div className="workspace workspace-review" style={{ display: 'flex', flexDirection: 'column', gap: '16px', padding: '16px', height: 'calc(100vh - 36px)', overflow: 'hidden', backgroundColor: 'var(--bg-app)', fontFamily: "'Inter', -apple-system, sans-serif" }}>
      
      {/* Top Filter and Controls Bar */}
      <section style={{ flexShrink: 0, ...premiumCardStyle, padding: '12px 16px', flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
        
        <div style={{ display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '10px', color: '#9ca3af', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px' }}>Date Range:</span>
          <select
            value={dateRangeType}
            onChange={(e) => setDateRangeType(e.target.value)}
            style={{ background: 'var(--bg-app)', border: '1px solid #1c2230', borderRadius: '6px', color: '#f3f4f6', fontSize: '11px', padding: '6px 12px', cursor: 'pointer', outline: 'none' }}
          >
            <option value="today">Today</option>
            <option value="yesterday">Yesterday</option>
            <option value="this_week">This Week</option>
            <option value="this_month">This Month</option>
            <option value="last_30_days">Last 30 Days</option>
            <option value="all_time">All Time</option>
            <option value="single_date">Single Date</option>
            <option value="custom">Custom Range</option>
          </select>

          {dateRangeType === 'single_date' && (
            <select
              value={selectedDate}
              onChange={(e) => setSelectedDate(e.target.value)}
              style={{ background: 'var(--bg-app)', border: '1px solid #1c2230', borderRadius: '6px', color: '#f3f4f6', fontSize: '11px', padding: '6px 12px', cursor: 'pointer', outline: 'none' }}
            >
              {availableDates.map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
          )}

          {dateRangeType === 'custom' && (
            <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
              <input
                type="date"
                value={customStartDate}
                onChange={(e) => setCustomStartDate(e.target.value)}
                style={{ background: 'var(--bg-app)', border: '1px solid #1c2230', borderRadius: '6px', color: '#f3f4f6', fontSize: '11px', padding: '5px 12px', outline: 'none', colorScheme: 'dark' }}
              />
              <span style={{ fontSize: '10px', color: '#9ca3af' }}>to</span>
              <input
                type="date"
                value={customEndDate}
                onChange={(e) => setCustomEndDate(e.target.value)}
                style={{ background: 'var(--bg-app)', border: '1px solid #1c2230', borderRadius: '6px', color: '#f3f4f6', fontSize: '11px', padding: '5px 12px', outline: 'none', colorScheme: 'dark' }}
              />
            </div>
          )}

          <span style={{ fontSize: '10px', color: '#9ca3af', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', marginLeft: '8px' }}>Node:</span>
          <select
            value={selectedInstance}
            onChange={(e) => setSelectedInstance(e.target.value)}
            style={{ background: 'var(--bg-app)', border: '1px solid #1c2230', borderRadius: '6px', color: '#f3f4f6', fontSize: '11px', padding: '6px 12px', cursor: 'pointer', outline: 'none' }}
          >
            <option value="all">All Channels</option>
            {storeInstances.map((inst) => (
              <option key={inst.id} value={inst.id}>{inst.name}</option>
            ))}
          </select>
        </div>
        
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          {syncResult && <span style={{ fontSize: '10px', color: '#9ca3af', fontFamily: 'monospace' }}>{syncResult}</span>}
          <button
            className="btn-toolbar"
            style={{ borderColor: colorWin, color: colorWin, borderRadius: '6px', padding: '6px 16px', fontSize: '11px', fontWeight: 600 }}
            onClick={handleSyncLogs}
            disabled={isSyncing}
          >
            {isSyncing ? 'Syncing...' : 'Sync Logs'}
          </button>
        </div>

      </section>

      {/* Horizontal navigation tabs bar (Tradervue style) */}
      <div style={{ display: 'flex', borderBottom: '1px solid #1c2230', margin: '4px 0', gap: '16px', flexShrink: 0 }}>
        <button onClick={() => setActiveTab('overview')} style={activeTabStyle('overview')}>Overview</button>
        <button onClick={() => setActiveTab('detailed')} style={activeTabStyle('detailed')}>Detailed Stats</button>
        <button onClick={() => setActiveTab('breakdowns')} style={activeTabStyle('breakdowns')}>Win vs Loss / Session</button>
        <button onClick={() => setActiveTab('ledger')} style={activeTabStyle('ledger')}>Trades Ledger</button>
      </div>

      {/* Main Tab Content Panel */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflowY: 'auto', gap: '16px', padding: '4px 0' }}>
        
        {isLoadingPerf ? (
          <div style={{ display: 'flex', flex: 1, alignItems: 'center', justifyContent: 'center', color: '#9ca3af', fontSize: '12px', fontFamily: 'monospace' }}>
            Querying database logs...
          </div>
        ) : validTrades.length === 0 ? (
          <div style={{ display: 'flex', flex: 1, alignItems: 'center', justifyContent: 'center', color: '#9ca3af', fontSize: '12px', fontFamily: 'monospace' }}>
            No database entries match the selected filters.
          </div>
        ) : (
          <>
            {/* TAB 1: OVERVIEW */}
            {activeTab === 'overview' && (
              <>
                {/* Health Card View */}
                <div style={{ display: 'flex', gap: '16px' }}>
                  <div style={{ padding: 0, margin: 0, width: '220px', flexShrink: 0, background: 'var(--bg-panel)', border: '1px solid var(--border-color)', display: 'flex', flexDirection: 'column', borderRadius: '8px', overflow: 'hidden' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 8px', borderBottom: '1px solid var(--border-color)', background: 'var(--bg-toolbar)', fontWeight: 'bold' }}>
                      <div style={{ display: 'flex', alignItems: 'center' }}>
                        <strong style={{ color: 'var(--text-main)', fontSize: '11px' }}>{healthName}</strong>
                      </div>
                    </div>
                    <div style={{ padding: '6px 8px', display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '10px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ color: 'var(--text-muted)' }}>Balance</span>
                        <strong style={{ color: 'var(--text-main)' }}>${healthBalance.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ color: 'var(--text-muted)' }}>Equity</span>
                        <strong style={{ color: 'var(--text-main)' }}>${healthEquity.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ color: 'var(--text-muted)' }}>Trades</span>
                        <strong style={{ color: 'var(--text-main)' }}>{healthTrades}</strong>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ color: 'var(--text-muted)' }}>P&L</span>
                        <strong style={{ color: healthPnlColor }}>{healthPnlText}</strong>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '4px', paddingTop: '4px', borderTop: '1px solid var(--border-color)' }}>
                        <span style={{ color: 'var(--text-muted)' }}>Realized (Filtered)</span>
                        <strong style={{ color: healthRealizedColor }}>{healthRealizedText}</strong>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Tradervue-Style Weekly Strip Calendar View */}
                <div style={premiumCardStyle}>
                  <div style={premiumCardHeaderStyle}>
                    <strong style={premiumCardTitleStyle}>
                      {activeMonthYearStr}
                    </strong>
                    <div style={{ display: 'flex', border: '1px solid var(--border-color)', borderRadius: '6px', overflow: 'hidden' }}>
                      <button
                        onClick={shiftWeekPrev}
                        style={{ background: 'var(--bg-app)', border: 'none', color: '#9ca3af', padding: '6px 12px', fontSize: '11px', cursor: 'pointer', borderRight: '1px solid var(--border-color)' }}
                        title="Previous 7 Days"
                      >
                        &lt;
                      </button>
                      <button
                        onClick={shiftWeekToday}
                        style={{ background: 'var(--bg-app)', border: 'none', color: '#f3f4f6', padding: '6px 12px', fontSize: '11px', fontWeight: 600, cursor: 'pointer', borderRight: '1px solid var(--border-color)' }}
                      >
                        Today
                      </button>
                      <button
                        onClick={shiftWeekNext}
                        style={{ background: 'var(--bg-app)', border: 'none', color: '#9ca3af', padding: '6px 12px', fontSize: '11px', cursor: 'pointer' }}
                        title="Next 7 Days"
                      >
                        &gt;
                      </button>
                    </div>
                  </div>
                  
                  <div style={{ ...premiumCardBodyStyle, gap: '10px' }}>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: '10px' }}>
                    {dailyStripCards.map((card) => {
                      const hasProfit = card.profit >= 0;
                      const cardBg = card.active ? 'linear-gradient(145deg, #111625 0%, #171e33 100%)' : '#0e111a';
                      const cardBorder = card.active ? (hasProfit ? `1px solid ${colorWin}` : `1px solid ${colorLoss}`) : '1px solid #1c2230';
                      const profitText = card.active ? (hasProfit ? `+$${card.profit.toFixed(0)}` : `-$${Math.abs(card.profit).toFixed(0)}`) : '$0';
                      const textColor = card.active ? (hasProfit ? colorWin : colorLoss) : '#9ca3af';

                      return (
                        <div
                          key={card.dateStr}
                          style={{
                            background: cardBg,
                            border: cardBorder,
                            borderRadius: '10px',
                            padding: '12px',
                            minHeight: '100px',
                            display: 'flex',
                            flexDirection: 'column',
                            justifyContent: 'space-between',
                            boxShadow: card.active ? '0 4px 12px rgba(0,0,0,0.2)' : 'none'
                          }}
                        >
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <div style={{ display: 'flex', alignItems: 'baseline', gap: '4px' }}>
                              <span style={{ fontSize: '20px', fontWeight: 700, color: '#f3f4f6', lineHeight: 1 }}>{card.dayNum}</span>
                              <span style={{ fontSize: '10px', color: '#9ca3af', fontWeight: 500 }}>{card.dayName}</span>
                            </div>
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke={card.active ? '#9ca3af' : '#4b5563'} strokeWidth="2">
                              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                              <polyline points="14 2 14 8 20 8"/>
                            </svg>
                          </div>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', marginTop: '16px' }}>
                            <span style={{ fontSize: '13px', fontWeight: 700, color: textColor }}>{profitText}</span>
                            <span style={{ fontSize: '10px', color: '#9ca3af' }}>{card.tradesCount} trades</span>
                          </div>
                        </div>
                      );
                    })}
                    </div>
                  </div>
                </div>
                {/* Overview Charts Row */}
                <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '12px', minHeight: '400px' }}>
                  {/* Cumulative P&L Area Curve Card */}
                  <div style={premiumCardStyle}>
                    <div style={premiumCardHeaderStyle}>
                      <strong style={premiumCardTitleStyle}>Cumulative realized Net P&L Curve ($)</strong>
                    </div>
                    <div style={{ ...premiumCardBodyStyle, position: 'relative', minHeight: 0 }}>
                      <Line options={lineChartOptions} data={lineChartData} />
                    </div>
                  </div>

                  {/* Drawdown Analysis Card */}
                  <div style={premiumCardStyle}>
                    <div style={premiumCardHeaderStyle}>
                      <strong style={premiumCardTitleStyle}>Closed Drawdown Window ($)</strong>
                    </div>
                    <div style={{ ...premiumCardBodyStyle, position: 'relative', minHeight: 0 }}>
                      <Bar options={dailyBarChartOptions} data={ddChartData} />
                    </div>
                  </div>
                </div>
              </>
            )}

            {/* TAB 2: DETAILED STATS */}
            {activeTab === 'detailed' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '10px' }}>
                  
                  {/* Card 1: Net P&L */}
                  <div style={premiumCardStyle}>
                    <div style={premiumCardHeaderStyle}>
                      <strong style={premiumCardTitleStyle}>Net P&L</strong>
                    </div>
                    <div style={{ ...premiumCardBodyStyle, justifyContent: 'space-between', minHeight: '80px' }}>
                      <div style={{ color: totalNetProfit >= 0 ? colorWin : colorLoss, fontSize: '20px', fontWeight: 700, margin: '4px 0' }}>
                        {totalNetProfit >= 0 ? '+' : ''}${totalNetProfit.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </div>
                      <span style={{ fontSize: '10px', color: '#9ca3af' }}>
                        <span style={{ background: 'rgba(255,255,255,0.05)', padding: '2px 6px', borderRadius: '4px', border: '1px solid var(--border-color)' }}>
                          <strong>{totalTrades}</strong> Trades
                        </span>
                      </span>
                    </div>
                  </div>

                  {/* Card 2: Win Rate */}
                  <div style={premiumCardStyle}>
                    <div style={premiumCardHeaderStyle}>
                      <strong style={premiumCardTitleStyle}>Win Rate</strong>
                    </div>
                    <div style={{ ...premiumCardBodyStyle, justifyContent: 'space-between', alignItems: 'center', minHeight: '80px', flexDirection: 'row' }}>
                      <div style={{ display: 'flex', flexDirection: 'column', flex: 1 }}>
                        <div style={{ fontSize: '20px', fontWeight: 700, margin: '4px 0', color: '#f3f4f6' }}>
                          {winRate.toFixed(1)}%
                        </div>
                        <span style={{ fontSize: '9px', color: '#9ca3af' }}>{winningTrades} wins of {totalTrades}</span>
                      </div>
                      <div style={{ position: 'relative', display: 'flex', alignItems: 'center', justifyContent: 'center', width: '48px', height: '48px' }}>
                        <svg width="48" height="48" style={{ transform: 'rotate(-90deg)', filter: 'drop-shadow(0 0 2px rgba(16, 185, 129, 0.15))' }}>
                          <circle cx="24" cy="24" r={18} fill="transparent" stroke="var(--border-color)" strokeWidth="4" />
                          <circle cx="24" cy="24" r={18} fill="transparent" stroke={colorWin} strokeWidth="4"
                                  strokeDasharray={circumference} strokeDashoffset={strokeDashoffset} strokeLinecap="round" />
                        </svg>
                        <span style={{ position: 'absolute', fontSize: '9px', fontWeight: 700, color: '#9ca3af' }}>W%</span>
                      </div>
                    </div>
                  </div>

                  {/* Card 3: Profit Factor */}
                  <div style={premiumCardStyle}>
                    <div style={premiumCardHeaderStyle}>
                      <strong style={premiumCardTitleStyle}>Profit Factor</strong>
                    </div>
                    <div style={{ ...premiumCardBodyStyle, justifyContent: 'space-between', minHeight: '80px' }}>
                      <div style={{ display: 'flex', flexDirection: 'column', width: '100%' }}>
                        <span style={{ fontSize: '20px', fontWeight: 700, color: profitFactor >= 1.5 ? colorWin : profitFactor >= 1 ? '#60a5fa' : colorLoss }}>
                          {profitFactor.toFixed(2)}
                        </span>
                        <div style={{ width: '100%', height: '6px', background: 'var(--border-color)', borderRadius: '3px', overflow: 'hidden', marginTop: '6px' }}>
                          <div style={{ width: `${pfPercentage}%`, height: '100%', background: profitFactor >= 1.5 ? colorWin : profitFactor >= 1 ? '#60a5fa' : colorLoss }} />
                        </div>
                      </div>
                      <span style={{ fontSize: '8px', color: '#9ca3af' }}>
                        {profitFactor >= 1.5 ? 'Healthy (>1.5)' : profitFactor >= 1.0 ? 'Breakeven' : 'Unprofitable'}
                      </span>
                    </div>
                  </div>

                  {/* Card 4: Expectancy */}
                  <div style={premiumCardStyle}>
                    <div style={premiumCardHeaderStyle}>
                      <strong style={premiumCardTitleStyle}>Expectancy</strong>
                    </div>
                    <div style={{ ...premiumCardBodyStyle, justifyContent: 'space-between', minHeight: '80px' }}>
                      <div style={{ color: tradeExpectancy >= 0 ? colorWin : colorLoss, fontSize: '20px', fontWeight: 700, margin: '4px 0' }}>
                        {tradeExpectancy >= 0 ? '+' : ''}${tradeExpectancy.toFixed(2)}
                      </div>
                      <span style={{ fontSize: '9px', color: '#9ca3af' }}>expected profit / trade</span>
                    </div>
                  </div>

                  {/* Card 5: Avg Win vs Loss Ratio */}
                  <div style={premiumCardStyle}>
                    <div style={premiumCardHeaderStyle}>
                      <strong style={premiumCardTitleStyle}>Avg Win vs Loss</strong>
                    </div>
                    <div style={{ ...premiumCardBodyStyle, justifyContent: 'space-between', minHeight: '80px' }}>
                      <div style={{ display: 'flex', flexDirection: 'column', width: '100%' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '9px', color: '#9ca3af', fontWeight: 600 }}>
                          <span>W: <span style={{ color: colorWin }}>+${avgWin.toFixed(0)}</span></span>
                          <span>L: <span style={{ color: colorLoss }}>-${Math.abs(avgLoss).toFixed(0)}</span></span>
                        </div>
                        <div style={{ display: 'flex', height: '6px', borderRadius: '3px', overflow: 'hidden', marginTop: '6px', background: 'var(--border-color)' }}>
                          {avgWin > 0 && <div style={{ width: `${winRatio * 100}%`, background: colorWin, height: '100%' }} />}
                          {Math.abs(avgLoss) > 0 && <div style={{ width: `${(1 - winRatio) * 100}%`, background: colorLoss, height: '100%' }} />}
                        </div>
                      </div>
                      <span style={{ fontSize: '8px', color: '#9ca3af', textAlign: 'right' }}>
                        Ratio: <strong>{winLossRatio.toFixed(2)}</strong>
                      </span>
                    </div>
                  </div>

                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                  
                  {/* Detailed profile table card */}
                  <div style={premiumCardStyle}>
                    <div style={premiumCardHeaderStyle}>
                      <strong style={premiumCardTitleStyle}>Trade Outcomes Details</strong>
                    </div>
                    <div style={{ ...premiumCardBodyStyle, gap: '6px', fontSize: '11px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-color)', paddingBottom: '4px' }}>
                        <span style={{ color: 'var(--text-muted)' }}>Winning Trades:</span>
                        <span style={{ color: colorWin, fontWeight: 700 }}>{winningTrades} ({winsPct.toFixed(1)}%)</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-color)', paddingBottom: '4px' }}>
                        <span style={{ color: 'var(--text-muted)' }}>Losing Trades:</span>
                        <span style={{ color: colorLoss, fontWeight: 700 }}>{losingTrades} ({lossesPct.toFixed(1)}%)</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-color)', paddingBottom: '4px' }}>
                        <span style={{ color: 'var(--text-muted)' }}>Breakeven Trades:</span>
                        <span style={{ color: 'var(--text-main)' }}>{breakevenTrades} ({bePct.toFixed(1)}%)</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-color)', paddingBottom: '4px' }}>
                        <span style={{ color: 'var(--text-muted)' }}>Long trades (BUY):</span>
                        <span style={{ color: 'var(--text-main)' }}>{buyTradesCount} ({buyPct.toFixed(1)}%) <span style={{ color: 'var(--text-muted)' }}>(wins: {buyWinsCount}, {buyWinRate.toFixed(0)}% W)</span></span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-color)', paddingBottom: '4px' }}>
                        <span style={{ color: 'var(--text-muted)' }}>Short trades (SELL):</span>
                        <span style={{ color: 'var(--text-main)' }}>{sellTradesCount} ({sellPct.toFixed(1)}%) <span style={{ color: 'var(--text-muted)' }}>(wins: {sellWinsCount}, {sellWinRate.toFixed(0)}% W)</span></span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-color)', paddingBottom: '4px' }}>
                        <span style={{ color: 'var(--text-muted)' }}>Long realised P&L:</span>
                        <span style={{ color: buyNetProfit >= 0 ? colorWin : colorLoss, fontFamily: 'monospace', fontWeight: 'bold' }}>
                          {buyNetProfit >= 0 ? '+' : ''}${buyNetProfit.toFixed(2)}
                        </span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-color)', paddingBottom: '4px' }}>
                        <span style={{ color: 'var(--text-muted)' }}>Short realised P&L:</span>
                        <span style={{ color: sellNetProfit >= 0 ? colorWin : colorLoss, fontFamily: 'monospace', fontWeight: 'bold' }}>
                          {sellNetProfit >= 0 ? '+' : ''}${sellNetProfit.toFixed(2)}
                        </span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-color)', paddingBottom: '4px' }}>
                        <span style={{ color: 'var(--text-muted)' }}>Total Volume (Lots):</span>
                        <span style={{ color: 'var(--text-main)', fontFamily: 'monospace', fontWeight: 'bold' }}>{totalVolume.toFixed(2)}</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-color)', paddingBottom: '4px' }}>
                        <span style={{ color: 'var(--text-muted)' }}>Average Volume:</span>
                        <span style={{ color: 'var(--text-main)', fontFamily: 'monospace', fontWeight: 'bold' }}>{avgVolume.toFixed(2)}</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span style={{ color: 'var(--text-muted)' }}>Total Swap & Comm:</span>
                        <span style={{ color: totalFees <= 0 ? colorWin : colorLoss, fontFamily: 'monospace', fontWeight: 'bold' }}>
                          {totalFees >= 0 ? '+' : ''}${totalFees.toFixed(2)}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Profile and duration card */}
                  <div style={premiumCardStyle}>
                    <div style={premiumCardHeaderStyle}>
                      <strong style={premiumCardTitleStyle}>Hold Duration & Streak Profile</strong>
                    </div>
                    <div style={{ ...premiumCardBodyStyle, gap: '6px', fontSize: '11px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-color)', paddingBottom: '4px' }}>
                        <span style={{ color: 'var(--text-muted)' }}>Average Hold Time:</span>
                        <span style={{ color: 'var(--text-main)' }}>{avgHoldTimeStr}</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-color)', paddingBottom: '4px' }}>
                        <span style={{ color: 'var(--text-muted)' }}>Average Win Hold Time:</span>
                        <span style={{ color: 'var(--text-main)' }}>{avgWinHoldTimeStr}</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-color)', paddingBottom: '4px' }}>
                        <span style={{ color: 'var(--text-muted)' }}>Average Loss Hold Time:</span>
                        <span style={{ color: 'var(--text-main)' }}>{avgLossHoldTimeStr}</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-color)', paddingBottom: '4px' }}>
                        <span style={{ color: 'var(--text-muted)' }}>Longest Winning Streak:</span>
                        <span style={{ color: colorWin, fontWeight: 700 }}>{maxWinStreak} trades</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-color)', paddingBottom: '4px' }}>
                        <span style={{ color: 'var(--text-muted)' }}>Longest Losing Streak:</span>
                        <span style={{ color: colorLoss, fontWeight: 700 }}>{maxLossStreak} trades</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-color)', paddingBottom: '4px' }}>
                        <span style={{ color: 'var(--text-muted)' }}>Best Win Trade:</span>
                        <span style={{ color: colorWin, fontWeight: 700 }}>+${bestTrade.toFixed(2)}</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span style={{ color: 'var(--text-muted)' }}>Worst Loss Trade:</span>
                        <span style={{ color: colorLoss, fontWeight: 700 }}>-${Math.abs(worstTrade).toFixed(2)}</span>
                      </div>
                    </div>
                  </div>

                </div>
              </div>
            )}

            {/* TAB 3: WIN VS LOSS / SESSION BREAKDOWNS */}
            {activeTab === 'breakdowns' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                
                {/* Realized Daily P&L and Symbol performance chart */}
                <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '12px', height: '240px', flexShrink: 0 }}>
                  <div style={premiumCardStyle}>
                    <div style={premiumCardHeaderStyle}>
                      <strong style={premiumCardTitleStyle}>Realized Daily Net P&L ($)</strong>
                    </div>
                    <div style={{ ...premiumCardBodyStyle, position: 'relative', minHeight: 0 }}>
                      <Bar options={dailyBarChartOptions} data={dailyPnlChartData} />
                    </div>
                  </div>
                  <div style={premiumCardStyle}>
                    <div style={premiumCardHeaderStyle}>
                      <strong style={premiumCardTitleStyle}>Symbol Realized Profit Breakdown ($)</strong>
                    </div>
                    <div style={{ ...premiumCardBodyStyle, position: 'relative', minHeight: 0 }}>
                      <Bar options={dailyBarChartOptions} data={symbolChartData} />
                    </div>
                  </div>
                </div>

                {/* Symbols Grid stats table and Day of Week bar chart */}
                <div style={{ display: 'grid', gridTemplateColumns: '1.1fr 1fr', gap: '12px', height: '220px', flexShrink: 0 }}>
                  
                  <div style={premiumCardStyle}>
                    <div style={premiumCardHeaderStyle}>
                      <strong style={premiumCardTitleStyle}>Symbol Statistics List</strong>
                    </div>
                    <div className="table-container" style={{ ...premiumCardBodyStyle, padding: 0, overflowY: 'auto' }}>
                      <table className="data-grid" style={{ width: '100%' }}>
                        <thead>
                          <tr>
                            <th>Symbol</th>
                            <th style={{ textAlign: 'right' }}>Trades</th>
                            <th style={{ textAlign: 'right' }}>Win %</th>
                            <th style={{ textAlign: 'right' }}>Lots</th>
                            <th style={{ textAlign: 'right' }}>Net Profit</th>
                          </tr>
                        </thead>
                        <tbody>
                          {symbolList.map((s) => {
                            const pColor = s.netProfit >= 0 ? colorWin : colorLoss;
                            return (
                              <tr key={s.symbol}>
                                <td><strong>{s.symbol}</strong></td>
                                <td style={{ textAlign: 'right', fontFamily: 'monospace' }}>{s.tradesCount}</td>
                                <td style={{ textAlign: 'right', fontFamily: 'monospace' }}>{s.winRate.toFixed(1)}%</td>
                                <td style={{ textAlign: 'right', fontFamily: 'monospace' }}>{s.volume.toFixed(2)}</td>
                                <td style={{ textAlign: 'right', color: pColor, fontWeight: 'bold', fontFamily: 'monospace' }}>
                                  {s.netProfit >= 0 ? '+' : ''}${s.netProfit.toFixed(2)}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  <div style={premiumCardStyle}>
                    <div style={premiumCardHeaderStyle}>
                      <strong style={premiumCardTitleStyle}>Net realized P&L by Day of Week ($)</strong>
                    </div>
                    <div style={{ ...premiumCardBodyStyle, position: 'relative', minHeight: 0 }}>
                      <Bar options={dailyBarChartOptions} data={dayChartData} />
                    </div>
                  </div>

                </div>

                {/* Hourly session bar chart and Hold Time buckets */}
                <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '12px', height: '220px', flexShrink: 0 }}>
                  
                  <div style={premiumCardStyle}>
                    <div style={premiumCardHeaderStyle}>
                      <strong style={premiumCardTitleStyle}>Hourly Session Performance Breakdown</strong>
                    </div>
                    <div style={{ ...premiumCardBodyStyle, position: 'relative', minHeight: 0 }}>
                      <Bar options={dailyBarChartOptions} data={hourChartData} />
                    </div>
                  </div>

                  <div style={premiumCardStyle}>
                    <div style={premiumCardHeaderStyle}>
                      <strong style={premiumCardTitleStyle}>Hold Time Profiles</strong>
                    </div>
                    <div style={{ ...premiumCardBodyStyle, justifyContent: 'center', gap: '8px' }}>
                      <div style={{ display: 'flex', gap: '8px', background: 'rgba(255,255,255,0.02)', padding: '8px', borderRadius: '6px', borderLeft: `3px solid ${colorLong}` }}>
                        <div style={{ flex: 1 }}>
                          <div style={{ fontSize: '9px', color: '#9ca3af', fontWeight: 600 }}>SCALPS (&lt; 5 MINS)</div>
                          <div style={{ fontSize: '14px', fontWeight: 700, color: '#f3f4f6', marginTop: '2px' }}>{scalpCount} Trades</div>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', color: scalpProfit >= 0 ? colorWin : colorLoss, fontWeight: 700, fontSize: '11px', fontFamily: 'monospace' }}>
                          {scalpProfit >= 0 ? '+' : ''}${scalpProfit.toFixed(2)}
                        </div>
                      </div>

                      <div style={{ display: 'flex', gap: '8px', background: 'rgba(255,255,255,0.02)', padding: '8px', borderRadius: '6px', borderLeft: `3px solid ${colorShort}` }}>
                        <div style={{ flex: 1 }}>
                          <div style={{ fontSize: '9px', color: '#9ca3af', fontWeight: 600 }}>INTRADAY (5 MINS - 1 HOUR)</div>
                          <div style={{ fontSize: '14px', fontWeight: 700, color: '#f3f4f6', marginTop: '2px' }}>{intradayCount} Trades</div>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', color: intradayProfit >= 0 ? colorWin : colorLoss, fontWeight: 700, fontSize: '11px', fontFamily: 'monospace' }}>
                          {intradayProfit >= 0 ? '+' : ''}${intradayProfit.toFixed(2)}
                        </div>
                      </div>

                      <div style={{ display: 'flex', gap: '8px', background: 'rgba(255,255,255,0.02)', padding: '8px', borderRadius: '6px', borderLeft: '3px solid #9c27b0' }}>
                        <div style={{ flex: 1 }}>
                          <div style={{ fontSize: '9px', color: '#9ca3af', fontWeight: 600 }}>SWINGS (&gt; 1 HOUR)</div>
                          <div style={{ fontSize: '14px', fontWeight: 700, color: '#f3f4f6', marginTop: '2px' }}>{swingCount} Trades</div>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', color: swingProfit >= 0 ? colorWin : colorLoss, fontWeight: 700, fontSize: '11px', fontFamily: 'monospace' }}>
                          {swingProfit >= 0 ? '+' : ''}${swingProfit.toFixed(2)}
                        </div>
                      </div>
                    </div>
                  </div>

                </div>

              </div>
            )}



            {/* TAB 5: TRADES LEDGER */}
            {activeTab === 'ledger' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', flex: 1, minHeight: 0 }}>
                
                {/* Ledger Filters Row */}
                <div style={{ display: 'flex', gap: '10px', alignItems: 'center', background: 'var(--bg-toolbar)', border: '1px solid var(--border-color)', borderRadius: '8px', padding: '8px 16px', flexShrink: 0, justifyContent: 'space-between' }}>
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <span style={{ fontSize: '9px', color: '#9ca3af', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px' }}>SEARCH:</span>
                    <input
                      type="text"
                      placeholder="Type symbol..."
                      value={ledgerSearch}
                      onChange={(e) => { setLedgerSearch(e.target.value); setLedgerPage(1); }}
                      style={{ background: 'var(--bg-app)', border: '1px solid var(--border-color)', borderRadius: '6px', color: '#f3f4f6', fontSize: '11px', padding: '6px 12px', outline: 'none', width: '120px' }}
                    />

                    <span style={{ fontSize: '9px', color: '#9ca3af', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', marginLeft: '8px' }}>TYPE:</span>
                    <select
                      value={ledgerTypeFilter}
                      onChange={(e) => { setLedgerTypeFilter(e.target.value); setLedgerPage(1); }}
                      style={{ background: 'var(--bg-app)', border: '1px solid var(--border-color)', borderRadius: '6px', color: '#f3f4f6', fontSize: '11px', padding: '5px 10px', cursor: 'pointer', outline: 'none' }}
                    >
                      <option value="all">All</option>
                      <option value="BUY">BUY</option>
                      <option value="SELL">SELL</option>
                    </select>

                    <span style={{ fontSize: '9px', color: '#9ca3af', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', marginLeft: '8px' }}>OUTCOME:</span>
                    <select
                      value={ledgerOutcomeFilter}
                      onChange={(e) => { setLedgerOutcomeFilter(e.target.value); setLedgerPage(1); }}
                      style={{ background: 'var(--bg-app)', border: '1px solid var(--border-color)', borderRadius: '6px', color: '#f3f4f6', fontSize: '11px', padding: '5px 10px', cursor: 'pointer', outline: 'none' }}
                    >
                      <option value="all">All Outcomes</option>
                      <option value="wins">Wins Only</option>
                      <option value="losses">Losses Only</option>
                      <option value="breakeven">Breakeven Only</option>
                    </select>

                    <span style={{ fontSize: '9px', color: '#9ca3af', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', marginLeft: '8px' }}>PAGE SIZE:</span>
                    <select
                      value={ledgerPageSize}
                      onChange={(e) => { setLedgerPageSize(Number(e.target.value)); setLedgerPage(1); }}
                      style={{ background: 'var(--bg-app)', border: '1px solid var(--border-color)', borderRadius: '6px', color: '#f3f4f6', fontSize: '11px', padding: '5px 10px', cursor: 'pointer', outline: 'none' }}
                    >
                      <option value={10}>10</option>
                      <option value={20}>20</option>
                      <option value={50}>50</option>
                      <option value={100}>100</option>
                    </select>
                  </div>

                  {/* Pagination Indicator / Buttons */}
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center', fontSize: '10px' }}>
                    <span style={{ color: '#9ca3af' }}>
                      Showing {totalLedgerItems > 0 ? ledgerStartIndex + 1 : 0}–{Math.min(ledgerStartIndex + ledgerPageSize, totalLedgerItems)} of {totalLedgerItems}
                    </span>
                    <div style={{ display: 'flex', gap: '2px' }}>
                      <button
                        className="btn-toolbar"
                        style={{ padding: '4px 10px', borderRadius: '6px', fontSize: '10px', cursor: 'pointer' }}
                        onClick={() => setLedgerPage(p => Math.max(1, p - 1))}
                        disabled={ledgerPage === 1}
                      >
                        &lt; Prev
                      </button>
                      <span style={{ padding: '4px 8px', color: '#f3f4f6', fontFamily: 'monospace' }}>
                        {ledgerPage} / {totalLedgerPages}
                      </span>
                      <button
                        className="btn-toolbar"
                        style={{ padding: '4px 10px', borderRadius: '6px', fontSize: '10px', cursor: 'pointer' }}
                        onClick={() => setLedgerPage(p => Math.min(totalLedgerPages, p + 1))}
                        disabled={ledgerPage === totalLedgerPages}
                      >
                        Next &gt;
                      </button>
                    </div>
                  </div>
                </div>

                {/* Ledger Table Container */}
                <div style={{ ...premiumCardStyle, flex: 1, overflow: 'hidden', padding: 0 }}>
                  <div style={premiumCardHeaderStyle}>
                    <strong style={premiumCardTitleStyle}>Trades Ledger</strong>
                  </div>
                  <div className="table-container" style={{ ...premiumCardBodyStyle, padding: 0, overflowY: 'auto' }}>
                    <table className="data-grid" style={{ width: '100%' }}>
                    <thead>
                      <tr>
                        <th style={{ width: '70px', cursor: 'pointer' }} onClick={() => handleSort('ticket')}>
                          Ticket {ledgerSortField === 'ticket' ? (ledgerSortOrder === 'asc' ? '▲' : '▼') : ''}
                        </th>
                        <th style={{ width: '110px', cursor: 'pointer' }} onClick={() => handleSort('time')}>
                          Close Time {ledgerSortField === 'time' ? (ledgerSortOrder === 'asc' ? '▲' : '▼') : ''}
                        </th>
                        <th style={{ width: '80px' }}>Instance</th>
                        <th style={{ width: '70px', cursor: 'pointer' }} onClick={() => handleSort('symbol')}>
                          Symbol {ledgerSortField === 'symbol' ? (ledgerSortOrder === 'asc' ? '▲' : '▼') : ''}
                        </th>
                        <th style={{ width: '55px', cursor: 'pointer' }} onClick={() => handleSort('type')}>
                          Type {ledgerSortField === 'type' ? (ledgerSortOrder === 'asc' ? '▲' : '▼') : ''}
                        </th>
                        <th style={{ width: '55px', textAlign: 'right', cursor: 'pointer' }} onClick={() => handleSort('volume')}>
                          Volume {ledgerSortField === 'volume' ? (ledgerSortOrder === 'asc' ? '▲' : '▼') : ''}
                        </th>
                        <th style={{ width: '55px', textAlign: 'right' }}>Comm</th>
                        <th style={{ width: '55px', textAlign: 'right' }}>Swap</th>
                        <th style={{ width: '80px', textAlign: 'right', cursor: 'pointer' }} onClick={() => handleSort('profit')}>
                          Profit {ledgerSortField === 'profit' ? (ledgerSortOrder === 'asc' ? '▲' : '▼') : ''}
                        </th>
                        <th style={{ width: '75px', textAlign: 'right' }}>Hold Time</th>
                        <th>Comment</th>
                      </tr>
                    </thead>
                    <tbody>
                      {paginatedLedgerTrades.map((t) => {
                        const profitColor = t.profit >= 0 ? colorWin : colorLoss;
                        const dateObj = new Date((t.local_time || t.time) * 1000);
                        
                        const formattedTime = dateObj.toLocaleDateString('en-US', { month: '2-digit', day: '2-digit' }) + ' ' + 
                          dateObj.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
                        
                        const durationSec = (t.local_time || t.time) - t.local_start_time;
                        const holdStr = (t.local_start_time && durationSec > 0) ? formatDuration(durationSec) : '--';
                        
                        return (
                          <tr key={t.id}>
                            <td style={{ fontFamily: 'monospace', color: '#9ca3af' }}>#{t.ticket}</td>
                            <td style={{ fontFamily: 'monospace' }}>{formattedTime}</td>
                            <td style={{ fontWeight: 'bold' }}>{t.instance_name}</td>
                            <td><strong>{t.symbol}</strong></td>
                            <td>
                              <span className={`badge-dense ${t.type === 'BUY' ? 'bdg-buy' : t.type === 'SELL' ? 'bdg-sell' : 'bdg-active'}`}>
                                {t.type}
                              </span>
                            </td>
                            <td style={{ textAlign: 'right', fontFamily: 'monospace' }}>{t.volume.toFixed(2)}</td>
                            <td style={{ textAlign: 'right', fontFamily: 'monospace', color: '#9ca3af' }}>${t.commission.toFixed(2)}</td>
                            <td style={{ textAlign: 'right', fontFamily: 'monospace', color: '#9ca3af' }}>${t.swap.toFixed(2)}</td>
                            <td style={{ textAlign: 'right', color: profitColor, fontWeight: 'bold', fontFamily: 'monospace' }}>
                              {t.profit >= 0 ? '+' : ''}${t.profit.toFixed(2)}
                            </td>
                            <td style={{ textAlign: 'right', fontFamily: 'monospace', fontSize: '9px', color: '#9ca3af' }}>{holdStr}</td>
                            <td style={{ color: '#9ca3af', fontStyle: 'italic', fontSize: '9px' }}>{t.comment || '--'}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                    </table>
                  </div>
                </div>

              </div>
            )}
          </>
        )}

      </div>

    </div>
  );
};

const daysOfWeek = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

export default Review;
