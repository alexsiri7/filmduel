import { useState, useEffect, useCallback, useRef } from "react";
import { fetchPair, submitDuel, fetchStats } from "../api";
import MovieCard from "../components/MovieCard";
import { cn } from "../lib/utils";

const MODE = "discovery";

function SkeletonCard() {
  return (
    <div className="w-full max-w-[340px] overflow-hidden animate-pulse">
      <div className="aspect-[2/3] bg-[#1d1b1a]" />
    </div>
  );
}

export default function Duel() {
  const [pair, setPair] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [stats, setStats] = useState(null);
  const [pickMode, setPickMode] = useState(false);
  const [animateKey, setAnimateKey] = useState(0);
  const prefetchRef = useRef(null);

  const loadStats = useCallback(async () => {
    try {
      const data = await fetchStats();
      setStats(data);
    } catch (err) {
      console.error("Failed to load stats:", err);
    }
  }, []);

  const prefetchNext = useCallback(() => {
    prefetchRef.current = fetchPair(MODE).catch(() => null);
  }, []);

  const loadPair = useCallback(
    async (usePrefetch = false) => {
      setLoading(true);
      setResult(null);
      setPickMode(false);
      setError(null);
      try {
        let data;
        if (usePrefetch && prefetchRef.current) {
          data = await prefetchRef.current;
          prefetchRef.current = null;
        }
        if (!data) {
          data = await fetchPair(MODE);
        }
        setPair(data);
        setAnimateKey((k) => k + 1);
      } catch (err) {
        console.error("Failed to load movie pair:", err);
        setError(err.message);
        setPair(null);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  useEffect(() => {
    loadPair();
    loadStats();
  }, [loadPair, loadStats]);

  const handleSubmit = async (outcome) => {
    if (!pair || submitting) return;
    setSubmitting(true);
    prefetchNext();
    try {
      const res = await submitDuel(
        pair.movie_a.id,
        pair.movie_b.id,
        outcome,
        MODE
      );
      setResult(res);
      setPickMode(false);
      setTimeout(() => {
        loadPair(true);
        loadStats();
      }, 900);
    } catch (err) {
      console.error("Failed to submit duel:", err);
    } finally {
      setSubmitting(false);
    }
  };

  // Pool empty / error state
  if (!loading && error) {
    const isPoolEmpty =
      error.includes("Not enough") || error.includes("pool");
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-6 p-12">
        <p className="text-[#6B6760] text-lg text-center max-w-md font-body">
          {isPoolEmpty
            ? "Watch more movies on Trakt to get started! You need at least 2 movies in your library."
            : "Something went wrong loading your movies."}
        </p>
        <button
          onClick={() => loadPair()}
          className="border border-[#514534]/30 hover:border-[#E8A020]/50 hover:bg-[#1d1b1a] text-[#d6c4ae] font-headline font-bold uppercase tracking-widest text-xs py-4 px-8 transition-all"
        >
          Try Again
        </button>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col bg-[#141312]">
      {/* Top Stats Bar */}
      <header className="h-20 px-6 md:px-12 flex justify-between items-center bg-[#0F0E0D]/70 backdrop-blur-xl border-b border-[#E8A020]/10 sticky top-0 z-30">
        <div className="flex gap-6 md:gap-12">
          {stats && (
            <>
              <div className="flex flex-col">
                <span className="text-[10px] font-label uppercase tracking-[0.2em] text-[#d6c4ae]/60">
                  duels played
                </span>
                <span className="text-lg font-headline font-bold text-[#E8A020]">
                  {stats.total_duels?.toLocaleString()}
                </span>
              </div>
              <div className="flex flex-col">
                <span className="text-[10px] font-label uppercase tracking-[0.2em] text-[#d6c4ae]/60">
                  films ranked
                </span>
                <span className="text-lg font-headline font-bold text-[#E8A020]">
                  {stats.total_movies_ranked?.toLocaleString()}
                </span>
              </div>
              <div className="flex flex-col">
                <span className="text-[10px] font-label uppercase tracking-[0.2em] text-[#d6c4ae]/60">
                  to discover
                </span>
                <span className="text-lg font-headline font-bold text-[#E8A020]">
                  {(stats.unseen_count ?? 0).toLocaleString()}
                </span>
              </div>
            </>
          )}
        </div>
      </header>

      {/* Duel Content Area */}
      <section className="flex-1 p-4 md:p-12 flex flex-col items-center justify-center gap-8 md:gap-12">
        {/* Loading skeleton */}
        {loading && (
          <div className="w-full max-w-7xl flex items-center justify-center gap-6">
            <SkeletonCard />
            <div className="w-20 h-20 bg-[#942b00] animate-pulse rotate-45 hidden md:block" />
            <SkeletonCard />
          </div>
        )}

        {/* Duel arena */}
        {!loading && pair && (
          <>
            {/* Instruction */}
            {pickMode ? (
              <div className="text-center">
                <h2 className="text-[#F5F0E8] font-body text-lg font-medium opacity-80 italic animate-pulse">
                  Tap the film you rate higher
                </h2>
              </div>
            ) : (
              <div className="text-center">
                <h2 className="text-[#6B6760] font-body text-lg font-medium opacity-80">
                  Which do you prefer?
                </h2>
              </div>
            )}

            {/* Cards Container */}
            <div
              key={animateKey}
              className="w-full max-w-7xl flex flex-col md:flex-row items-center justify-between gap-4 md:gap-6 relative"
            >
              {/* Left Film Card */}
              <div className="flex-1 w-full max-w-[500px] shadow-2xl">
                <MovieCard
                  movie={pair.movie_a}
                  onClick={() => handleSubmit("a_wins")}
                  delta={result?.movie_a_elo_delta}
                  clickable={pickMode}
                  highlight={pickMode}
                />
              </div>

              {/* VS Badge */}
              <div className="z-20 relative md:-mx-8 my-2 md:my-0">
                <div className="w-16 h-16 md:w-20 md:h-20 bg-[#942b00] flex items-center justify-center rounded-none shadow-[0_0_40px_rgba(148,43,0,0.4)] border-2 border-[#ffb59d]/20 rotate-45">
                  <span className="font-headline font-black text-xl md:text-2xl text-[#ffb59d] -rotate-45 italic tracking-tighter">
                    VS
                  </span>
                </div>
              </div>

              {/* Right Film Card */}
              <div className="flex-1 w-full max-w-[500px] shadow-2xl">
                <MovieCard
                  movie={pair.movie_b}
                  onClick={() => handleSubmit("b_wins")}
                  delta={result?.movie_b_elo_delta}
                  clickable={pickMode}
                  highlight={pickMode}
                />
              </div>
            </div>

            {/* Action Controls */}
            <div className="w-full max-w-4xl grid grid-cols-1 md:grid-cols-4 gap-3 md:gap-4">
              <button
                onClick={() => setPickMode(true)}
                disabled={submitting || pickMode}
                className={cn(
                  "md:col-span-4 bg-[#ffbe5b] text-[#442b00] font-headline font-black py-5 md:py-6 uppercase tracking-[0.2em] text-base md:text-lg hover:shadow-[0_0_30px_rgba(232,160,32,0.4)] active:scale-[0.98] transition-all disabled:opacity-60",
                  pickMode && "shadow-[0_0_30px_rgba(232,160,32,0.4)]"
                )}
              >
                I've seen both — pick a winner
              </button>
              <button
                onClick={() => handleSubmit("a_only")}
                disabled={submitting}
                className="border border-[#514534]/30 hover:border-[#E8A020]/50 hover:bg-[#1d1b1a] text-[#d6c4ae] font-label uppercase tracking-widest text-xs py-4 transition-all disabled:opacity-40"
              >
                <span className="hidden md:inline">Only seen </span>
                <span className="truncate">{pair.movie_a.title}</span>
              </button>
              <button
                onClick={() => handleSubmit("b_only")}
                disabled={submitting}
                className="border border-[#514534]/30 hover:border-[#E8A020]/50 hover:bg-[#1d1b1a] text-[#d6c4ae] font-label uppercase tracking-widest text-xs py-4 transition-all disabled:opacity-40"
              >
                <span className="hidden md:inline">Only seen </span>
                <span className="truncate">{pair.movie_b.title}</span>
              </button>
              <button
                onClick={() => handleSubmit("neither")}
                disabled={submitting}
                className="md:col-span-2 border border-[#514534]/30 hover:border-[#C04A20]/50 hover:bg-[#1d1b1a] text-[#d6c4ae] font-label uppercase tracking-widest text-xs py-4 transition-all disabled:opacity-40"
              >
                Haven't seen either
              </button>
            </div>

            {/* Result feedback */}
            {result &&
              (result.outcome === "a_wins" || result.outcome === "b_wins") ? (
              <p className="text-sm text-[#E8A020] font-headline font-medium uppercase tracking-widest">
                ELO updated! Next duel loading...
              </p>
            ) : result ? (
              <p className="text-sm text-[#6B6760] font-headline font-medium uppercase tracking-widest">
                Noted! Loading next pair...
              </p>
            ) : null}
          </>
        )}
      </section>
    </div>
  );
}
