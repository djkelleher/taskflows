import { useEffect } from "react";
import { Routes, Route, Navigate, Outlet } from "react-router-dom";
import { ToastProvider } from "@/components/ui/Toast";
import { ConfirmProvider } from "@/components/ui/ConfirmDialog";
import { MainLayout } from "@/components/layout";
import { useAuthStore } from "@/stores/authStore";

// Pages
import { LoginPage } from "@/pages/LoginPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { LogsPage } from "@/pages/LogsPage";
import { EnvironmentsPage } from "@/pages/EnvironmentsPage";
import { EnvironmentCreatePage } from "@/pages/EnvironmentCreatePage";
import { EnvironmentEditPage } from "@/pages/EnvironmentEditPage";

function ProtectedRoute() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const isInitialized = useAuthStore((state) => state.isInitialized);

  // Wait for auth initialization before redirecting
  if (!isInitialized) {
    return null;
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return <Outlet />;
}

function App() {
  const initialize = useAuthStore((state) => state.initialize);
  const isInitialized = useAuthStore((state) => state.isInitialized);

  useEffect(() => {
    initialize();
  }, [initialize]);

  // Show nothing while initializing to prevent flash
  if (!isInitialized) {
    return null;
  }

  return (
    <ToastProvider>
      <ConfirmProvider>
        <Routes>
          {/* Public routes */}
          <Route path="/login" element={<LoginPage />} />

          {/* Protected routes */}
          <Route element={<ProtectedRoute />}>
            <Route element={<MainLayout />}>
              <Route path="/" element={<DashboardPage />} />
              <Route path="/logs/:serviceName" element={<LogsPage />} />
              <Route path="/environments" element={<EnvironmentsPage />} />
              <Route path="/environments/create" element={<EnvironmentCreatePage />} />
              <Route path="/environments/edit/:name" element={<EnvironmentEditPage />} />
            </Route>
          </Route>

          {/* Catch all */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </ConfirmProvider>
    </ToastProvider>
  );
}

export default App;
