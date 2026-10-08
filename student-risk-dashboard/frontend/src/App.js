import React, { useState, useEffect } from 'react';
import { Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom';
import { getCurrentUser } from 'aws-amplify/auth';
import LoginPage from './pages/LoginPage';
import Dashboard from './pages/Dashboard';
import StudentDetail from './pages/StudentDetail';

function ProtectedRoute({ children }) {
  const [authState, setAuthState] = useState('loading'); // 'loading' | 'authed' | 'unauthed'
  const location = useLocation();

  useEffect(() => {
    let cancelled = false;
    getCurrentUser()
      .then(() => { if (!cancelled) setAuthState('authed'); })
      .catch(() => { if (!cancelled) setAuthState('unauthed'); });
    return () => { cancelled = true; };
  }, []);

  if (authState === 'loading') {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        height: '100vh', background: 'var(--bg)'
      }}>
        <div className="spinner" style={{
          width: 40, height: 40, border: '4px solid #e2e8f0',
          borderTopColor: 'var(--primary)', borderRadius: '50%',
          animation: 'spin 0.8s linear infinite'
        }} />
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }

  if (authState === 'unauthed') {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <Dashboard />
          </ProtectedRoute>
        }
      />
      <Route
        path="/students/:id"
        element={
          <ProtectedRoute>
            <StudentDetail />
          </ProtectedRoute>
        }
      />
      {/* Catch-all redirect */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
