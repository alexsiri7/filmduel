import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import {
  fetchPair,
  submitDuel,
  fetchSwipeCards,
  submitSwipeResults,
  getRankings,
  getMe,
  logout,
  submitFeedback,
} from "../api";

describe("api", () => {
  let originalLocation;

  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    // Save and mock window.location
    originalLocation = window.location;
    delete window.location;
    window.location = { href: "" };
  });

  afterEach(() => {
    window.location = originalLocation;
    vi.restoreAllMocks();
  });

  function mockFetchOk(data, status = 200) {
    fetch.mockResolvedValueOnce({
      ok: true,
      status,
      json: () => Promise.resolve(data),
    });
  }

  function mockFetch401() {
    fetch.mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: () => Promise.resolve({ detail: "Unauthorized" }),
    });
  }

  function mockFetchError(status = 500, detail = "Server error") {
    fetch.mockResolvedValueOnce({
      ok: false,
      status,
      json: () => Promise.resolve({ detail }),
    });
  }

  // fetchPair
  describe("fetchPair", () => {
    it("calls correct endpoint with mode param", async () => {
      mockFetchOk({ movie_a: {}, movie_b: {} });
      await fetchPair("discovery");
      expect(fetch).toHaveBeenCalledWith(
        "/api/movies/pair?mode=discovery",
        expect.objectContaining({
          credentials: "include",
          headers: expect.objectContaining({ "Content-Type": "application/json" }),
        })
      );
    });

    it("includes last_pair_token when provided", async () => {
      mockFetchOk({ movie_a: {}, movie_b: {} });
      await fetchPair("discovery", "abc123");
      expect(fetch).toHaveBeenCalledWith(
        "/api/movies/pair?mode=discovery&last_pair_token=abc123",
        expect.any(Object)
      );
    });
  });

  // submitDuel
  describe("submitDuel", () => {
    it("sends correct body", async () => {
      mockFetchOk({ success: true });
      await submitDuel(1, 2, "a_wins", "discovery");
      expect(fetch).toHaveBeenCalledWith(
        "/api/duels",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            movie_a_id: 1,
            movie_b_id: 2,
            outcome: "a_wins",
            mode: "discovery",
          }),
        })
      );
    });
  });

  // fetchSwipeCards
  describe("fetchSwipeCards", () => {
    it("calls /api/swipe/cards", async () => {
      mockFetchOk([{ id: 1, title: "Test" }]);
      await fetchSwipeCards();
      expect(fetch).toHaveBeenCalledWith(
        "/api/swipe/cards",
        expect.objectContaining({ credentials: "include" })
      );
    });
  });

  // submitSwipeResults
  describe("submitSwipeResults", () => {
    it("sends array of results", async () => {
      const results = [
        { movie_id: 1, seen: true },
        { movie_id: 2, seen: false },
      ];
      mockFetchOk({ seen_count: 1, unseen_count: 1 });
      await submitSwipeResults(results);
      expect(fetch).toHaveBeenCalledWith(
        "/api/swipe/results",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ results }),
        })
      );
    });
  });

  // 401 redirect
  describe("401 handling", () => {
    it("redirects to /login on 401", async () => {
      mockFetch401();
      const result = await getMe();
      expect(result).toBeNull();
      expect(window.location.href).toBe("/login");
    });
  });

  // Error handling
  describe("error handling", () => {
    it("throws on non-OK response", async () => {
      mockFetchError(500, "Internal server error");
      await expect(getRankings()).rejects.toThrow("Internal server error");
    });

    it("throws generic message when error body is not JSON", async () => {
      fetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: () => Promise.reject(new Error("not json")),
      });
      await expect(getRankings()).rejects.toThrow("Request failed");
    });
  });

  // submitFeedback
  describe("submitFeedback", () => {
    it("posts to /api/feedback", async () => {
      mockFetchOk({ id: "abc-123", created_at: "2026-04-13T00:00:00Z" }, 201);
      const result = await submitFeedback("Bug title", "Description here");
      expect(fetch).toHaveBeenCalledWith(
        "/api/feedback",
        expect.objectContaining({ method: "POST", credentials: "include" })
      );
      expect(result.id).toBe("abc-123");
    });

    it("throws on non-ok response", async () => {
      mockFetchError(500, "Server error");
      await expect(submitFeedback("t", "d")).rejects.toThrow("Server error");
    });

    it("redirects to /login on 401", async () => {
      mockFetch401();
      await submitFeedback("t", "d");
      expect(window.location.href).toBe("/login");
    });
  });

  // 204 handling
  describe("204 handling", () => {
    it("returns null on 204 response", async () => {
      fetch.mockResolvedValueOnce({
        ok: true,
        status: 204,
        json: () => Promise.resolve(null),
      });
      const result = await logout();
      expect(result).toBeNull();
    });
  });
});
