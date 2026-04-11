import { useState, useEffect, useCallback } from "react";
import { Swords, Eye, EyeOff } from "lucide-react";
import { getMoviePair, submitDuel, getStats } from "../api";
import MovieCard from "../components/MovieCard";
import { Button } from "../components/ui/button";

export default function Duel() {
  const [pair, setPair] = useState(null);
  const [loading, setLoading] = useState(true);
  const [result, setResult] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [stats, setStats] = useState(null);

  const loadStats = useCallback(async () => {
    try {
      const data = await getStats();
      setStats(data);
    } catch (err) {
      console.error("Failed to load stats:", err);
    }
  }, []);

  const loadPair = useCallback(async () => {
    setLoading(true);
    setResult(null);
    try {
      const data = await getMoviePair();
      setPair(data);
    } catch (err) {
      console.error("Failed to load movie pair:", err);
      setPair(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadPair();
    loadStats();
  }, [loadPair, loadStats]);

  const handleChoice = async (outcome) => {
    if (!pair || submitting) return;
    setSubmitting(true);
    try {
      const res = await submitDuel(pair.movie_a.id, pair.movie_b.id, outcome);
      setResult(res);
      setTimeout(() => {
        loadPair();
        loadStats();
      }, 1200);
    } catch (err) {
      console.error("Failed to submit duel:", err);
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-muted-foreground text-lg animate-pulse">
          Loading movies...
        </div>
      </div>
    );
  }

  if (!pair) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4">
        <p className="text-muted-foreground">
          Could not load movies. Try refreshing.
        </p>
        <Button variant="outline" onClick={loadPair}>
          Try Again
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center gap-8">
      {/* Stats bar */}
      {stats && (
        <div className="flex items-center gap-6 text-sm text-muted-foreground">
          <span>
            <span className="font-semibold text-foreground">{stats.total_duels}</span>
            {" duels"}
          </span>
          <span className="text-muted-foreground/40">·</span>
          <span>
            <span className="font-semibold text-foreground">{stats.total_movies_ranked}</span>
            {" ranked"}
          </span>
          <span className="text-muted-foreground/40">·</span>
          <span>
            <span className="font-semibold text-foreground">{stats.unseen_count}</span>
            {" unseen"}
          </span>
        </div>
      )}

      <h2 className="text-2xl font-bold tracking-tight">Which do you prefer?</h2>

      {/* Duel arena — two cards with VS divider */}
      <div className="flex items-center gap-4 md:gap-8 w-full justify-center">
        <MovieCard
          movie={pair.movie_a}
          onClick={() => handleChoice("a_wins")}
          delta={result?.movie_a_elo_delta}
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

      {/* Result feedback */}
      {result && (
        <p className="text-sm text-muted-foreground animate-in fade-in">
          ELO updated. Next duel loading...
        </p>
      )}
    </div>
  );
}
