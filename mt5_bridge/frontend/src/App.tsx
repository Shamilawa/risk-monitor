import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import Header from './components/Header';
import Dashboard from './components/Dashboard';
import Copier from './components/Copier';
import Review from './components/Review';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useSocket } from './hooks/useSocket';
import './index.css';

const queryClient = new QueryClient();

function App() {
  useSocket();

  return (
    <QueryClientProvider client={queryClient}>
      <Router>
        <div className="app-container" style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
        <Header />
        <main className="main-content" style={{ flex: 1 }}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/copier" element={<Copier />} />
            <Route path="/review" element={<Review />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </main>
        </div>
      </Router>
    </QueryClientProvider>
  );
}

export default App;
