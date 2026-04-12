import { useState, useEffect } from "react";
import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import Nav from "./components/Nav";
import Login from "./pages/Login";
import Duel from "./pages/Duel";
import Rankings from "./pages/Rankings";

function ProtectedRoute({ children }) {
  const [status, setStatus] = useState("loading");

  useEffect(() => {
    fetch("/api/me", { credentials: "include" })
      .then((r) => setStatus(r.ok ? "authenticated" : "unauthenticated"))
      .catch(() => setStatus("unauthenticated"));
  }, []);

  if (status === "loading") {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-muted-foreground font-headline uppercase tracking-widest animate-pulse">
          Loading...
        </div>
      </div>
    );
  }
  if (status === "unauthenticated") {
    return <Navigate to="/login" replace />;
  }
  return children;
}

export default function App() {
  const location = useLocation();
  const isLogin = location.pathname === "/login";

  if (isLogin) {
    return (
      <div className="min-h-screen bg-[#0F0E0D] text-[#F5F0E8]">
        <Routes>
          <Route path="/login" element={<Login />} />
        </Routes>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0F0E0D] text-[#F5F0E8] flex">
      <Nav />
      <main className="flex-1 md:ml-64 min-h-screen">
        <Routes>
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <Duel />
              </ProtectedRoute>
            }
          />
          <Route
            path="/rankings"
            element={
              <ProtectedRoute>
                <Rankings />
              </ProtectedRoute>
            }
          />
        </Routes>
      </main>
      {/* Mobile bottom nav */}
      <nav className="fixed bottom-0 left-0 w-full z-50 flex justify-around items-center px-4 py-2 bg-[#0F0E0D]/80 backdrop-blur-xl md:hidden shadow-[0_-8px_32px_rgba(232,160,32,0.08)]">
        <a
          href="/"
          className={`flex flex-col items-center justify-center px-6 py-2 transition-colors ${
            location.pathname === "/"
              ? "text-[#E8A020] border-t-2 border-[#E8A020] bg-[#E8A020]/10"
              : "text-[#6B6760] hover:text-[#F5F0E8]"
          }`}
        >
          <span className="text-[10px] font-bold uppercase tracking-[0.1em] font-headline">Duel</span>
        </a>
        <a
          href="/rankings"
          className={`flex flex-col items-center justify-center px-6 py-2 transition-colors ${
            location.pathname === "/rankings"
              ? "text-[#E8A020] border-t-2 border-[#E8A020] bg-[#E8A020]/10"
              : "text-[#6B6760] hover:text-[#F5F0E8]"
          }`}
        >
          <span className="text-[10px] font-bold uppercase tracking-[0.1em] font-headline">Rankings</span>
        </a>
      </nav>
    </div>
  );
}
