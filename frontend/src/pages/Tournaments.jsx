import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { getTournaments, createTournament, getTournamentGenres } from "../api";

const BRACKET_SIZES = [8, 16, 32, 64];
const DECADES = ["1970s", "1980s", "1990s", "2000s", "2010s", "2020s"];

export default function Tournaments() {
  const navigate = useNavigate();
  const [tournaments, setTournaments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState(null);

  // Create form state
  const [name, setName] = useState("");
  const [bracketSize, setBracketSize] = useState(16);
  const [filterMode, setFilterMode] = useState("all"); // all | genre | decade
  const [filterValue, setFilterValue] = useState("");
  const [availableGenres, setAvailableGenres] = useState([]);

  useEffect(() => {
    loadTournaments();
  }, []);

  async function loadTournaments() {
    try {
      const data = await getTournaments();
      setTournaments(data);
    } catch (err) {
      console.error("Failed to load tournaments:", err);
    } finally {
      setLoading(false);
    }
  }

  async function handleOpenCreate() {
    setShowCreate(true);
    try {
      const genres = await getTournamentGenres();
      setAvailableGenres(genres);
    } catch (err) {
      console.error("Failed to load genres:", err);
    }
  }

  async function handleCreate() {
    if (!name.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const filterType = filterMode === "all" ? null : filterMode;
      const fv = filterMode === "all" ? null : filterValue;
      const t = await createTournament(name.trim(), bracketSize, filterType, fv);
      navigate(`/tournaments/${t.id}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setCreating(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-[#6B6760] text-lg font-headline uppercase tracking-widest animate-pulse">
          Loading tournaments...
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0F0E0D] p-6 md:p-12 pb-32">
      {/* Header */}
      <header className="mb-12 flex items-start justify-between gap-4 flex-wrap">
        <h2 className="text-5xl md:text-7xl font-headline font-black uppercase tracking-tighter text-[#F5F0E8] leading-none">
          Tour<span className="text-[#E8A020]">naments</span>
        </h2>
        {!showCreate && (
          <button
            onClick={handleOpenCreate}
            className="bg-[#E8A020] text-[#0F0E0D] font-headline font-black uppercase py-4 px-8 tracking-widest text-sm hover:shadow-[0_0_30px_rgba(232,160,32,0.4)] active:scale-[0.98] transition-all shrink-0"
          >
            Create Tournament
          </button>
        )}
      </header>

      {/* Create Form */}
      {showCreate && (
        <div className="mb-12 bg-[#1d1b1a] p-6 md:p-8 border-l-4 border-[#E8A020]">
          <h3 className="text-2xl font-headline font-black uppercase tracking-tight text-[#F5F0E8] mb-6">
            New Tournament
          </h3>

          {/* Name */}
          <div className="mb-6">
            <label className="text-[10px] font-label uppercase tracking-[0.3em] text-[#6B6760] block mb-2">
              Tournament Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Horror Showdown"
              className="w-full max-w-md bg-[#0F0E0D] border border-[#F5F0E8]/10 text-[#F5F0E8] font-body px-4 py-3 placeholder:text-[#6B6760]/50 focus:border-[#E8A020]/50 focus:outline-none transition-colors"
            />
          </div>

          {/* Bracket Size */}
          <div className="mb-6">
            <label className="text-[10px] font-label uppercase tracking-[0.3em] text-[#6B6760] block mb-2">
              Bracket Size
            </label>
            <div className="flex gap-2">
              {BRACKET_SIZES.map((size) => (
                <button
                  key={size}
                  onClick={() => setBracketSize(size)}
                  className={
                    bracketSize === size
                      ? "px-6 py-2 bg-[#E8A020] text-[#0F0E0D] font-label font-bold uppercase text-xs tracking-widest border border-[#E8A020]"
                      : "px-6 py-2 bg-transparent text-[#F5F0E8]/60 font-label font-bold uppercase text-xs tracking-widest border border-[#F5F0E8]/10 hover:border-[#E8A020]/40 transition-colors"
                  }
                >
                  {size}
                </button>
              ))}
            </div>
          </div>

          {/* Filter Mode */}
          <div className="mb-6">
            <label className="text-[10px] font-label uppercase tracking-[0.3em] text-[#6B6760] block mb-2">
              Filter Films
            </label>
            <div className="flex gap-2 mb-4">
              {[
                { key: "all", label: "All Films" },
                { key: "genre", label: "By Genre" },
                { key: "decade", label: "By Decade" },
              ].map((opt) => (
                <button
                  key={opt.key}
                  onClick={() => {
                    setFilterMode(opt.key);
                    setFilterValue("");
                  }}
                  className={
                    filterMode === opt.key
                      ? "px-6 py-2 bg-[#E8A020] text-[#0F0E0D] font-label font-bold uppercase text-xs tracking-widest border border-[#E8A020]"
                      : "px-6 py-2 bg-transparent text-[#F5F0E8]/60 font-label font-bold uppercase text-xs tracking-widest border border-[#F5F0E8]/10 hover:border-[#E8A020]/40 transition-colors"
                  }
                >
                  {opt.label}
                </button>
              ))}
            </div>

            {/* Genre pills */}
            {filterMode === "genre" && (
              <div className="flex flex-wrap gap-2">
                {availableGenres.map((g) => (
                  <button
                    key={g}
                    onClick={() => setFilterValue(g)}
                    className={
                      filterValue === g
                        ? "px-4 py-1.5 bg-[#E8A020] text-[#0F0E0D] font-label font-bold uppercase text-[10px] tracking-widest border border-[#E8A020]"
                        : "px-4 py-1.5 bg-transparent text-[#F5F0E8]/60 font-label font-bold uppercase text-[10px] tracking-widest border border-[#F5F0E8]/10 hover:border-[#E8A020]/40 transition-colors"
                    }
                  >
                    {g}
                  </button>
                ))}
                {availableGenres.length === 0 && (
                  <span className="text-[#6B6760] text-sm font-body">Loading genres...</span>
                )}
              </div>
            )}

            {/* Decade pills */}
            {filterMode === "decade" && (
              <div className="flex flex-wrap gap-2">
                {DECADES.map((d) => (
                  <button
                    key={d}
                    onClick={() => setFilterValue(d)}
                    className={
                      filterValue === d
                        ? "px-4 py-1.5 bg-[#E8A020] text-[#0F0E0D] font-label font-bold uppercase text-[10px] tracking-widest border border-[#E8A020]"
                        : "px-4 py-1.5 bg-transparent text-[#F5F0E8]/60 font-label font-bold uppercase text-[10px] tracking-widest border border-[#F5F0E8]/10 hover:border-[#E8A020]/40 transition-colors"
                    }
                  >
                    {d}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Error */}
          {error && (
            <p className="text-[#C04A20] font-body text-sm mb-4">{error}</p>
          )}

          {/* Actions */}
          <div className="flex gap-3">
            <button
              onClick={handleCreate}
              disabled={creating || !name.trim() || (filterMode !== "all" && !filterValue)}
              className="bg-[#E8A020] text-[#0F0E0D] font-headline font-black uppercase py-4 px-8 tracking-widest text-sm hover:shadow-[0_0_30px_rgba(232,160,32,0.4)] active:scale-[0.98] transition-all disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {creating ? "Creating..." : "Create & Seed"}
            </button>
            <button
              onClick={() => {
                setShowCreate(false);
                setError(null);
              }}
              className="border border-[#F5F0E8]/10 hover:border-[#E8A020]/40 text-[#F5F0E8]/60 font-headline font-bold uppercase py-4 px-8 tracking-widest text-xs transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Tournament List */}
      {tournaments.length === 0 && !showCreate ? (
        <div className="p-8 text-center text-[#6B6760] bg-[#1d1b1a] font-body">
          No tournaments yet. Create one to get started!
        </div>
      ) : (
        <div className="space-y-4">
          {tournaments.map((t) => {
            const isActive = t.status === "active";
            const isCompleted = t.status === "completed";
            return (
              <div
                key={t.id}
                className={`group relative flex items-center gap-4 md:gap-8 p-4 md:p-6 transition-colors ${
                  isActive
                    ? "bg-[#1d1b1a] border-l-4 border-[#E8A020] shadow-[inset_0_0_40px_rgba(232,160,32,0.05)]"
                    : isCompleted
                    ? "bg-[#141312] border-l-4 border-[#E8A020]/40 hover:bg-[#1d1b1a]"
                    : "bg-[#141312] border-l-4 border-transparent hover:bg-[#1d1b1a] opacity-50"
                }`}
              >
                {/* Info */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline gap-3 mb-1">
                    <h3 className="font-headline font-bold uppercase text-lg md:text-2xl text-[#F5F0E8] truncate">
                      {t.name}
                    </h3>
                    <span className="text-sm font-label text-[#F5F0E8]/40 shrink-0 hidden sm:inline">
                      {t.bracket_size} films
                    </span>
                  </div>
                  <div className="flex gap-4 md:gap-6 items-center">
                    <div className="flex flex-col">
                      <span className="text-[10px] font-label uppercase tracking-widest text-[#6B6760]">
                        Status
                      </span>
                      <span
                        className={`font-headline font-bold text-sm uppercase ${
                          isActive
                            ? "text-[#E8A020]"
                            : isCompleted
                            ? "text-[#F5F0E8]/60"
                            : "text-[#6B6760]"
                        }`}
                      >
                        {t.status}
                      </span>
                    </div>
                    <div className="flex flex-col">
                      <span className="text-[10px] font-label uppercase tracking-widest text-[#6B6760]">
                        Progress
                      </span>
                      <span className="font-body text-sm text-[#F5F0E8]/60">
                        {t.progress}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Action */}
                {isActive && (
                  <button
                    onClick={() => navigate(`/tournaments/${t.id}`)}
                    className="bg-[#E8A020] text-[#0F0E0D] font-headline font-black uppercase py-3 px-6 tracking-widest text-xs hover:shadow-[0_0_20px_rgba(232,160,32,0.3)] active:scale-[0.98] transition-all shrink-0"
                  >
                    Continue
                  </button>
                )}
                {isCompleted && (
                  <button
                    onClick={() => navigate(`/tournaments/${t.id}`)}
                    className="border border-[#E8A020]/30 text-[#E8A020] font-headline font-bold uppercase py-3 px-6 tracking-widest text-xs hover:bg-[#E8A020]/10 transition-all shrink-0"
                  >
                    View Bracket
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
