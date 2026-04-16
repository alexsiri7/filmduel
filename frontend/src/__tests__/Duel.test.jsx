import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, beforeEach, vi } from "vitest";
import Duel from "../pages/Duel";

const mockNavigate = vi.fn();

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => mockNavigate };
});

const fakePair = {
  movie_a: {
    id: 1,
    title: "Alien",
    year: 1979,
    poster_url: "https://example.com/alien.jpg",
    genres: ["Horror", "Sci-fi"],
  },
  movie_b: {
    id: 2,
    title: "Aliens",
    year: 1986,
    poster_url: "https://example.com/aliens.jpg",
    genres: ["Action", "Sci-fi"],
  },
};

const fakeStats = {
  total_duels: 42,
  total_movies_ranked: 15,
  unseen_count: 100,
};

const fakeDuelResult = {
  movie_a_elo_delta: 12,
  movie_b_elo_delta: -12,
  next_action: "duel",
};

function setupFetch(overrides = {}) {
  return vi.fn((url, opts) => {
    if (url.includes("/api/movies/pair")) {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(overrides.pair ?? fakePair),
      });
    }
    if (url.includes("/api/rankings/stats")) {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(overrides.stats ?? fakeStats),
      });
    }
    if (url === "/api/duels" && opts?.method === "POST") {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(overrides.duelResult ?? fakeDuelResult),
      });
    }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
  });
}

describe("Duel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", setupFetch());
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows loading skeleton initially", () => {
    // Use AbortController so the pending fetch can be cleaned up
    const controller = new AbortController();
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise((_, reject) => {
        controller.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
      }))
    );
    render(
      <MemoryRouter>
        <Duel />
      </MemoryRouter>
    );
    // Skeleton has animate-pulse divs
    const pulseElements = document.querySelectorAll(".animate-pulse");
    expect(pulseElements.length).toBeGreaterThan(0);
    controller.abort();
  });

  it("renders two movie cards when pair loads", async () => {
    render(
      <MemoryRouter>
        <Duel />
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText("Alien")).toBeInTheDocument();
      expect(screen.getByText("Aliens")).toBeInTheDocument();
    });
  });

  it("shows VS badge between cards", async () => {
    render(
      <MemoryRouter>
        <Duel />
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText("VS")).toBeInTheDocument();
    });
  });

  it("shows stats bar with duel count", async () => {
    render(
      <MemoryRouter>
        <Duel />
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText("42")).toBeInTheDocument();
      expect(screen.getByText("15")).toBeInTheDocument();
    });
  });

  it("shows instruction text", async () => {
    render(
      <MemoryRouter>
        <Duel />
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(
        screen.getByText("Tap the film you rate higher")
      ).toBeInTheDocument();
    });
  });

  it("tapping left card submits a_wins", async () => {
    const mockFetch = setupFetch();
    vi.stubGlobal("fetch", mockFetch);

    render(
      <MemoryRouter>
        <Duel />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("Alien")).toBeInTheDocument();
    });

    // Both cards are buttons - click the left one (Alien)
    const buttons = screen.getAllByRole("button");
    const alienButton = buttons.find(
      (b) => b.textContent.includes("Alien") && !b.textContent.includes("Aliens")
    );
    fireEvent.click(alienButton);

    await waitFor(() => {
      const duelCall = mockFetch.mock.calls.find(
        ([url, opts]) => url === "/api/duels" && opts?.method === "POST"
      );
      expect(duelCall).toBeDefined();
      const body = JSON.parse(duelCall[1].body);
      expect(body.outcome).toBe("a_wins");
      expect(body.movie_a_id).toBe(1);
      expect(body.movie_b_id).toBe(2);
    });
  });

  it("tapping right card submits b_wins", async () => {
    const mockFetch = setupFetch();
    vi.stubGlobal("fetch", mockFetch);

    render(
      <MemoryRouter>
        <Duel />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("Aliens")).toBeInTheDocument();
    });

    const buttons = screen.getAllByRole("button");
    const aliensButton = buttons.find((b) => b.textContent.includes("Aliens"));
    fireEvent.click(aliensButton);

    await waitFor(() => {
      const duelCall = mockFetch.mock.calls.find(
        ([url, opts]) => url === "/api/duels" && opts?.method === "POST"
      );
      expect(duelCall).toBeDefined();
      const body = JSON.parse(duelCall[1].body);
      expect(body.outcome).toBe("b_wins");
    });
  });

  it("shows swipe interstitial when next_action is swipe", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const mockFetch = setupFetch({
      duelResult: { movie_a_elo_delta: 12, movie_b_elo_delta: -12, next_action: "swipe" },
    });
    vi.stubGlobal("fetch", mockFetch);

    render(
      <MemoryRouter>
        <Duel />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("Alien")).toBeInTheDocument();
    });

    const buttons = screen.getAllByRole("button");
    const alienButton = buttons.find(
      (b) => b.textContent.includes("Alien") && !b.textContent.includes("Aliens")
    );
    fireEvent.click(alienButton);

    // Advance past the 600ms winner flash timeout
    await vi.advanceTimersByTimeAsync(700);

    await waitFor(() => {
      expect(screen.getByText("Time to discover more films")).toBeInTheDocument();
      expect(screen.getByText("Swipe 10 Films")).toBeInTheDocument();
    });
  });

  it("shows 'show' instruction text in show mode", async () => {
    vi.stubGlobal("fetch", setupFetch());
    render(
      <MemoryRouter>
        <Duel mediaType="show" />
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText("Tap the show you rate higher")).toBeInTheDocument();
    });
  });

  it("shows 'shows ranked' stat label in show mode", async () => {
    vi.stubGlobal("fetch", setupFetch());
    render(
      <MemoryRouter>
        <Duel mediaType="show" />
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText("shows ranked")).toBeInTheDocument();
    });
  });

  it("shows swipe interstitial with show strings when next_action is swipe and mediaType is show", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const mockFetch = setupFetch({
      duelResult: { movie_a_elo_delta: 12, movie_b_elo_delta: -12, next_action: "swipe" },
    });
    vi.stubGlobal("fetch", mockFetch);

    render(
      <MemoryRouter>
        <Duel mediaType="show" />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("Alien")).toBeInTheDocument();
    });

    const buttons = screen.getAllByRole("button");
    const alienButton = buttons.find(
      (b) => b.textContent.includes("Alien") && !b.textContent.includes("Aliens")
    );
    fireEvent.click(alienButton);

    await vi.advanceTimersByTimeAsync(700);

    await waitFor(() => {
      expect(screen.getByText("Time to discover more shows")).toBeInTheDocument();
      expect(screen.getByText("Swipe 10 Shows")).toBeInTheDocument();
    });
  });

  it("prefetches next pair on load", async () => {
    const mockFetch = setupFetch();
    vi.stubGlobal("fetch", mockFetch);

    render(
      <MemoryRouter>
        <Duel />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("Alien")).toBeInTheDocument();
    });

    // loadPair calls fetchPair once, then prefetchNext calls it again
    await waitFor(() => {
      const pairCalls = mockFetch.mock.calls.filter(([url]) =>
        url.includes("/api/movies/pair")
      );
      expect(pairCalls.length).toBeGreaterThanOrEqual(2);
    });
  });
});
