import { useState, useEffect, useCallback, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { getTournament, submitTournamentMatch, abandonTournament, regenerateTournament } from "../api";
import MovieCard from "../components/MovieCard";
import { mediaLabel } from "../lib/utils";

function roundLabel(round, totalRounds) {
  if (round === totalRounds) return "Final";
  if (round === totalRounds - 1) return "Semifinals";
  if (round === totalRounds - 2) return "Quarterfinals";
  return `Round ${round}`;
}

function matchCountInRound(bracketSize, round) {
  return bracketSize / Math.pow(2, round);
}

/** Tiny poster thumbnail for bracket cells */
function PosterThumb({ movie, isWinner, isLoser }) {
  if (!movie) {
    return (
      <div className="w-8 h-12 bg-[#1d1b1a] shrink-0 border border-[#F5F0E8]/5" />
    );
  }
  return (
    <div className="w-8 h-12 shrink-0 overflow-hidden relative">
      <img
        src={movie.poster_url || ""}
        alt={movie.title}
        className={`w-full h-full object-cover transition-all ${
          isLoser ? "grayscale opacity-40" : ""
        } ${isWinner ? "brightness-110" : ""}`}
        loading="lazy"
        onError={(e) => {
          e.target.style.display = "none";
        }}
      />
      {isWinner && (
        <div className="absolute inset-0 border border-[#E8A020]/60" />
      )}
    </div>
  );
}

/** Single match card in the bracket */
function BracketMatch({ match, isNext, totalRounds, onClick }) {
  const played = !!match.winner_movie_id;
  const isBye = match.is_bye;
  const aWins = played && match.winner_movie_id === match.movie_a?.id;
  const bWins = played && match.winner_movie_id === match.movie_b?.id;

  return (
    <div
      onClick={isNext && !played && !isBye ? onClick : undefined}
      className={`relative bg-[#1d1b1a] border transition-all w-full ${
        isBye
          ? "border-[#F5F0E8]/5 opacity-50"
          : isNext && !played
          ? "border-[#E8A020]/60 shadow-[0_0_20px_rgba(232,160,32,0.15)] cursor-pointer hover:border-[#E8A020] animate-pulse-slow"
          : played
          ? "border-[#F5F0E8]/5"
          : "border-[#F5F0E8]/5 opacity-60"
      }`}
    >
      {/* Movie A */}
      <div
        className={`flex items-center gap-2 px-2 py-1.5 border-b border-[#F5F0E8]/5 ${
          aWins && !isBye ? "bg-[#E8A020]/10" : ""
        }`}
      >
        <PosterThumb
          movie={match.movie_a}
          isWinner={aWins && !isBye}
          isLoser={bWins && !isBye}
        />
        <span
          className={`text-[11px] font-headline font-bold uppercase tracking-tight truncate ${
            isBye
              ? "text-[#F5F0E8]/50"
              : aWins
              ? "text-[#E8A020]"
              : bWins
              ? "text-[#F5F0E8]/30"
              : "text-[#F5F0E8]/70"
          }`}
        >
          {match.movie_a?.title || "TBD"}
        </span>
      </div>
      {/* Movie B */}
      <div
        className={`flex items-center gap-2 px-2 py-1.5 ${
          bWins && !isBye ? "bg-[#E8A020]/10" : ""
        }`}
      >
        {isBye ? (
          <>
            <div className="w-8 h-12 bg-[#1d1b1a] shrink-0 border border-[#F5F0E8]/5" />
            <span className="text-[11px] font-headline font-bold uppercase tracking-tight text-[#6B6760]">
              BYE
            </span>
          </>
        ) : (
          <>
            <PosterThumb
              movie={match.movie_b}
              isWinner={bWins}
              isLoser={aWins}
            />
            <span
              className={`text-[11px] font-headline font-bold uppercase tracking-tight truncate ${
                bWins
                  ? "text-[#E8A020]"
                  : aWins
                  ? "text-[#F5F0E8]/30"
                  : "text-[#F5F0E8]/70"
              }`}
            >
              {match.movie_b?.title || "TBD"}
            </span>
          </>
        )}
      </div>
      {/* Next match indicator */}
      {isNext && !played && !isBye && (
        <div className="absolute -top-2 left-1/2 -translate-x-1/2 z-10">
          <span className="bg-[#E8A020] text-[#0F0E0D] px-2 py-0.5 text-[8px] font-headline font-black uppercase tracking-wider">
            Next
          </span>
        </div>
      )}
    </div>
  );
}

export default function TournamentBracket({ mediaType = "movie" }) {
  const { id } = useParams();
  const navigate = useNavigate();
  const label = mediaLabel(mediaType);
  const [tournament, setTournament] = useState(null);
  const [loading, setLoading] = useState(true);
  const [playing, setPlaying] = useState(false); // match play mode
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [winnerFlash, setWinnerFlash] = useState(null); // brief flash between matches
  const [regenerating, setRegenerating] = useState(false);

  const loadTournament = useCallback(async () => {
    try {
      const data = await getTournament(id);
      setTournament(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    loadTournament();
  }, [loadTournament]);

  // Compute bracket structure
  const { rounds, totalRounds, nextMatch, champion } = useMemo(() => {
    if (!tournament) return { rounds: [], totalRounds: 0, nextMatch: null, champion: null };

    const tr = Math.log2(tournament.bracket_size);
    const roundMap = {};
    let next = null;

    for (const m of tournament.matches) {
      if (!roundMap[m.round]) roundMap[m.round] = [];
      roundMap[m.round].push(m);
    }

    // Sort each round by position
    const roundsList = [];
    for (let r = 1; r <= tr; r++) {
      const matches = (roundMap[r] || []).sort((a, b) => a.position - b.position);
      roundsList.push({ round: r, matches });
    }

    // Find next playable match
    for (const rd of roundsList) {
      for (const m of rd.matches) {
        if (m.movie_a && m.movie_b && !m.winner_movie_id) {
          next = m;
          break;
        }
      }
      if (next) break;
    }

    // Find champion
    let champ = null;
    if (tournament.status === "completed" && tournament.champion_movie_id) {
      for (const m of tournament.matches) {
        if (m.movie_a?.id === tournament.champion_movie_id) {
          champ = m.movie_a;
          break;
        }
        if (m.movie_b?.id === tournament.champion_movie_id) {
          champ = m.movie_b;
          break;
        }
      }
    }

    return { rounds: roundsList, totalRounds: tr, nextMatch: next, champion: champ };
  }, [tournament]);

  // Helper: find the next playable match from tournament data
  function findNextPlayable(tournamentData) {
    if (!tournamentData) return null;
    const sorted = [...tournamentData.matches].sort((a, b) =>
      a.round !== b.round ? a.round - b.round : a.position - b.position
    );
    for (const m of sorted) {
      if (m.movie_a && m.movie_b && !m.winner_movie_id) return m;
    }
    return null;
  }

  function handlePick(winnerMovieId) {
    if (submitting || !nextMatch) return;
    setSubmitting(true);

    const currentRound = nextMatch.round;
    const matchId = nextMatch.id;
    const winnerMovie =
      nextMatch.movie_a.id === winnerMovieId ? nextMatch.movie_a : nextMatch.movie_b;

    // Immediately show winner flash
    setWinnerFlash(winnerMovie);

    // Optimistically update local tournament state so nextMatch recalculates instantly
    setTournament((prev) => {
      if (!prev) return prev;
      const updatedMatches = prev.matches.map((m) => {
        if (m.id === matchId) {
          return { ...m, winner_movie_id: winnerMovieId };
        }
        // Propagate winner to next round slot
        const nextPos = Math.floor(
          prev.matches.find((mm) => mm.id === matchId)?.position / 2
        );
        if (
          m.round === currentRound + 1 &&
          m.position === nextPos
        ) {
          const srcMatch = prev.matches.find((mm) => mm.id === matchId);
          if (srcMatch && srcMatch.position % 2 === 0) {
            return { ...m, movie_a: winnerMovie };
          } else {
            return { ...m, movie_b: winnerMovie };
          }
        }
        return m;
      });
      return { ...prev, matches: updatedMatches };
    });

    // Fire API in background — reconcile with server state when it responds
    submitTournamentMatch(id, matchId, winnerMovieId)
      .then((serverState) => {
        // Server state is authoritative — reconcile
        setTournament(serverState);
        const newNext = findNextPlayable(serverState);
        if (!newNext || newNext.round !== currentRound) {
          setPlaying(false);
        }
      })
      .catch((err) => {
        setError(err.message);
        // Reload on error to get correct state
        loadTournament();
      });

    // Re-enable interaction after flash
    setTimeout(() => {
      setWinnerFlash(null);
      setSubmitting(false);
    }, 600);
  }

  async function handleRegenerate() {
    setRegenerating(true);
    setError(null);
    try {
      const updated = await regenerateTournament(id);
      setTournament(updated);
    } catch (err) {
      setError(err.message);
    } finally {
      setRegenerating(false);
    }
  }

  // Check if regeneration is available (AI-curated, no non-bye matches played)
  const canRegenerate = tournament?.is_ai_curated &&
    tournament?.status === "active" &&
    !tournament?.matches?.some((m) => m.winner_movie_id && !m.is_bye);

  async function handleAbandon() {
    if (!confirm("Abandon this tournament? This cannot be undone.")) return;
    try {
      await abandonTournament(id);
      navigate("/tournaments");
    } catch (err) {
      setError(err.message);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-[#6B6760] text-lg font-headline uppercase tracking-widest animate-pulse">
          Loading bracket...
        </div>
      </div>
    );
  }

  if (error && !tournament) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-6 p-12">
        <p className="text-[#C04A20] font-body text-lg">{error}</p>
        <button
          onClick={() => navigate("/tournaments")}
          className="border border-[#514534]/30 hover:border-[#E8A020]/50 hover:bg-[#1d1b1a] text-[#d6c4ae] font-headline font-bold uppercase tracking-widest text-xs py-4 px-8 transition-all"
        >
          Back to Tournaments
        </button>
      </div>
    );
  }

  // ── Match Play Mode ──────────────────────────────────────────────
  if (playing && nextMatch) {
    const currentRoundMatches = rounds.find((r) => r.round === nextMatch.round)?.matches || [];
    const matchIndex = currentRoundMatches.findIndex((m) => m.id === nextMatch.id);
    const totalInRound = currentRoundMatches.length;

    return (
      <div className="min-h-screen flex flex-col bg-[#0F0E0D] relative">
        {/* Context header */}
        <header className="h-16 px-6 md:px-12 flex justify-between items-center bg-[#0F0E0D]/70 backdrop-blur-xl border-b border-[#E8A020]/10 sticky top-0 z-30">
          <div className="flex items-center gap-4">
            <button
              onClick={() => setPlaying(false)}
              className="text-[#F5F0E8]/40 hover:text-[#F5F0E8] font-headline font-bold uppercase text-xs tracking-widest transition-colors"
            >
              Back to Bracket
            </button>
          </div>
          <div className="text-center">
            <span className="text-[10px] font-label uppercase tracking-[0.3em] text-[#E8A020]">
              {roundLabel(nextMatch.round, totalRounds)} — Match {matchIndex + 1} of {totalInRound}
            </span>
          </div>
          <div className="w-24" />
        </header>

        {/* Duel arena */}
        <section className="flex-1 p-4 md:p-12 flex flex-col items-center justify-center gap-8 md:gap-12">
          <p className="text-[10px] font-label uppercase tracking-[0.3em] text-[#6B6760]">
            {`Tap the ${label} you rate higher`}
          </p>

          <div className="w-full max-w-7xl flex flex-col md:flex-row items-center justify-between gap-4 md:gap-6 relative">
            {/* Movie A */}
            <div className="flex-1 w-full max-w-[500px] shadow-2xl flex justify-end">
              <MovieCard
                movie={nextMatch.movie_a}
                onClick={() => handlePick(nextMatch.movie_a.id)}
                clickable={!submitting}
              />
            </div>

            {/* VS Badge */}
            <div className="z-20 relative md:-mx-8 my-2 md:my-0 shrink-0">
              <div className="w-16 h-16 md:w-20 md:h-20 bg-[#942b00] flex items-center justify-center rounded-none shadow-[0_0_40px_rgba(148,43,0,0.4)] border-2 border-[#ffb59d]/20 rotate-45">
                <span className="font-headline font-black text-xl md:text-2xl text-[#ffb59d] -rotate-45 italic tracking-tighter">
                  VS
                </span>
              </div>
            </div>

            {/* Movie B */}
            <div className="flex-1 w-full max-w-[500px] shadow-2xl flex justify-start">
              <MovieCard
                movie={nextMatch.movie_b}
                onClick={() => handlePick(nextMatch.movie_b.id)}
                clickable={!submitting}
              />
            </div>
          </div>

          {submitting && (
            <p className="text-sm text-[#E8A020] font-headline font-medium uppercase tracking-widest animate-pulse">
              Submitting...
            </p>
          )}
        </section>

        {/* Winner flash overlay */}
        {winnerFlash && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0F0E0D]/80 backdrop-blur-sm animate-fade-out">
            <div className="text-center">
              <p className="text-[10px] font-label uppercase tracking-[0.3em] text-[#E8A020] mb-3">
                Winner
              </p>
              <h3 className="text-3xl md:text-5xl font-headline font-black uppercase tracking-tighter text-[#E8A020] leading-none">
                {winnerFlash.title}
              </h3>
              <p className="text-sm text-[#F5F0E8]/40 mt-2 font-label">advances to next round</p>
            </div>
          </div>
        )}
      </div>
    );
  }

  // ── Bracket View ─────────────────────────────────────────────────
  const isCompleted = tournament.status === "completed";
  const isAbandoned = tournament.status === "abandoned";

  return (
    <div className="min-h-screen bg-[#0F0E0D] p-6 md:p-12 pb-32">
      {/* Header */}
      <header className="mb-8">
        <div className="flex items-center gap-4 mb-2">
          <button
            onClick={() => navigate("/tournaments")}
            className="text-[#F5F0E8]/40 hover:text-[#F5F0E8] font-headline font-bold uppercase text-xs tracking-widest transition-colors"
          >
            Tournaments
          </button>
          <span className="text-[#F5F0E8]/20">/</span>
        </div>
        <h2 className="text-4xl md:text-6xl font-headline font-black uppercase tracking-tighter text-[#F5F0E8] leading-none mb-2">
          {tournament.name}
        </h2>
        {tournament.tagline && (
          <p className="text-lg md:text-xl font-body text-[#E8A020]/80 italic mb-2">
            {tournament.tagline}
          </p>
        )}
        {tournament.theme_description && (
          <p className="text-sm font-body text-[#F5F0E8]/50 mb-4 max-w-2xl leading-relaxed">
            {tournament.theme_description}
          </p>
        )}
        <div className="flex items-center gap-6 flex-wrap">
          <span className="text-[10px] font-label uppercase tracking-[0.3em] text-[#6B6760]">
            {tournament.bracket_size} {label}s
          </span>
          <span
            className={`text-[10px] font-label uppercase tracking-[0.3em] ${
              isCompleted ? "text-[#E8A020]" : isAbandoned ? "text-[#C04A20]" : "text-[#6B6760]"
            }`}
          >
            {tournament.status}
          </span>
          {tournament.filter_type && (
            <span className="text-[10px] font-label uppercase tracking-[0.3em] text-[#6B6760]">
              {tournament.filter_type}: {tournament.filter_value}
            </span>
          )}
        </div>
      </header>

      {/* Champion Banner */}
      {isCompleted && champion && (
        <div className="mb-10 bg-[#1d1b1a] border-l-4 border-[#E8A020] p-6 md:p-8 flex items-center gap-6 shadow-[inset_0_0_60px_rgba(232,160,32,0.05)]">
          <div className="w-20 h-28 md:w-28 md:h-40 shrink-0 overflow-hidden relative">
            {champion.poster_url && (
              <img
                src={champion.poster_url}
                alt={champion.title}
                className="w-full h-full object-cover"
              />
            )}
            <div className="absolute inset-0 noir-gradient" />
          </div>
          <div>
            <span className="text-3xl md:text-4xl mb-2 block">&#127942;</span>
            <p className="text-[10px] font-label uppercase tracking-[0.3em] text-[#E8A020] mb-1">
              Champion
            </p>
            <h3 className="text-2xl md:text-4xl font-headline font-black uppercase tracking-tighter text-[#E8A020] leading-none">
              {champion.title}
            </h3>
            {champion.year && (
              <p className="text-sm font-label text-[#F5F0E8]/40 mt-1">{champion.year}</p>
            )}
          </div>
        </div>
      )}

      {/* Play Round Button + Regenerate */}
      {nextMatch && !isCompleted && !isAbandoned && (() => {
        const roundMatches = rounds.find((r) => r.round === nextMatch.round)?.matches || [];
        const remaining = roundMatches.filter((m) => !m.winner_movie_id).length;
        const label = remaining > 1
          ? `Play ${roundLabel(nextMatch.round, totalRounds)} (${remaining} matches)`
          : "Play Next Match";
        return (
          <div className="mb-8 flex items-center gap-4 flex-wrap">
            <button
              onClick={() => setPlaying(true)}
              className="bg-[#E8A020] text-[#0F0E0D] font-headline font-black uppercase py-4 px-8 tracking-widest text-sm hover:shadow-[0_0_30px_rgba(232,160,32,0.4)] active:scale-[0.98] transition-all"
            >
              {label}
            </button>
            {canRegenerate && (
              <button
                onClick={handleRegenerate}
                disabled={regenerating}
                className="border border-[#E8A020]/30 text-[#E8A020] font-headline font-bold uppercase py-4 px-6 tracking-widest text-xs hover:bg-[#E8A020]/10 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {regenerating ? "Regenerating..." : "Regenerate"}
              </button>
            )}
          </div>
        );
      })()}

      {/* Error */}
      {error && (
        <p className="text-[#C04A20] font-body text-sm mb-4">{error}</p>
      )}

      {/* Bracket Grid */}
      <div className="overflow-x-auto pb-6 -mx-6 px-6">
        <div
          className="flex gap-4 md:gap-6"
          style={{ minWidth: `${rounds.length * 200}px` }}
        >
          {rounds.map((rd) => (
            <div key={rd.round} className="flex-1 min-w-[160px] md:min-w-[180px]">
              {/* Round Header */}
              <div className="mb-4 pb-2 border-b border-[#F5F0E8]/10">
                <span className="text-[10px] font-label uppercase tracking-[0.3em] text-[#6B6760]">
                  {roundLabel(rd.round, totalRounds)}
                </span>
              </div>

              {/* Matches */}
              <div
                className="flex flex-col justify-around h-full gap-2"
                style={{
                  // Increase spacing for later rounds to align with feeder matches
                  gap: `${Math.pow(2, rd.round - 1) * 8}px`,
                  paddingTop: `${(Math.pow(2, rd.round - 1) - 1) * 24}px`,
                }}
              >
                {rd.matches.map((m) => (
                  <BracketMatch
                    key={m.id}
                    match={m}
                    isNext={nextMatch?.id === m.id}
                    totalRounds={totalRounds}
                    onClick={() => setPlaying(true)}
                  />
                ))}
              </div>
            </div>
          ))}

          {/* Champion column */}
          <div className="min-w-[140px] md:min-w-[160px]">
            <div className="mb-4 pb-2 border-b border-[#E8A020]/30">
              <span className="text-[10px] font-label uppercase tracking-[0.3em] text-[#E8A020]">
                Champion
              </span>
            </div>
            <div
              className="flex flex-col justify-around h-full"
              style={{
                paddingTop: `${(Math.pow(2, totalRounds) - 1) * 24}px`,
              }}
            >
              {champion ? (
                <div className="bg-[#1d1b1a] border border-[#E8A020]/40 p-3 shadow-[0_0_20px_rgba(232,160,32,0.1)]">
                  <div className="flex items-center gap-2">
                    <PosterThumb movie={champion} isWinner />
                    <div className="min-w-0">
                      <span className="text-[11px] font-headline font-bold uppercase tracking-tight text-[#E8A020] truncate block">
                        {champion.title}
                      </span>
                      <span className="text-[9px] text-[#F5F0E8]/40">
                        &#127942; Winner
                      </span>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="bg-[#1d1b1a] border border-[#F5F0E8]/5 p-3 opacity-40">
                  <span className="text-[11px] font-headline font-bold uppercase tracking-tight text-[#F5F0E8]/30">
                    TBD
                  </span>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Bracket connector lines via CSS (visual hint) */}
      <style>{`
        .animate-pulse-slow {
          animation: pulse-slow 2s ease-in-out infinite;
        }
        @keyframes pulse-slow {
          0%, 100% { box-shadow: 0 0 10px rgba(232,160,32,0.1); }
          50% { box-shadow: 0 0 25px rgba(232,160,32,0.25); }
        }
        .animate-fade-out {
          animation: fade-in-out 600ms ease-in-out forwards;
        }
        @keyframes fade-in-out {
          0% { opacity: 0; transform: scale(0.95); }
          20% { opacity: 1; transform: scale(1); }
          80% { opacity: 1; transform: scale(1); }
          100% { opacity: 0; transform: scale(1.02); }
        }
      `}</style>

      {/* Abandon button */}
      {!isCompleted && !isAbandoned && (
        <div className="mt-12 pt-8 border-t border-[#F5F0E8]/5">
          <button
            onClick={handleAbandon}
            className="text-[#C04A20]/60 hover:text-[#C04A20] font-headline font-bold uppercase text-xs tracking-widest transition-colors"
          >
            Abandon Tournament
          </button>
        </div>
      )}
    </div>
  );
}
