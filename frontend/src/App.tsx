import { useState, useEffect } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import HomePage from "./pages/HomePage";
import DashboardPage from "./pages/DashboardPage";
import DocumentationPage from "./pages/DocumentationPage";
import CICDPage from "./pages/CICDPage";
import HistoryPage from "./pages/HistoryPage";
import LoginScreen from "./components/LoginScreen";
import { getCurrentUser, setOnUnauthorizedCallback } from "./api";
import type { User } from "./types";
import "./index.css";

function ProtectedRoute({ user, loading, children }: { user: User | null; loading: boolean; children: React.ReactNode }) {
  if (loading) {
    return <div className="h-screen w-screen bg-[#1e1e1e] flex items-center justify-center text-white">Loading...</div>;
  }
  if (!user) {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [authLoading, setAuthLoading] = useState(true);

  useEffect(() => {
    setOnUnauthorizedCallback(() => {
      setUser(null);
    });

    getCurrentUser()
      .then((currentUser) => setUser(currentUser))
      .catch(() => setUser(null))
      .finally(() => setAuthLoading(false));
  }, []);

  const handleLogout = () => {
    setUser(null);
  };

  return (
    <BrowserRouter>
      <Routes>
        <Route 
          path="/" 
          element={
            <HomePage 
              user={user} 
              authLoading={authLoading} 
              onDevLoginSuccess={(u) => setUser(u)} 
            />
          } 
        />
        <Route 
          path="/login" 
          element={
            <div className="min-h-screen bg-[#161718] flex items-center justify-center p-4">
              <LoginScreen onDevLoginSuccess={(u: User) => { setUser(u); window.location.href = "/dashboard"; }} />
            </div>
          } 
        />
        <Route 
          path="/signup" 
          element={
            <div className="min-h-screen bg-[#161718] flex items-center justify-center p-4">
              <LoginScreen onDevLoginSuccess={(u: User) => { setUser(u); window.location.href = "/dashboard"; }} />
            </div>
          } 
        />
        <Route 
          path="/dashboard/*" 
          element={
            <ProtectedRoute user={user} loading={authLoading}>
              <DashboardPage user={user!} onLogout={handleLogout} />
            </ProtectedRoute>
          } 
        />
        <Route 
          path="/docs/*" 
          element={
            <ProtectedRoute user={user} loading={authLoading}>
              <DocumentationPage user={user!} onLogout={handleLogout} />
            </ProtectedRoute>
          } 
        />
        <Route 
          path="/cicd/*" 
          element={
            <ProtectedRoute user={user} loading={authLoading}>
              <CICDPage user={user!} onLogout={handleLogout} />
            </ProtectedRoute>
          } 
        />
        <Route 
          path="/history/*" 
          element={
            <ProtectedRoute user={user} loading={authLoading}>
              <HistoryPage user={user!} onLogout={handleLogout} />
            </ProtectedRoute>
          } 
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
