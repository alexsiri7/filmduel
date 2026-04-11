import { useState, useEffect, useCallback } from "react";
import { getMoviePair, submitDuel } from "../api";
import MovieCard from "../components/MovieCard";

export default function Duel() {
  const [pair, setPair] = useState(null);
  const [loading, setLoading] = useState(true);
  const [result, setResult] = useState(null);

  const loadPair = useCallback(async () => {
    setLoading(true);
    setResult(null);
    try {
      const data = await getMoviePair();
      setPair(data);
    } catch (err) {
      console.error("Failed to load movie pair:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadPair();
  }, [loadPair]);

  const handleChoice = async (outcome) => {
    if (!pair) return;
    try {
      const res = await submitDuel(pair.duel_id, outcome);
      setResult(res);
      // Auto-load next pair after a short delay
      setTimeout(loadPair, 1500);
    } catch (err) {
      console.error("Failed to submit duel:", err);
    }
  };

  if (loading) {
    return <div className="duel-loading">Loading movies...</div>;
  }

  if (!pair) {
    return <div className="duel-error">Could not load movies. Try refreshing.</div>;
  }

  return (
    <div className="duel-page">
      <h2>Which do you prefer?</h2>
      <div className="duel-cards">
        <MovieCard
          movie={pair.movie_a}
          onClick={() => handleChoice("a_wins")}
          delta={result?.movie_a_elo_delta}
        />
        <div className="duel-vs">VS</div>
        <MovieCard
          movie={pair.movie_b}
          onClick={() => handleChoice("b_wins")}
          delta={result?.movie_b_elo_delta}
        />
      </div>
      <div className="duel-actions">
        <button onClick={() => handleChoice("a_only")}>Only seen left</button>
        <button onClick={() => handleChoice("neither")}>Seen neither</button>
        <button onClick={() => handleChoice("b_only")}>Only seen right</button>
      </div>
    </div>
  );
}
