/**
 * Fetch wrapper for the FilmDuel API.
 */

async function request(path, options = {}) {
  const res = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  if (res.status === 401) { window.location.href = "/login"; return null; }
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(error.detail || `HTTP ${res.status}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

export function getMe() { return request("/api/me"); }

export function fetchPair(mode = "discovery", lastPairToken = null) {
  const params = new URLSearchParams({ mode });
  if (lastPairToken) params.set("last_pair_token", lastPairToken);
  return request(`/api/movies/pair?${params}`);
}

export function submitDuel(movieAId, movieBId, outcome, mode = "discovery") {
  return request("/api/duels", {
    method: "POST",
    body: JSON.stringify({ movie_a_id: movieAId, movie_b_id: movieBId, outcome, mode }),
  });
}

export function getRankings(limit = 50, offset = 0) {
  return request(`/api/rankings?limit=${limit}&offset=${offset}`);
}

export function fetchStats() { return request("/api/rankings/stats"); }
export const getStats = fetchStats;

export function fetchSwipeCards() { return request("/api/swipe/cards"); }

export function submitSwipeResults(results) {
  return request("/api/swipe/results", {
    method: "POST",
    body: JSON.stringify({ results }),
  });
}

export function logout() { return request("/auth/logout", { method: "POST" }); }

// ── Tournaments ──────────────────────────────────────────────────────

export function getTournaments() {
  return request("/api/tournaments");
}

export function getTournamentGenres() {
  return request("/api/tournaments/genres");
}

export function createTournament(name, bracketSize, filterType, filterValue) {
  return request("/api/tournaments", {
    method: "POST",
    body: JSON.stringify({
      name,
      bracket_size: bracketSize,
      filter_type: filterType || null,
      filter_value: filterValue || null,
    }),
  });
}

export function getTournament(id) {
  return request(`/api/tournaments/${id}`);
}

export function getNextMatch(tournamentId) {
  return request(`/api/tournaments/${tournamentId}/next`);
}

export function submitTournamentMatch(tournamentId, matchId, winnerMovieId) {
  return request(`/api/tournaments/${tournamentId}/matches/${matchId}`, {
    method: "POST",
    body: JSON.stringify({ winner_movie_id: winnerMovieId }),
  });
}

export function abandonTournament(id) {
  return request(`/api/tournaments/${id}`, { method: "DELETE" });
}
