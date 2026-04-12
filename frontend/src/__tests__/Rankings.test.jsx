import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, beforeEach, vi } from "vitest";
import Rankings from "../pages/Rankings";

const fakeRankings = {
  rankings: [
    {
      movie: {
        id: 1,
        title: "Parasite",
        year: 2019,
        poster_url: "https://example.com/parasite.jpg",
        genres: ["Drama", "Thriller"],
      },
      elo: 1600,
      battles: 20,
    },
    {
      movie: {
        id: 2,
        title: "Get Out",
        year: 2017,
        poster_url: "https://example.com/getout.jpg",
        genres: ["Horror", "Thriller"],
      },
      elo: 1500,
      battles: 15,
    },
  ],
};

const fakeStats = {
  total_duels: 100,
  total_movies_ranked: 25,
  unseen_count: 50,
};

function setupFetch(overrides = {}) {
  return vi.fn((url) => {
    if (url.includes("/api/rankings") && !url.includes("stats") && !url.includes("export")) {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(overrides.rankings ?? fakeRankings),
      });
    }
    if (url.includes("/api/rankings/stats")) {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(overrides.stats ?? fakeStats),
      });
    }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
  });
}

describe("Rankings", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", setupFetch());
  });

  it("renders rankings with movie titles", async () => {
    render(
      <MemoryRouter>
        <Rankings />
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText("Parasite")).toBeInTheDocument();
      expect(screen.getByText("Get Out")).toBeInTheDocument();
    });
  });

  it("shows rank numbers", async () => {
    render(
      <MemoryRouter>
        <Rankings />
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText("01")).toBeInTheDocument();
      expect(screen.getByText("02")).toBeInTheDocument();
    });
  });

  it("shows ELO scores", async () => {
    render(
      <MemoryRouter>
        <Rankings />
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText("1,600")).toBeInTheDocument();
      expect(screen.getByText("1,500")).toBeInTheDocument();
    });
  });

  it("shows battles count", async () => {
    render(
      <MemoryRouter>
        <Rankings />
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText("20")).toBeInTheDocument();
      expect(screen.getByText("15")).toBeInTheDocument();
    });
  });

  it("shows export button", async () => {
    render(
      <MemoryRouter>
        <Rankings />
      </MemoryRouter>
    );
    await waitFor(() => {
      const exportLink = screen.getByText("Export to Letterboxd");
      expect(exportLink).toBeInTheDocument();
      expect(exportLink.closest("a")).toHaveAttribute(
        "href",
        "/api/rankings/export/csv"
      );
    });
  });

  it("handles empty rankings", async () => {
    vi.stubGlobal(
      "fetch",
      setupFetch({ rankings: { rankings: [] } })
    );
    render(
      <MemoryRouter>
        <Rankings />
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(
        screen.getByText("No rankings yet. Start dueling to build your list!")
      ).toBeInTheDocument();
    });
  });

  it("shows loading state initially", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    render(
      <MemoryRouter>
        <Rankings />
      </MemoryRouter>
    );
    expect(screen.getByText("Loading rankings...")).toBeInTheDocument();
  });

  it("renders genre filter pills", async () => {
    render(
      <MemoryRouter>
        <Rankings />
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText("All")).toBeInTheDocument();
      expect(screen.getByText("Drama")).toBeInTheDocument();
      expect(screen.getByText("Horror")).toBeInTheDocument();
    });
  });

  it("renders the header with 'Your rankings'", async () => {
    render(
      <MemoryRouter>
        <Rankings />
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText("rankings")).toBeInTheDocument();
    });
  });
});
