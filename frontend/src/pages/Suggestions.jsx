import { useState, useEffect } from "react";
import { getSuggestions, regenerateSuggestions, dismissSuggestion, addToWatchlist, markSuggestionSeen } from "../api";
import { mediaLabel, mediaLabelCap } from "../lib/utils";

function SkeletonCard() {
  return (
    <div className="bg-[#141312] animate-pulse">
      <div className="aspect-[2/3] bg-[#1d1b1a]" />
      <div className="p-4 space-y-3">
        <div className="h-5 bg-[#1d1b1a] w-3/4" />
        <div className="h-3 bg-[#1d1b1a] w-full" />
        <div className="h-3 bg-[#1d1b1a] w-2/3" />
        <div className="flex gap-2 pt-2">
          <div className="h-10 bg-[#1d1b1a] flex-1" />
          <div className="h-10 w-10 bg-[#1d1b1a]" />
        </div>
      </div>
    </div>
  );
}

export default function Suggestions({ mediaType = "movie" }) {
  const label = mediaLabel(mediaType);
  const [suggestions, setSuggestions] = useState([]);
  const [status, setStatus] = useState("loading");
  const [regenerating, setRegenerating] = useState(false);
  const [error, setError] = useState(null);

  async function load() {
    setStatus("loading");
    setError(null);
    try {
      const data = await getSuggestions(mediaType);
      setSuggestions(data.suggestions);
      setStatus(data.status);
    } catch (err) {
      console.error("Failed to load suggestions:", err);
      setError(err.message);
      setStatus("error");
    }
  }

  useEffect(() => { load(); }, [mediaType]);

  async function handleRegenerate() {
    setRegenerating(true);
    setError(null);
    try {
      const data = await regenerateSuggestions(mediaType);
      setSuggestions(data.suggestions);
      setStatus(data.status);
    } catch (err) {
      if (err.message.includes("3 times")) {
        setError("Daily regeneration limit reached. Try again tomorrow.");
      } else {
        setError(err.message);
      }
    } finally {
      setRegenerating(false);
    }
  }

  async function handleDismiss(id) {
    try {
      await dismissSuggestion(id);
      setSuggestions((prev) => prev.filter((s) => s.id !== id));
    } catch (err) {
      console.error("Failed to dismiss:", err);
    }
  }

  async function handleAddToWatchlist(id) {
    try {
      const updated = await addToWatchlist(id);
      setSuggestions((prev) =>
        prev.map((s) => (s.id === id ? { ...s, added_to_watchlist_at: updated.added_to_watchlist_at } : s))
      );
    } catch (err) {
      console.error("Failed to add to watchlist:", err);
    }
  }

  async function handleMarkSeen(id) {
    try {
      await markSuggestionSeen(id);
      setSuggestions((prev) => prev.filter((s) => s.id !== id));
    } catch (err) {
      console.error("Failed to mark seen:", err);
    }
  }

  const activeSuggestions = suggestions.filter((s) => !s.dismissed_at);
  const allDismissed = status === "ready" && suggestions.length > 0 && activeSuggestions.length === 0;

  // Loading state
  if (status === "loading") {
    return (
      <div className="min-h-screen bg-[#0F0E0D] p-6 md:p-12 pb-32">
        <header className="mb-12">
          <h2 className="text-5xl md:text-7xl font-headline font-black uppercase tracking-tighter text-[#F5F0E8] mb-2 leading-none">
            Watch <span className="text-primary-container">Next</span>
          </h2>
          <p className="text-[#6B6760] font-body text-sm">AI-curated picks based on your taste</p>
        </header>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
          {[...Array(6)].map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      </div>
    );
  }

  // Not enough ranked films
  if (status === "not_enough_films") {
    return (
      <div className="min-h-screen bg-[#0F0E0D] p-6 md:p-12 pb-32">
        <header className="mb-12">
          <h2 className="text-5xl md:text-7xl font-headline font-black uppercase tracking-tighter text-[#F5F0E8] mb-2 leading-none">
            Watch <span className="text-primary-container">Next</span>
          </h2>
        </header>
        <div className="max-w-md mx-auto text-center space-y-6 mt-24">
          <h3 className="text-2xl font-headline font-bold uppercase text-[#F5F0E8]">
            Keep dueling!
          </h3>
          <p className="text-[#6B6760] font-body leading-relaxed">
            {`We need at least 20 ranked ${label}s to understand your taste and generate personalized suggestions. Head to the duel page and keep ranking!`}
          </p>
          <a
            href="/"
            className="inline-block mt-6 px-8 py-4 bg-primary-container text-[#0F0E0D] font-headline font-black uppercase tracking-widest text-sm hover:scale-[1.02] active:scale-95 transition-all"
          >
            Start Dueling
          </a>
        </div>
      </div>
    );
  }

  // Not enough candidates in pool
  if (status === "no_candidates") {
    return (
      <div className="min-h-screen bg-[#0F0E0D] p-6 md:p-12 pb-32">
        <header className="mb-12">
          <h2 className="text-5xl md:text-7xl font-headline font-black uppercase tracking-tighter text-[#F5F0E8] mb-2 leading-none">
            Watch <span className="text-primary-container">Next</span>
          </h2>
        </header>
        <div className="max-w-md mx-auto text-center space-y-6 mt-24">
          <h3 className="text-2xl font-headline font-bold uppercase text-[#F5F0E8]">
            Pool expanding...
          </h3>
          <p className="text-[#6B6760] font-body leading-relaxed">
            {`We're adding more ${label}s to your pool. Swipe a few rounds to classify new ${label}s, then come back for personalized suggestions.`}
          </p>
          <a
            href="/swipe"
            className="inline-block mt-6 px-8 py-4 bg-primary-container text-[#0F0E0D] font-headline font-black uppercase tracking-widest text-sm hover:scale-[1.02] active:scale-95 transition-all"
          >
            {`Swipe ${mediaLabelCap(mediaType)}s`}
          </a>
        </div>
      </div>
    );
  }

  // Error state
  if (status === "error") {
    return (
      <div className="min-h-screen bg-[#0F0E0D] p-6 md:p-12 pb-32">
        <header className="mb-12">
          <h2 className="text-5xl md:text-7xl font-headline font-black uppercase tracking-tighter text-[#F5F0E8] mb-2 leading-none">
            Watch <span className="text-primary-container">Next</span>
          </h2>
        </header>
        <div className="max-w-md mx-auto text-center space-y-6 mt-24">
          <p className="text-[#F5F0E8]/60 font-body">{error || "Something went wrong."}</p>
          <button
            onClick={load}
            className="px-8 py-4 bg-primary-container text-[#0F0E0D] font-headline font-black uppercase tracking-widest text-sm hover:scale-[1.02] active:scale-95 transition-all"
          >
            Try Again
          </button>
        </div>
      </div>
    );
  }

  // All dismissed
  if (allDismissed) {
    return (
      <div className="min-h-screen bg-[#0F0E0D] p-6 md:p-12 pb-32">
        <header className="mb-12">
          <h2 className="text-5xl md:text-7xl font-headline font-black uppercase tracking-tighter text-[#F5F0E8] mb-2 leading-none">
            Watch <span className="text-primary-container">Next</span>
          </h2>
        </header>
        <div className="max-w-md mx-auto text-center space-y-6 mt-24">
          <h3 className="text-2xl font-headline font-bold uppercase text-[#F5F0E8]">
            All caught up!
          </h3>
          <p className="text-[#6B6760] font-body leading-relaxed">
            You've reviewed all your suggestions. Generate a fresh batch?
          </p>
          <button
            onClick={handleRegenerate}
            disabled={regenerating}
            className="px-8 py-4 bg-primary-container text-[#0F0E0D] font-headline font-black uppercase tracking-widest text-sm hover:scale-[1.02] active:scale-95 transition-all disabled:opacity-50"
          >
            {regenerating ? "Generating..." : "Regenerate Suggestions"}
          </button>
          {error && (
            <p className="text-red-400 font-body text-sm">{error}</p>
          )}
        </div>
      </div>
    );
  }

  // Ready state — show cards
  return (
    <div className="min-h-screen bg-[#0F0E0D] p-6 md:p-12 pb-32">
      <header className="mb-12 flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
        <div>
          <h2 className="text-5xl md:text-7xl font-headline font-black uppercase tracking-tighter text-[#F5F0E8] mb-2 leading-none">
            Watch <span className="text-primary-container">Next</span>
          </h2>
          <p className="text-[#6B6760] font-body text-sm">AI-curated picks based on your taste</p>
        </div>
        <button
          onClick={handleRegenerate}
          disabled={regenerating}
          className="px-6 py-3 bg-transparent border border-[#F5F0E8]/10 text-[#F5F0E8]/60 font-headline font-bold uppercase text-xs tracking-widest hover:border-primary-container/40 hover:text-primary-container transition-colors disabled:opacity-50 shrink-0"
        >
          {regenerating ? "Generating..." : "Refresh"}
        </button>
      </header>

      {error && (
        <div className="mb-6 p-4 bg-red-900/20 border border-red-500/30 text-red-400 font-body text-sm">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
        {activeSuggestions.map((s) => (
          <div
            key={s.id}
            className="group bg-[#141312] overflow-hidden transition-all hover:shadow-accent-sm"
          >
            {/* Poster */}
            <div className="relative aspect-[2/3] overflow-hidden">
              {s.movie.poster_url ? (
                <img
                  src={s.movie.poster_url}
                  alt={s.movie.title}
                  className="w-full h-full object-cover grayscale-[30%] group-hover:grayscale-0 transition-all duration-500"
                  loading="lazy"
                />
              ) : (
                <div className="w-full h-full bg-[#1d1b1a] flex items-center justify-center">
                  <span className="text-[#6B6760] font-headline text-4xl opacity-30">?</span>
                </div>
              )}
              {/* Title overlay */}
              <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/90 via-black/50 to-transparent p-4 pt-12">
                <h3 className="font-headline font-bold uppercase text-[#F5F0E8] text-lg leading-tight truncate">
                  {s.movie.title}
                </h3>
                {s.movie.year && (
                  <span className="text-xs font-label text-[#F5F0E8]/50">{s.movie.year}</span>
                )}
              </div>
            </div>

            {/* Reason + links + actions */}
            <div className="p-4 space-y-3">
              <p className="text-[#F5F0E8]/50 font-body text-sm italic leading-relaxed">
                {s.reason}
              </p>

              {/* External links */}
              <div className="flex gap-3">
                {s.movie.imdb_id && (
                  <a
                    href={`https://www.imdb.com/title/${s.movie.imdb_id}/`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[10px] font-label uppercase tracking-widest text-[#F5F0E8]/30 hover:text-primary-container transition-colors"
                  >
                    IMDB
                  </a>
                )}
                {s.movie.trakt_id && (
                  <a
                    href={`https://trakt.tv/search/trakt/${s.movie.trakt_id}?id_type=${s.movie.media_type === "show" ? "show" : "movie"}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[10px] font-label uppercase tracking-widest text-[#F5F0E8]/30 hover:text-primary-container transition-colors"
                  >
                    Trakt
                  </a>
                )}
              </div>

              {/* Action buttons */}
              <div className="flex gap-2">
                {s.added_to_watchlist_at ? (
                  <div className="flex-1 flex items-center justify-center gap-2 px-4 py-3 bg-primary-container/20 text-primary-container font-headline font-bold uppercase text-xs tracking-widest">
                    On Watchlist
                  </div>
                ) : (
                  <button
                    onClick={() => handleAddToWatchlist(s.id)}
                    className="flex-1 px-4 py-3 bg-primary-container text-[#0F0E0D] font-headline font-bold uppercase text-xs tracking-widest hover:scale-[1.02] active:scale-95 transition-all"
                  >
                    Watchlist
                  </button>
                )}
                <button
                  onClick={() => handleMarkSeen(s.id)}
                  className="px-3 py-3 border border-primary-container/30 text-primary-container/70 font-headline font-bold uppercase text-[10px] tracking-widest hover:bg-primary-container/10 hover:text-primary-container transition-colors"
                  title={`I've seen this ${label}`}
                >
                  Seen it
                </button>
                <button
                  onClick={() => handleDismiss(s.id)}
                  className="w-12 h-12 flex items-center justify-center border border-[#F5F0E8]/10 text-[#F5F0E8]/40 hover:text-[#F5F0E8] hover:border-[#F5F0E8]/30 transition-colors text-lg"
                  title="Dismiss"
                >
                  &times;
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
