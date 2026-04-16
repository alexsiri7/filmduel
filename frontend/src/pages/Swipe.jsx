import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { fetchSwipeCards, submitSwipeResults } from "../api";
import SwipeCard from "../components/SwipeCard";
import { mediaLabel } from "../lib/utils";

export default function Swipe({ mediaType = "movie" }) {
  const label = mediaLabel(mediaType);
  const navigate = useNavigate();
  const [cards, setCards] = useState([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [summary, setSummary] = useState(null);
  const [cardKey, setCardKey] = useState(0);

  const loadCards = useCallback(async () => {
    setLoading(true);
    setError(null);
    setCurrentIndex(0);
    setResults([]);
    setSummary(null);
    setCardKey(0);
    try {
      const data = await fetchSwipeCards(mediaType);
      if (!data || data.length === 0) {
        setCards([]);
      } else {
        setCards(data);
      }
    } catch (err) {
      setError(err.message);
      setCards([]);
    } finally {
      setLoading(false);
    }
  }, [mediaType]);

  useEffect(() => {
    loadCards();
  }, [loadCards]);

  const handleSwipe = useCallback(
    (seen) => {
      const card = cards[currentIndex];
      if (!card) return;

      const newResults = [...results, { movie_id: card.id, seen }];
      setResults(newResults);

      if (currentIndex + 1 >= cards.length) {
        // All cards done, submit
        setSubmitting(true);
        submitSwipeResults(newResults, mediaType)
          .then((res) => {
            setSummary(res);
          })
          .catch((err) => {
            setError(err.message);
          })
          .finally(() => {
            setSubmitting(false);
          });
      } else {
        setCurrentIndex((i) => i + 1);
        setCardKey((k) => k + 1);
      }
    },
    [cards, currentIndex, results]
  );

  const handleButtonSwipe = (seen) => {
    handleSwipe(seen);
  };

  // Summary screen — auto-continue if need more seen films
  // NOTE: This useEffect MUST be before any early returns to satisfy React's rules of hooks
  useEffect(() => {
    if (summary && summary.next_action === "swipe") {
      const timer = setTimeout(() => {
        loadCards();
      }, 1500);
      return () => clearTimeout(timer);
    }
  }, [summary, loadCards]);

  // Loading state
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#0F0E0D]">
        <div className="text-[#6B6760] font-headline uppercase tracking-widest animate-pulse">
          {`Loading ${label}s...`}
        </div>
      </div>
    );
  }

  // Error state
  if (error && !cards.length) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-6 p-12 bg-[#0F0E0D]">
        <p className="text-[#6B6760] text-lg text-center max-w-md font-body">{error}</p>
        <button
          onClick={loadCards}
          className="border border-[#514534]/30 hover:border-primary-container/50 hover:bg-[#1d1b1a] text-[#d6c4ae] font-headline font-bold uppercase tracking-widest text-xs py-4 px-8 transition-all"
        >
          Try Again
        </button>
      </div>
    );
  }

  if (summary) {
    const needMore = summary.next_action === "swipe";
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-8 p-12 bg-[#0F0E0D]">
        <div className="text-center space-y-4">
          <p className="text-[10px] font-label uppercase tracking-[0.3em] text-[#d6c4ae]/60">
            {needMore ? "Round Complete" : "Swipe Complete"}
          </p>
          <h2 className="text-4xl md:text-5xl font-headline font-black uppercase tracking-tighter text-[#F5F0E8]">
            {`You've seen ${summary.seen_count} of these ${label}s`}
          </h2>
          <p className="text-[#6B6760] font-body text-lg">
            {needMore
              ? `Loading more ${label}s...`
              : `${summary.unseen_count} new discoveries added to your pool`}
          </p>
          {needMore && (
            <div className="w-16 h-0.5 bg-primary-container mx-auto animate-pulse mt-4" />
          )}
        </div>

        {!needMore && (
          <div className="flex flex-col gap-3 w-full max-w-xs">
            <button
              onClick={() => navigate("/")}
              className="bg-primary-container text-[#0F0E0D] font-headline font-black py-5 uppercase tracking-[0.2em] text-base hover:shadow-accent-md active:scale-[0.98] transition-all"
            >
              Start Dueling
            </button>
            <button
              onClick={loadCards}
              className="border border-[#514534]/30 hover:border-primary-container/50 hover:bg-[#1d1b1a] text-[#d6c4ae] font-headline font-bold uppercase tracking-widest text-xs py-4 transition-all"
            >
              Swipe More
            </button>
          </div>
        )}
      </div>
    );
  }

  // No cards
  if (!cards.length) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-6 p-12 bg-[#0F0E0D]">
        <p className="text-[#6B6760] text-lg text-center max-w-md font-body">
          {`No unknown ${label}s left to swipe. You've classified them all!`}
        </p>
        <button
          onClick={() => navigate("/")}
          className="bg-primary-container text-[#0F0E0D] font-headline font-black py-4 px-8 uppercase tracking-[0.2em] text-sm hover:shadow-accent-md active:scale-[0.98] transition-all"
        >
          Back to Duels
        </button>
      </div>
    );
  }

  const card = cards[currentIndex];
  const total = cards.length;

  return (
    <div className="min-h-screen flex flex-col bg-[#0F0E0D]">
      {/* Progress header */}
      <header className="h-16 px-6 flex items-center justify-between bg-[#0F0E0D]/70 backdrop-blur-xl border-b border-primary-container/10 sticky top-0 z-30">
        <span className="text-[10px] font-label uppercase tracking-[0.3em] text-[#d6c4ae]/60">
          Swipe Session
        </span>
        <span className="font-headline font-bold text-primary-container text-lg">
          {currentIndex + 1} / {total}
        </span>
      </header>

      {/* Progress bar */}
      <div className="h-1 bg-[#1d1b1a]">
        <div
          className="h-full bg-primary-container transition-all duration-300"
          style={{ width: `${((currentIndex + 1) / total) * 100}%` }}
        />
      </div>

      {/* Card area */}
      <section className="flex-1 flex flex-col items-center justify-center p-4 md:p-8 gap-6">
        <SwipeCard key={cardKey} movie={card} onSwipe={handleSwipe} />

        {/* Button controls */}
        <div className="flex gap-4 w-full max-w-[380px]">
          <button
            onClick={() => handleButtonSwipe(false)}
            disabled={submitting}
            className="flex-1 border-2 border-[#514534]/40 hover:border-[#F5F0E8]/40 text-[#d6c4ae] font-headline font-bold uppercase tracking-widest text-xs py-4 transition-all disabled:opacity-40 hover:bg-[#1d1b1a]"
          >
            Never seen it
          </button>
          <button
            onClick={() => handleButtonSwipe(true)}
            disabled={submitting}
            className="flex-1 bg-primary-container text-[#0F0E0D] font-headline font-black uppercase tracking-widest text-xs py-4 hover:shadow-accent-sm active:scale-[0.98] transition-all disabled:opacity-40"
          >
            Seen it
          </button>
        </div>

        <p className="text-[10px] font-label uppercase tracking-[0.2em] text-[#6B6760]">
          Swipe right = seen &middot; Swipe left = not seen
        </p>
      </section>
    </div>
  );
}
