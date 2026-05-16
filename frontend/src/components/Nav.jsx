import { useState, useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import { logout, getMe, updateSettings } from "../api";
import ReportIssueModal from "./ReportIssueModal";

const navItems = [
  { path: "/", label: "Current Duel", icon: "swords" },
  { path: "/swipe", label: "Swipe", icon: "swipe" },
  { path: "/rankings", label: "Rankings", icon: "leaderboard" },
  { path: "/suggestions", label: "Watch Next", icon: "suggest" },
  { path: "/tournaments", label: "Tournaments", icon: "bracket" },
];

export default function Nav({ mediaType, setMediaType }) {
  const location = useLocation();
  const [showFeedback, setShowFeedback] = useState(false);
  const [syncRatings, setSyncRatings] = useState(false);

  useEffect(() => {
    getMe().then((user) => {
      if (user) setSyncRatings(user.sync_ratings_to_trakt);
    });
  }, []);

  const handleSyncToggle = async () => {
    const next = !syncRatings;
    setSyncRatings(next);
    await updateSettings({ sync_ratings_to_trakt: next });
  };

  const handleLogout = async () => {
    await logout();
    window.location.href = "/login";
  };

  return (
    <aside className="fixed left-0 top-0 h-full w-64 z-40 bg-[#141312] shadow-[10px_0_30px_rgba(0,0,0,0.3)] hidden md:flex flex-col py-8 px-4 gap-8">
      {/* Logo */}
      <div className="flex items-center gap-3 px-2">
        <div className="w-10 h-10 flex items-center justify-center">
          <img src="/logo.png" alt="FilmDuel" className="w-10 h-10 object-contain" />
        </div>
        <div>
          <h1 className="text-primary-container text-xl font-black font-headline tracking-tighter uppercase">
            FILMDUEL
          </h1>
          <p className="text-[#F5F0E8]/40 text-[10px] uppercase tracking-[0.2em] font-bold">
            The Noir Projectionist
          </p>
        </div>
      </div>

      {/* Media type toggle */}
      <div className="flex bg-[#0F0E0D] rounded-sm p-1 gap-1 mx-2">
        <button
          onClick={() => setMediaType("movie")}
          className={`flex-1 py-2 text-xs font-headline font-bold uppercase tracking-widest transition-colors rounded-sm ${
            mediaType === "movie"
              ? "bg-primary-container text-[#0F0E0D]"
              : "text-[#F5F0E8]/40 hover:text-[#F5F0E8]/60"
          }`}
        >
          Movies
        </button>
        <button
          onClick={() => setMediaType("show")}
          className={`flex-1 py-2 text-xs font-headline font-bold uppercase tracking-widest transition-colors rounded-sm ${
            mediaType === "show"
              ? "bg-primary-container text-[#0F0E0D]"
              : "text-[#F5F0E8]/40 hover:text-[#F5F0E8]/60"
          }`}
        >
          Shows
        </button>
      </div>

      {/* Nav items */}
      <nav className="flex-1 space-y-2">
        {navItems.map((item) => {
          const isActive =
            item.path === "/"
              ? location.pathname === "/"
              : location.pathname.startsWith(item.path);
          return (
            <Link
              key={item.path}
              to={item.path}
              className={
                isActive
                  ? "flex items-center gap-4 px-4 py-3 bg-primary-container text-[#0F0E0D] rounded-none shadow-accent-sm font-headline font-bold uppercase tracking-wider transition-all duration-300"
                  : "flex items-center gap-4 px-4 py-3 text-[#F5F0E8]/40 hover:text-[#F5F0E8] hover:bg-[#1d1b1a] font-headline font-bold uppercase tracking-wider transition-all hover:translate-x-1 duration-300"
              }
            >
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>

      {/* Actions */}
      <div className="px-2 space-y-3">
        <Link
          to="/"
          className="block w-full bg-primary-container text-[#0F0E0D] font-headline font-black uppercase py-4 tracking-widest text-sm text-center hover:scale-[1.02] active:scale-95 transition-all"
        >
          START DUEL
        </Link>
        <button
          onClick={() => setShowFeedback(true)}
          className="block w-full text-center text-[#F5F0E8]/30 hover:text-primary-container/70 font-headline font-bold uppercase text-xs tracking-widest py-2 transition-colors"
        >
          Report Issue
        </button>
        <label className="flex items-center justify-between w-full cursor-pointer py-2 group">
          <span className="text-[#F5F0E8]/30 group-hover:text-[#F5F0E8]/60 font-headline font-bold uppercase text-xs tracking-widest transition-colors">
            Sync to Trakt
          </span>
          <button
            role="switch"
            aria-checked={syncRatings}
            onClick={handleSyncToggle}
            className={`relative w-9 h-5 rounded-full transition-colors ${
              syncRatings ? "bg-primary-container" : "bg-[#F5F0E8]/20"
            }`}
          >
            <span
              className={`absolute top-0.5 left-0.5 w-4 h-4 bg-[#0F0E0D] rounded-full transition-transform ${
                syncRatings ? "translate-x-4" : ""
              }`}
            />
          </button>
        </label>
        <button
          onClick={handleLogout}
          className="w-full text-[#F5F0E8]/30 hover:text-[#F5F0E8]/60 font-headline font-bold uppercase text-xs tracking-widest py-2 transition-colors"
        >
          Sign Out
        </button>
      </div>
      {showFeedback && <ReportIssueModal onClose={() => setShowFeedback(false)} />}
    </aside>
  );
}
