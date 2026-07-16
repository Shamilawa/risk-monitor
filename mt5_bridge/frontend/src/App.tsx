import { useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, useNavigate } from 'react-router-dom';
import Dashboard from './components/Dashboard';
import Copier from './components/Copier';
import Settings from './components/Settings';
import PortfolioManagement from './components/PortfolioManagement';
import { CommandBar } from './components/shell/CommandBar';
import { Sidebar } from './components/shell/Sidebar';
import { StatusLine } from './components/shell/StatusLine';
import { NAV_ENTRIES } from './components/shell/nav';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useSocket } from './hooks/useSocket';
import './index.css';

const queryClient = new QueryClient();

/** F-keys jump between top-level modules, terminal-style. */
function FKeyNav() {
  const navigate = useNavigate();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const entry = NAV_ENTRIES.find((n) => n.fkey === e.key);
      if (entry) {
        e.preventDefault();
        navigate(entry.href);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [navigate]);
  return null;
}

function Shell() {
  useSocket();
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden' }}>
      <CommandBar />
      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
        <Sidebar />
        <main
          style={{
            flex: 1,
            minWidth: 0,
            overflow: 'hidden',
            background: 'var(--bg-app)',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/copier" element={<Copier />} />
            <Route path="/portfolio" element={<PortfolioManagement />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
      <StatusLine />
      <FKeyNav />
    </div>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Router>
        <Shell />
      </Router>
    </QueryClientProvider>
  );
}

export default App;
