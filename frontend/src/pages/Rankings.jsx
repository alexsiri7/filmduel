import { useState, useEffect } from "react";
import { getRankings, fetchStats, syncTrakt } from "../api";
import { mediaLabel, mediaLabelCap } from "../lib/utils";

const GENRE_FILTERS = ["All", "Drama", "Horror", "Sci-fi", "Thriller", "Comedy"];

export default function Rankings({ mediaType = "movie" }) {
  const label = mediaLabel(mediaType);
  const [rankings, setRankings] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeFilter, setActiveFilter] = useState("All");
  const [total, setTotal] = useState(0);
  const [syncState, setSyncState] = useState("idle"); // idle | syncing | done | error

  useEffect(() => {
    async function load() {
      setLoading(true);
      try {
        const genre = activeFilter === "All" ? null : activeFilter;
        const [rankData, statsData] = await Promise.all([
          getRankings(50, 0, genre, null, mediaType),
          fetchStats(mediaType),
        ]);
        setRankings(rankData.rankings);
        setTotal(rankData.total);
        setStats(statsData);
      } catch (err) {
        console.error("Failed to load rankings:", err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [activeFilter, mediaType]);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-[#6B6760] text-lg font-headline uppercase tracking-widest animate-pulse">
          Loading rankings...
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0F0E0D] p-6 md:p-12 pb-32">
      {/* Header */}
      <header className="mb-12">
        <div className="flex items-start justify-between mb-8 gap-4">
          <h2 className="text-5xl md:text-7xl font-headline font-black uppercase tracking-tighter text-[#F5F0E8] leading-none">
            Your <span className="text-[#E8A020]">rankings</span>
          </h2>
          <button
            onClick={async () => {
              if (syncState === "syncing") return;
              setSyncState("syncing");
              try {
                const result = await syncTrakt();
                setSyncState("done");
                if (result?.new_movies > 0) {
                  // Reload rankings to reflect new data
                  const genre = activeFilter === "All" ? null : activeFilter;
                  const [rankData, statsData] = await Promise.all([
                    getRankings(50, 0, genre, null, mediaType),
                    fetchStats(mediaType),
                  ]);
                  setRankings(rankData.rankings);
                  setTotal(rankData.total);
                  setStats(statsData);
                }
                setTimeout(() => setSyncState("idle"), 3000);
              } catch (err) {
                console.error("Sync failed:", err);
                setSyncState("error");
                setTimeout(() => setSyncState("idle"), 3000);
              }
            }}
            disabled={syncState === "syncing"}
            className={`shrink-0 mt-2 px-4 py-2 font-label font-bold uppercase text-xs tracking-widest border transition-all ${
              syncState === "syncing"
                ? "border-[#E8A020]/30 text-[#E8A020]/50 cursor-wait"
                : syncState === "done"
                ? "border-green-500/50 text-green-400"
                : syncState === "error"
                ? "border-red-500/50 text-red-400"
                : "border-[#F5F0E8]/10 text-[#F5F0E8]/60 hover:border-[#E8A020]/40 hover:text-[#E8A020]"
            }`}
          >
            {syncState === "syncing"
              ? "Syncing..."
              : syncState === "done"
              ? "Synced!"
              : syncState === "error"
              ? "Failed"
              : "Sync Trakt"}
          </button>
        </div>

        {/* Filter Pills */}
        <div className="flex items-center gap-3 flex-wrap">
          {GENRE_FILTERS.map((filter) => (
            <button
              key={filter}
              onClick={() => setActiveFilter(filter)}
              className={
                activeFilter === filter
                  ? "px-6 py-2 bg-[#E8A020] text-[#0F0E0D] font-label font-bold uppercase text-xs tracking-widest border border-[#E8A020]"
                  : "px-6 py-2 bg-transparent text-[#F5F0E8]/60 font-label font-bold uppercase text-xs tracking-widest border border-[#F5F0E8]/10 hover:border-[#E8A020]/40 transition-colors"
              }
            >
              {filter}
            </button>
          ))}
        </div>
      </header>

      {/* Rankings List */}
      {rankings.length === 0 ? (
        <div className="p-8 text-center text-[#6B6760] bg-[#1d1b1a] font-body">
          {rankings.length === 0
            ? "No rankings yet. Start dueling to build your list!"
            : `No ${label}s match this filter.`}
        </div>
      ) : (
        <div className="space-y-4">
          {rankings.map((r, idx) => {
            const isFirst = idx === 0;
            const rank = String(idx + 1).padStart(2, "0");

            return (
              <div
                key={r.movie.id}
                className={`group relative flex items-center gap-4 md:gap-8 p-4 md:p-6 transition-colors ${
                  isFirst
                    ? "bg-[#1d1b1a] border-l-4 border-[#E8A020] shadow-[inset_0_0_40px_rgba(232,160,32,0.05)]"
                    : "bg-[#141312] border-l-4 border-transparent hover:bg-[#1d1b1a]"
                }`}
              >
                {/* Rank number */}
                <div className="w-12 md:w-20 text-center shrink-0">
                  <span
                    className={`font-headline font-black italic ${
                      isFirst
                        ? "text-4xl md:text-6xl text-[#E8A020]"
                        : "text-3xl md:text-5xl text-[#F5F0E8]/20 group-hover:text-[#E8A020]/40 transition-colors"
                    }`}
                  >
                    {rank}
                  </span>
                </div>

                {/* Poster thumbnail */}
                <div
                  className={`shrink-0 relative overflow-hidden ${
                    isFirst ? "w-20 h-28 md:w-24 md:h-36" : "w-16 h-24 md:w-20 md:h-28"
                  }`}
                >
                  {r.movie.poster_url ? (
                    <img
                      src={r.movie.poster_url}
                      alt={r.movie.title}
                      className="w-full h-full object-cover grayscale group-hover:grayscale-0 transition-all duration-500"
                      loading="lazy"
                    />
                  ) : (
                    <div className="w-full h-full bg-[#1d1b1a]" />
                  )}
                </div>

                {/* Movie info */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline gap-3 mb-1">
                    <h3
                      className={`font-headline font-bold uppercase text-[#F5F0E8] truncate ${
                        isFirst ? "text-xl md:text-3xl" : "text-lg md:text-2xl"
                      }`}
                    >
                      {r.movie.title}
                    </h3>
                    <span className="text-sm font-label text-[#F5F0E8]/40 shrink-0 hidden sm:inline">
                      {r.movie.year}
                    </span>
                  </div>
                  <div className="flex gap-4 md:gap-6">
                    <div className="flex flex-col">
                      <span className="text-[10px] font-label uppercase tracking-widest text-[#6B6760]">
                        ELO Score
                      </span>
                      <span
                        className={`font-headline font-bold ${
                          isFirst
                            ? "text-lg text-[#E8A020]"
                            : "text-md text-[#F5F0E8]/60"
                        }`}
                      >
                        {r.elo?.toLocaleString()}
                      </span>
                    </div>
                    <div className="flex flex-col">
                      <span className="text-[10px] font-label uppercase tracking-widest text-[#6B6760]">
                        Rating
                      </span>
                      <span
                        className={`font-headline font-bold ${
                          isFirst
                            ? "text-lg text-[#F5F0E8]"
                            : "text-md text-[#F5F0E8]/60"
                        }`}
                      >
                        {r.trakt_rating != null ? `${r.trakt_rating}/10` : "—"}
                      </span>
                    </div>
                    <div className="flex flex-col">
                      <span className="text-[10px] font-label uppercase tracking-widest text-[#6B6760]">
                        Battles
                      </span>
                      <span
                        className={`font-headline font-bold ${
                          isFirst
                            ? "text-lg text-[#F5F0E8]"
                            : "text-md text-[#F5F0E8]/60"
                        }`}
                      >
                        {r.battles}
                      </span>
                    </div>
                  </div>
                  <div className="flex gap-3 mt-1">
                    {r.movie.trakt_id && (
                      <a
                        href={`https://trakt.tv/search/trakt/${r.movie.trakt_id}?id_type=${r.movie.media_type === "show" ? "show" : "movie"}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-[10px] font-label uppercase tracking-widest text-[#F5F0E8]/30 hover:text-[#E8A020] transition-colors"
                      >
                        Trakt
                      </a>
                    )}
                    {r.movie.imdb_id && (
                      <a
                        href={`https://www.imdb.com/title/${r.movie.imdb_id}/`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-[10px] font-label uppercase tracking-widest text-[#F5F0E8]/30 hover:text-[#E8A020] transition-colors"
                      >
                        IMDB
                      </a>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Floating Export Button */}
      <div className="fixed bottom-20 md:bottom-12 right-6 md:right-12 flex flex-col items-end gap-4 z-50">
        <a
          href={`/api/rankings/export/csv?media_type=${mediaType}`}
          download
          className="flex items-center gap-3 px-6 md:px-8 py-4 bg-[#E8A020] text-[#0F0E0D] font-headline font-black uppercase tracking-widest text-sm shadow-[0_10px_30px_rgba(232,160,32,0.3)] hover:scale-105 active:scale-95 transition-all"
        >
          Export to Letterboxd
        </a>

        {/* Quick Stats Overlay */}
        {stats && (
          <div className="p-4 bg-[#1d1b1a]/80 backdrop-blur-md border border-[#F5F0E8]/5 w-56 md:w-64 hidden md:block">
            <div className="flex justify-between items-center mb-2">
              <span className="text-[10px] font-label uppercase tracking-widest text-[#6B6760]">
                Total Ranked
              </span>
              <span className="text-sm font-headline font-bold text-[#F5F0E8]">
                {`${stats.total_movies_ranked} ${mediaLabelCap(mediaType)}s`}
              </span>
            </div>
            <div className="w-full h-1 bg-[#211f1e]">
              <div
                className="h-full bg-[#E8A020]"
                style={{
                  width: `${Math.min(
                    100,
                    ((stats.total_movies_ranked || 0) /
                      Math.max(1, stats.total_movies_ranked + (stats.unseen_count || 0))) *
                      100
                  )}%`,
                }}
              />
            </div>
            <p className="mt-3 text-[10px] font-body text-[#F5F0E8]/40 leading-relaxed">
              Rankings updated based on your last {stats.total_duels?.toLocaleString()} duels.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
