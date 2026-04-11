import { useState, useEffect, useCallback } from "react";
import { Swords, Eye, EyeOff } from "lucide-react";
import { getMoviePair, submitDuel } from "../api";
import MovieCard from "../components/MovieCard";
import { Button } from "../components/ui/button";

function DuelSkeleton() {
  return (
    <div className="skeleton-duel">
      <div className="skeleton skeleton-header" />
      <div className="skeleton-cards">
        <div className="skeleton-card">
          <div className="skeleton skeleton-poster" />
          <div className="skeleton-card-body">
            <div className="skeleton skeleton-title" />
            <div className="skeleton skeleton-year" />
          </div>
        </div>
        <div className="skeleton skeleton-vs" />
        <div className="skeleton-card">
          <div className="skeleton skeleton-poster" />
          <div className="skeleton-card-body">
            <div className="skeleton skeleton-title" />
            <div className="skeleton skeleton-year" />
          </div>
        </div>
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

  const loadPair = useCallback(async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await getMoviePair();
      setPair(data);
    } catch (err) {
      console.error("Failed to load movie pair:", err);
      setError(err.message || "Could not load movies.");
      setPair(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadPair();
  }, [loadPair]);

  const handleChoice = async (outcome) => {
    if (!pair || submitting) return;
    setSubmitting(true);
    try {
      const res = await submitDuel(pair.movie_a.id, pair.movie_b.id, outcome);
      setResult(res);
      setTimeout(loadPair, 1500);
    } catch (err) {
      console.error("Failed to submit duel:", err);
      setError(err.message || "Failed to submit. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return <DuelSkeleton />;
  }

  if (error && !pair) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4">
        <p className="text-muted-foreground">{error}</p>
        <Button variant="outline" onClick={loadPair}>
          Try Again
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center gap-8">
      <h2 className="text-2xl font-bold tracking-tight">Which do you prefer?</h2>

      {/* Duel arena — two cards with VS divider */}
      <div className="flex items-center gap-4 md:gap-8 w-full justify-center">
        <MovieCard
          movie={pair.movie_a}
          onClick={() => handleChoice("a_wins")}
          delta={result?.movie_a_elo_delta}
          disabled={submitting}
        />

        <div className="flex flex-col items-center gap-2 shrink-0">
          <div className="w-12 h-12 rounded-full bg-primary/20 flex items-center justify-center">
            <Swords className="h-6 w-6 text-primary" />
          </div>
          <span className="text-sm font-bold text-muted-foreground uppercase tracking-widest">
            vs
          </span>
        </div>

        <MovieCard
          movie={pair.movie_b}
          onClick={() => handleChoice("b_wins")}
          delta={result?.movie_b_elo_delta}
          disabled={submitting}
        />
      </div>

      {/* Action buttons */}
      <div className="flex flex-wrap items-center justify-center gap-3">
        <Button
          variant="secondary"
          onClick={() => handleChoice("a_only")}
          disabled={submitting}
          className="gap-2"
        >
          <Eye className="h-4 w-4" />
          Only seen left
        </Button>
        <Button
          variant="outline"
          onClick={() => handleChoice("neither")}
          disabled={submitting}
          className="gap-2"
        >
          <EyeOff className="h-4 w-4" />
          Seen neither
        </Button>
        <Button
          variant="secondary"
          onClick={() => handleChoice("b_only")}
          disabled={submitting}
          className="gap-2"
        >
          <Eye className="h-4 w-4" />
          Only seen right
        </Button>
      </div>

      {/* Error feedback */}
      {error && (
        <p className="text-sm text-destructive animate-in fade-in">
          {error}
        </p>
      )}

      {/* Result feedback */}
      {result && !error && (
        <p className="text-sm text-muted-foreground animate-in fade-in">
          ELO updated. Next duel loading...
        </p>
      )}
    </div>
  );
}
