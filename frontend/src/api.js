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

export function fetchPair(mode = "discovery", lastPairToken = null, mediaType = "movie") {
  const params = new URLSearchParams({ mode, media_type: mediaType });
  if (lastPairToken) params.set("last_pair_token", lastPairToken);
  return request(`/api/movies/pair?${params}`);
}

export function submitDuel(movieAId, movieBId, outcome, mode = "discovery") {
  return request("/api/duels", {
    method: "POST",
    body: JSON.stringify({ movie_a_id: movieAId, movie_b_id: movieBId, outcome, mode }),
  });
}

export function getRankings(limit = 50, offset = 0, genre = null, decade = null, mediaType = "movie") {
  const params = new URLSearchParams({ limit, offset, media_type: mediaType });
  if (genre) params.set("genre", genre);
  if (decade) params.set("decade", decade);
  return request(`/api/rankings?${params}`);
}

export function fetchStats(mediaType = "movie") {
  return request(`/api/rankings/stats?media_type=${mediaType}`);
}
export const getStats = fetchStats;

export function fetchSwipeCards(mediaType = "movie") {
  return request(`/api/swipe/cards?media_type=${mediaType}`);
}

export function submitSwipeResults(results, mediaType = "movie") {
  return request(`/api/swipe/results?media_type=${mediaType}`, {
    method: "POST",
    body: JSON.stringify({ results }),
  });
}

export function logout() { return request("/auth/logout", { method: "POST" }); }

export function syncTrakt() { return request("/api/sync", { method: "POST" }); }

// ── Tournaments ──────────────────────────────────────────────────────

export function getTournaments() {
  return request("/api/tournaments");
}

export function getTournamentGenres(mediaType = "movie") {
  return request(`/api/tournaments/genres?media_type=${mediaType}`);
}

export function getTournamentPoolCount(filterType, filterValue, mediaType = "movie") {
  const params = new URLSearchParams({ media_type: mediaType });
  if (filterType) params.set("filter_type", filterType);
  if (filterValue) params.set("filter_value", filterValue);
  return request(`/api/tournaments/pool-count?${params}`);
}

export function createTournament(name, bracketSize, filterType, filterValue, aiCurated = false, mediaType = "movie") {
  return request("/api/tournaments", {
    method: "POST",
    body: JSON.stringify({
      name,
      bracket_size: bracketSize,
      filter_type: filterType || null,
      filter_value: filterValue || null,
      ai_curated: aiCurated,
      media_type: mediaType,
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

export function regenerateTournament(id) {
  return request(`/api/tournaments/${id}/regenerate`, { method: "POST" });
}

// ── Suggestions ─────────────────────────────────────────────────────

export function getSuggestions(mediaType = "movie") {
  return request(`/api/suggestions?media_type=${mediaType}`);
}

export function regenerateSuggestions(mediaType = "movie") {
  return request(`/api/suggestions/regenerate?media_type=${mediaType}`, { method: "POST" });
}

export function dismissSuggestion(id) {
  return request(`/api/suggestions/${id}/dismiss`, { method: "POST" });
}

export function addToWatchlist(id) {
  return request(`/api/suggestions/${id}/watchlist`, { method: "POST" });
}

export function markSuggestionSeen(id) {
  return request(`/api/suggestions/${id}/seen`, { method: "POST" });
}

// ── Feedback ────────────────────────────────────────────────────────

export async function submitFeedback(title, description, screenshotDataUrl = null) {
  const formData = new FormData();
  formData.append("title", title);
  formData.append("description", description);
  if (screenshotDataUrl) {
    const res = await fetch(screenshotDataUrl);
    const blob = await res.blob();
    formData.append("screenshot", blob, "screenshot.jpg");
  }
  const response = await fetch("/api/feedback", {
    method: "POST",
    credentials: "include",
    body: formData,
  });
  if (response.status === 401) { window.location.href = "/login"; return null; }
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }
  return response.json();
}
