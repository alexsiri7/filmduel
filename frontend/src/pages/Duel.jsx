import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { fetchPair, submitDuel, fetchStats } from "../api";
import MovieCard from "../components/MovieCard";
import { mediaLabel, mediaLabelCap } from "../lib/utils";

const MODE = "discovery";

function SkeletonCard() {
  return (
    <div className="w-full max-w-[150px] md:max-w-[340px] overflow-hidden animate-pulse">
      <div className="aspect-[2/3] bg-[#1d1b1a]" />
    </div>
  );
}

export default function Duel({ mediaType = "movie" }) {
  const label = mediaLabel(mediaType);
  const navigate = useNavigate();
  const [pair, setPair] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [stats, setStats] = useState(null);

  const [animateKey, setAnimateKey] = useState(0);
  const [showSwipePrompt, setShowSwipePrompt] = useState(false);
  const prefetchRef = useRef(null);
  const [windowWidth, setWindowWidth] = useState(window.innerWidth);

  useEffect(() => {
    const handleResize = () => setWindowWidth(window.innerWidth);
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  const loadStats = useCallback(async () => {
    try {
      const data = await fetchStats(mediaType);
      setStats(data);
    } catch (err) {
      console.error("Failed to load stats:", err);
    }
  }, [mediaType]);

  const prefetchNext = useCallback(() => {
    prefetchRef.current = fetchPair(MODE, null, mediaType).catch(() => null);
  }, [mediaType]);

  const loadPair = useCallback(
    async (usePrefetch = false) => {
      setLoading(true);
      setResult(null);
      setError(null);
      try {
        let data;
        if (usePrefetch && prefetchRef.current) {
          data = await prefetchRef.current;
          prefetchRef.current = null;
        }
        if (!data) {
          data = await fetchPair(MODE, null, mediaType);
        }
        setPair(data);
        setAnimateKey((k) => k + 1);
        // Eagerly preload the next pair while user considers this one
        prefetchNext();
      } catch (err) {
        console.error("Failed to load movie pair:", err);
        // If not enough seen films, redirect to swipe
        if (err.message?.includes("Swipe") || err.message?.includes("seen films")) {
          navigate("/swipe");
          return;
        }
        setError(err.message);
        setPair(null);
      } finally {
        setLoading(false);
      }
    },
    [mediaType]
  );

  useEffect(() => {
    prefetchRef.current = null;
    loadPair();
    loadStats();
  }, [loadPair, loadStats]);

  const handleSubmit = (outcome) => {
    if (!pair || submitting) return;
    setSubmitting(true);
    setResult({ outcome });

    // Fire-and-forget: submit duel in background, don't block the UI
    submitDuel(pair.movie_a.id, pair.movie_b.id, outcome, MODE)
      .then((res) => {
        // Check if we need to swipe — handle asynchronously
        if (res.next_action === "swipe") {
          setShowSwipePrompt(true);
        }
        // Stats update in background
        loadStats();
      })
      .catch((err) => console.error("Failed to submit duel:", err));

    // Immediately show winner flash for 600ms, then load next pair from prefetch
    setTimeout(() => {
      setSubmitting(false);
      loadPair(true);
    }, 600);
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
    <div className="min-h-screen flex flex-col bg-[#141312] relative">
      {/* Swipe interstitial overlay */}
      {showSwipePrompt && (
        <div className="absolute inset-0 z-50 bg-[#0F0E0D]/95 backdrop-blur-xl flex flex-col items-center justify-center gap-8 p-12">
          <div className="text-center space-y-4">
            <p className="text-[10px] font-label uppercase tracking-[0.3em] text-[#d6c4ae]/60">
              {`Running low on ${label}s`}
            </p>
            <h2 className="text-3xl md:text-4xl font-headline font-black uppercase tracking-tighter text-[#F5F0E8]">
              {`Time to discover more ${label}s`}
            </h2>
            <p className="text-[#6B6760] font-body text-lg max-w-md">
              {`Swipe through 10 ${label}s to classify them as seen or unseen, then come back for more duels.`}
            </p>
          </div>
          <div className="flex flex-col gap-3 w-full max-w-xs">
            <button
              onClick={() => navigate("/swipe")}
              className="bg-[#E8A020] text-[#0F0E0D] font-headline font-black py-5 uppercase tracking-[0.2em] text-base hover:shadow-[0_0_30px_rgba(232,160,32,0.4)] active:scale-[0.98] transition-all"
            >
              {`Swipe 10 ${mediaLabelCap(mediaType)}s`}
            </button>
            <button
              onClick={() => {
                setShowSwipePrompt(false);
                loadPair(true);
                loadStats();
              }}
              className="border border-[#514534]/30 hover:border-[#E8A020]/50 hover:bg-[#1d1b1a] text-[#d6c4ae] font-headline font-bold uppercase tracking-widest text-xs py-4 transition-all"
            >
              Keep Dueling
            </button>
          </div>
        </div>
      )}

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
                  {`${label}s ranked`}
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
          <div className="w-full max-w-7xl flex items-center justify-center gap-3 md:gap-6">
            <SkeletonCard />
            <div className="w-10 h-10 md:w-20 md:h-20 bg-[#942b00] animate-pulse rotate-45 shrink-0" />
            <SkeletonCard />
          </div>
        )}

        {/* Duel arena */}
        {!loading && pair && (
          <>
            {/* Instruction */}
            <p className="text-[10px] font-label uppercase tracking-[0.3em] text-[#6B6760]">
              {`Tap the ${label} you rate higher`}
            </p>

            {/* Cards Container */}
            <div
              key={animateKey}
              className="w-full max-w-7xl flex flex-row items-center justify-center gap-3 md:gap-6 relative"
            >
              {/* Left Film Card */}
              <div className="flex-1 max-w-[200px] md:max-w-[500px] shadow-2xl flex justify-end">
                <MovieCard
                  movie={pair.movie_a}
                  onClick={() => handleSubmit("a_wins")}
                  clickable={!submitting && !result}
                  compact={windowWidth < 768}
                  chosen={result ? (result.outcome === "a_wins" ? "winner" : "loser") : undefined}
                />
              </div>

              {/* VS Badge */}
              <div className="z-20 relative md:-mx-8 shrink-0">
                <div className="w-10 h-10 md:w-20 md:h-20 bg-[#942b00] flex items-center justify-center rounded-none shadow-[0_0_40px_rgba(148,43,0,0.4)] border-2 border-[#ffb59d]/20 rotate-45">
                  <span className="font-headline font-black text-sm md:text-2xl text-[#ffb59d] -rotate-45 italic tracking-tighter">
                    VS
                  </span>
                </div>
              </div>

              {/* Right Film Card */}
              <div className="flex-1 max-w-[200px] md:max-w-[500px] shadow-2xl flex justify-start">
                <MovieCard
                  movie={pair.movie_b}
                  onClick={() => handleSubmit("b_wins")}
                  clickable={!submitting && !result}
                  compact={windowWidth < 768}
                  chosen={result ? (result.outcome === "b_wins" ? "winner" : "loser") : undefined}
                />
              </div>
            </div>

            {/* Result feedback — brief winner flash before next pair */}
          </>
        )}
      </section>
    </div>
  );
}
