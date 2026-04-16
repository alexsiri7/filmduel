import { useState, useEffect } from "react";
import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import Nav from "./components/Nav";
import Login from "./pages/Login";
import Duel from "./pages/Duel";
import Rankings from "./pages/Rankings";
import Swipe from "./pages/Swipe";
import Tournaments from "./pages/Tournaments";
import Suggestions from "./pages/Suggestions";
import TournamentBracket from "./pages/TournamentBracket";

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

  const [mediaType, setMediaType] = useState(() =>
    localStorage.getItem("filmduel_media_type") || "movie"
  );

  useEffect(() => {
    localStorage.setItem("filmduel_media_type", mediaType);
  }, [mediaType]);

  useEffect(() => {
    document.body.classList.toggle("show-mode", mediaType === "show");
  }, [mediaType]);

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
      <Nav mediaType={mediaType} setMediaType={setMediaType} />
      <main className="flex-1 md:ml-64 min-h-screen">
        <Routes>
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <Duel mediaType={mediaType} />
              </ProtectedRoute>
            }
          />
          <Route
            path="/swipe"
            element={
              <ProtectedRoute>
                <Swipe mediaType={mediaType} />
              </ProtectedRoute>
            }
          />
          <Route
            path="/rankings"
            element={
              <ProtectedRoute>
                <Rankings mediaType={mediaType} />
              </ProtectedRoute>
            }
          />
          <Route
            path="/suggestions"
            element={
              <ProtectedRoute>
                <Suggestions mediaType={mediaType} />
              </ProtectedRoute>
            }
          />
          <Route
            path="/tournaments"
            element={
              <ProtectedRoute>
                <Tournaments mediaType={mediaType} />
              </ProtectedRoute>
            }
          />
          <Route
            path="/tournaments/:id"
            element={
              <ProtectedRoute>
                <TournamentBracket mediaType={mediaType} />
              </ProtectedRoute>
            }
          />
        </Routes>
      </main>
      {/* Mobile bottom nav */}
      <nav className="fixed bottom-0 left-0 w-full z-50 flex flex-col items-center bg-[#0F0E0D]/80 backdrop-blur-xl md:hidden shadow-[0_-8px_32px_rgba(232,160,32,0.08)]">
        {/* Media type toggle */}
        <div className="flex w-full justify-center gap-1 px-4 pt-2 pb-1">
          <button
            onClick={() => setMediaType("movie")}
            className={`flex-1 py-1 text-[10px] font-bold uppercase tracking-[0.1em] font-headline rounded-sm transition-colors ${
              mediaType === "movie"
                ? "bg-[#E8A020] text-[#0F0E0D]"
                : "text-[#F5F0E8]/40 hover:text-[#F5F0E8]/60"
            }`}
          >
            Movies
          </button>
          <button
            onClick={() => setMediaType("show")}
            className={`flex-1 py-1 text-[10px] font-bold uppercase tracking-[0.1em] font-headline rounded-sm transition-colors ${
              mediaType === "show"
                ? "bg-[#E8A020] text-[#0F0E0D]"
                : "text-[#F5F0E8]/40 hover:text-[#F5F0E8]/60"
            }`}
          >
            Shows
          </button>
        </div>
        <div className="flex justify-around items-center w-full px-4 py-2">
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
            href="/swipe"
            className={`flex flex-col items-center justify-center px-6 py-2 transition-colors ${
              location.pathname === "/swipe"
                ? "text-[#E8A020] border-t-2 border-[#E8A020] bg-[#E8A020]/10"
                : "text-[#6B6760] hover:text-[#F5F0E8]"
            }`}
          >
            <span className="text-[10px] font-bold uppercase tracking-[0.1em] font-headline">Swipe</span>
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
          <a
            href="/suggestions"
            className={`flex flex-col items-center justify-center px-6 py-2 transition-colors ${
              location.pathname === "/suggestions"
                ? "text-[#E8A020] border-t-2 border-[#E8A020] bg-[#E8A020]/10"
                : "text-[#6B6760] hover:text-[#F5F0E8]"
            }`}
          >
            <span className="text-[10px] font-bold uppercase tracking-[0.1em] font-headline">Watch Next</span>
          </a>
          <a
            href="/tournaments"
            className={`flex flex-col items-center justify-center px-6 py-2 transition-colors ${
              location.pathname.startsWith("/tournaments")
                ? "text-[#E8A020] border-t-2 border-[#E8A020] bg-[#E8A020]/10"
                : "text-[#6B6760] hover:text-[#F5F0E8]"
            }`}
          >
            <span className="text-[10px] font-bold uppercase tracking-[0.1em] font-headline">Brackets</span>
          </a>
        </div>
      </nav>
    </div>
  );
}
