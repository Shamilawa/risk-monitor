import { useEffect, useState } from 'react';
import { NavLink } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useStore } from '../store/useStore';
import type { NewsToday } from '../types';
import { findActiveWindow } from '../utils/news';

const fetchNewsToday = async (): Promise<NewsToday> => {
  const res = await fetch('/api/news/today');
  return res.json();
};

const Header = () => {
  const mt5Status = useStore((state) => state.mt5Status);
  const instances = useStore((state) => state.instances || []);
  const [currentDate, setCurrentDate] = useState('');

  const { data: newsToday } = useQuery<NewsToday>({
    queryKey: ['news', 'today'],
    queryFn: fetchNewsToday,
    refetchInterval: 30000,
  });
  const newsFailed = newsToday?.status === 'FAILED';
  const activeBlackout = newsToday ? findActiveWindow(newsToday.events) : undefined;

  useEffect(() => {
    const updateDate = () => {
      const options: Intl.DateTimeFormatOptions = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' };
      setCurrentDate(new Date().toLocaleDateString('en-US', options).toUpperCase());
    };
    updateDate();
    const interval = setInterval(updateDate, 60000);
    return () => clearInterval(interval);
  }, []);

  // Compute aggregate stats
  const totalBal = instances.reduce((acc, inst) => acc + (inst.balance || 0), 0);
  const totalEq = instances.reduce((acc, inst) => acc + (inst.equity || 0), 0);
  const combinedPnl = totalEq - totalBal;
  const activeTrades = instances.reduce((acc, inst) => acc + (inst.positions ? inst.positions.length : 0), 0);

  const formattedBal = totalBal.toLocaleString('en-US', { style: 'currency', currency: 'USD' });
  const formattedEq = totalEq.toLocaleString('en-US', { style: 'currency', currency: 'USD' });
  const formattedPnl = (combinedPnl >= 0 ? '+' : '') + combinedPnl.toLocaleString('en-US', { style: 'currency', currency: 'USD' });
  const pnlColor = combinedPnl > 0 ? 'var(--color-buy)' : combinedPnl < 0 ? 'var(--color-sell)' : 'var(--text-main)';

  return (
    <header className="terminal-header" style={{ height: '36px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'var(--bg-toolbar)', borderBottom: '1px solid var(--border-dark)', padding: '0 12px' }}>
      <div className="th-left" style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        <div className="th-brand" style={{ display: 'flex', alignItems: 'center', gap: '6px', borderRight: '1px solid var(--border-color)', paddingRight: '12px' }}>
          <strong style={{ fontSize: '11px', letterSpacing: '0.5px' }}>PREMIUM BRIDGE</strong>
        </div>
        <div className="th-nav" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          <div className="th-tabs" style={{ display: 'flex', height: '100%', alignItems: 'center' }}>
            <NavLink to="/" className={({ isActive }) => `th-tab ${isActive ? 'active' : ''}`}>
              Dashboard
            </NavLink>
            <NavLink to="/copier" className={({ isActive }) => `th-tab ${isActive ? 'active' : ''}`}>
              Trade Copier
            </NavLink>
            <NavLink to="/review" className={({ isActive }) => `th-tab ${isActive ? 'active' : ''}`}>
              Review Mode
            </NavLink>
          </div>
          <div className="th-divider"></div>
          <button id="btn-settings" className="th-btn-ghost">⚙ Settings</button>
        </div>
      </div>

      <div className="th-center" style={{ display: 'flex', alignItems: 'center' }}>
        <div className="th-ticker" style={{ display: 'flex', alignItems: 'center', gap: '12px', fontSize: '9px' }}>
          <div className="ticker-item" style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
            <span className="t-label">DATE</span>
            <span className="t-value" style={{ color: 'var(--text-muted)' }}>{currentDate || '--'}</span>
          </div>
          <div className="ticker-divider" style={{ width: '1px', height: '12px', background: 'var(--border-color)' }}></div>
          <div className="ticker-item" style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
            <span className="t-label">TOTAL BAL</span>
            <span className="t-value highlight" style={{ color: 'var(--text-main)', fontWeight: 'bold' }}>{formattedBal}</span>
          </div>
          <div className="ticker-item" style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
            <span className="t-label">TOTAL EQ</span>
            <span className="t-value highlight" style={{ color: 'var(--text-main)', fontWeight: 'bold' }}>{formattedEq}</span>
          </div>
          <div className="ticker-item" style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
            <span className="t-label">COMBINED P&L</span>
            <span className="t-value" style={{ color: pnlColor, fontWeight: 'bold' }}>{formattedPnl}</span>
          </div>
          <div className="ticker-divider" style={{ width: '1px', height: '12px', background: 'var(--border-color)' }}></div>
          <div className="ticker-item" style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
            <span className="t-label">ACTIVE TRADES</span>
            <span className="t-value" style={{ color: 'var(--text-main)', fontWeight: 'bold' }}>{activeTrades}</span>
          </div>
        </div>
      </div>

      <div className="th-right" style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        {(newsFailed || activeBlackout) && (
          <div className="th-status-box" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <div className="led-indicator">
              <span className="led offline" style={{ background: newsFailed ? '#e74c3c' : '#f39c12' }}></span>
            </div>
            <span className="status-text" style={{ color: newsFailed ? '#e74c3c' : '#f39c12', fontWeight: 'bold' }}>
              {newsFailed ? 'NEWS FEED DOWN' : `BLACKOUT: ${activeBlackout?.currency} ${activeBlackout?.title}`}
            </span>
          </div>
        )}
        <div className="th-status-box" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <div className="led-indicator">
            <span className={`led ${mt5Status.online ? 'online' : 'offline'}`}></span>
          </div>
          <span className="status-text">{mt5Status.text}</span>
        </div>
      </div>
    </header>
  );
};

export default Header;

