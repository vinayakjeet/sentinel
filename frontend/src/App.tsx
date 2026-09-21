import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { StreamProvider } from "./hooks/StreamContext";
import { Layout } from "./components/Layout";
import { Login } from "./pages/Login";
import { LiveStream } from "./pages/LiveStream";
import { AlertQueue } from "./pages/AlertQueue";
import { ModelHealth } from "./pages/ModelHealth";

// The force-graph bundle is large; load it only when a case is opened.
const CaseDetail = lazy(() => import("./pages/CaseDetail"));

function Authed() {
  const { session } = useAuth();
  if (!session) return <Login />;
  return (
    <StreamProvider token={session.token}>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<LiveStream />} />
          <Route path="alerts" element={<AlertQueue />} />
          <Route path="health" element={<ModelHealth />} />
          <Route
            path="cases/:decisionId"
            element={<Suspense fallback={<p className="p-6 text-ink-300">Loading case…</p>}><CaseDetail /></Suspense>}
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </StreamProvider>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Authed />
      </AuthProvider>
    </BrowserRouter>
  );
}
