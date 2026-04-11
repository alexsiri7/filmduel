/**
 * Fetch wrapper for the FilmDuel API.
 * All requests include credentials (cookies) for auth.
 */

const BASE = "/api";

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
    ...options,
  });

  if (res.status === 401) {
    window.location.href = "/login";
    return null;
  }

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(error.detail || `HTTP ${res.status}`);
  }

  if (res.status === 204) return null;
  return res.json();
}

export function getMe() {
  return request("/auth/me");
}

export function fetchPair(mode = "discovery") {
  return request(`/movies/pair?mode=${encodeURIComponent(mode)}`);
}

// Legacy alias
export function getMoviePair() {
  return fetchPair("discovery");
}

export function submitDuel(movieAId, movieBId, outcome, mode = "discovery") {
  return request("/duels", {
    method: "POST",
    body: JSON.stringify({
      movie_a_id: movieAId,
      movie_b_id: movieBId,
      outcome,
      mode,
    }),
  });
}

export function fetchStats() {
  return request("/rankings/stats");
}

// Legacy alias
export function getStats() {
  return fetchStats();
}

export function getRankings(limit = 50, offset = 0) {
  return request(`/rankings?limit=${limit}&offset=${offset}`);
}

export function logout() {
  return request("/auth/logout", { method: "POST" });
}
