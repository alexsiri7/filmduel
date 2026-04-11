import { useState, useEffect, useCallback, useRef } from "react";
import { Swords, Eye, EyeOff, CheckCircle2 } from "lucide-react";
import { fetchPair, submitDuel, fetchStats } from "../api";
import MovieCard from "../components/MovieCard";
import { Button } from "../components/ui/button";
import { cn } from "../lib/utils";

const MODE = "discovery";

function SkeletonCard() {
  return (
    <div className="w-full max-w-[280px] rounded-xl border border-border bg-card overflow-hidden animate-pulse">
      <div className="aspect-[2/3] bg-secondary" />
      <div className="p-3 space-y-2">
        <div className="h-4 bg-secondary rounded w-3/4" />
        <div className="h-3 bg-secondary rounded w-1/2" />
      </div>
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
    // Start prefetching the next pair immediately
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
      // Briefly show result, then load next
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
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-6">
        <div className="text-6xl">🎬</div>
        <p className="text-muted-foreground text-lg text-center max-w-md">
          {isPoolEmpty
            ? "Watch more movies on Trakt to get started! You need at least 2 movies in your library."
            : "Something went wrong loading your movies."}
        </p>
        <Button variant="outline" onClick={() => loadPair()}>
          Try Again
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center gap-6">
      {/* Stats bar */}
      {stats && (
        <div className="flex items-center gap-4 text-sm text-muted-foreground bg-card/50 border border-border rounded-full px-5 py-2">
          <span>
            <span className="font-semibold text-foreground tabular-nums">
              {stats.total_duels}
            </span>{" "}
            duels
          </span>
          <span className="text-border">|</span>
          <span>
            <span className="font-semibold text-foreground tabular-nums">
              {stats.total_movies_ranked}
            </span>{" "}
            ranked
          </span>
          <span className="text-border">|</span>
          <span>
            <span className="font-semibold text-foreground tabular-nums">
              {stats.unseen_count ?? 0}
            </span>{" "}
            to discover
          </span>
        </div>
      )}

      {/* Loading skeleton */}
      {loading && (
        <div className="flex flex-col items-center gap-6 w-full">
          <div className="h-7 w-48 bg-secondary rounded animate-pulse" />
          <div className="flex items-center gap-4 md:gap-8 w-full justify-center">
            <SkeletonCard />
            <div className="flex flex-col items-center gap-2 shrink-0">
              <div className="w-12 h-12 rounded-full bg-secondary animate-pulse" />
              <div className="w-6 h-3 bg-secondary rounded animate-pulse" />
            </div>
            <SkeletonCard />
          </div>
          <div className="flex gap-3">
            {[1, 2, 3, 4].map((i) => (
              <div
                key={i}
                className="h-9 w-32 bg-secondary rounded-lg animate-pulse"
              />
            ))}
          </div>
        </div>
      )}

      {/* Duel arena */}
      {!loading && pair && (
        <>
          {pickMode ? (
            <h2 className="text-xl font-bold tracking-tight text-primary animate-pulse">
              Tap your winner
            </h2>
          ) : (
            <h2 className="text-xl font-bold tracking-tight text-muted-foreground">
              Which do you prefer?
            </h2>
          )}

          <div
            key={animateKey}
            className="flex items-center gap-3 md:gap-8 w-full justify-center animate-in fade-in slide-in-from-bottom-4 duration-300"
          >
            <MovieCard
              movie={pair.movie_a}
              onClick={() => handleSubmit("a_wins")}
              delta={result?.movie_a_elo_delta}
              clickable={pickMode}
              highlight={pickMode}
            />

            <div className="flex flex-col items-center gap-2 shrink-0">
              <div
                className={cn(
                  "w-12 h-12 rounded-full flex items-center justify-center transition-colors",
                  pickMode ? "bg-primary/30" : "bg-primary/10"
                )}
              >
                <Swords className="h-6 w-6 text-primary" />
              </div>
              <span className="text-xs font-bold text-muted-foreground uppercase tracking-widest">
                vs
              </span>
            </div>

            <MovieCard
              movie={pair.movie_b}
              onClick={() => handleSubmit("b_wins")}
              delta={result?.movie_b_elo_delta}
              clickable={pickMode}
              highlight={pickMode}
            />
          </div>

          {/* Action buttons */}
          <div className="flex flex-wrap items-center justify-center gap-2 sm:gap-3 max-w-xl">
            <Button
              onClick={() => setPickMode(true)}
              disabled={submitting || pickMode}
              className={cn(
                "gap-2 transition-all",
                pickMode && "ring-2 ring-primary"
              )}
            >
              <CheckCircle2 className="h-4 w-4" />
              Seen both — pick a winner
            </Button>
            <Button
              variant="secondary"
              onClick={() => handleSubmit("a_only")}
              disabled={submitting}
              className="gap-2"
            >
              <Eye className="h-4 w-4" />
              <span className="hidden sm:inline">Only seen </span>
              <span className="truncate max-w-[100px]">
                {pair.movie_a.title}
              </span>
            </Button>
            <Button
              variant="secondary"
              onClick={() => handleSubmit("b_only")}
              disabled={submitting}
              className="gap-2"
            >
              <Eye className="h-4 w-4" />
              <span className="hidden sm:inline">Only seen </span>
              <span className="truncate max-w-[100px]">
                {pair.movie_b.title}
              </span>
            </Button>
            <Button
              variant="outline"
              onClick={() => handleSubmit("neither")}
              disabled={submitting}
              className="gap-2 text-muted-foreground"
            >
              <EyeOff className="h-4 w-4" />
              Haven't seen either
            </Button>
          </div>

          {/* Result feedback */}
          {result && (result.outcome === "a_wins" || result.outcome === "b_wins") ? (
            <p className="text-sm text-primary font-medium animate-in fade-in duration-200">
              ELO updated! Next duel loading...
            </p>
          ) : result ? (
            <p className="text-sm text-muted-foreground animate-in fade-in duration-200">
              Noted! Loading next pair...
            </p>
          ) : null}
        </>
      )}
    </div>
  );
}
