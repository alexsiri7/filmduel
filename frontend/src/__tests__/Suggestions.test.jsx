import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, beforeEach, vi } from "vitest";
import Suggestions from "../pages/Suggestions";
import {
  getSuggestions,
  regenerateSuggestions,
  dismissSuggestion,
  addToWatchlist,
  markSuggestionSeen,
} from "../api";

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => vi.fn() };
});

vi.mock("../api", () => ({
  getSuggestions: vi.fn(),
  regenerateSuggestions: vi.fn(),
  dismissSuggestion: vi.fn(),
  addToWatchlist: vi.fn(),
  markSuggestionSeen: vi.fn(),
}));

function makeSuggestion(overrides = {}) {
  return {
    id: "sugg-1",
    reason: "Because you loved Alien",
    added_to_watchlist_at: null,
    dismissed_at: null,
    movie: {
      title: "The Thing",
      year: 1982,
      poster_url: null,
      imdb_id: null,
      trakt_id: null,
      media_type: "movie",
    },
    ...overrides,
  };
}

function renderSuggestions() {
  return render(
    <MemoryRouter>
      <Suggestions />
    </MemoryRouter>
  );
}

describe("Suggestions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it.each([
    {
      status: "not_enough_films",
      expectedHeading: "Keep dueling!",
      expectedLink: "Start Dueling",
    },
    {
      status: "no_candidates",
      expectedHeading: "Pool expanding...",
      expectedLink: "Swipe Films",
    },
  ])(
    "renders the $status branch",
    async ({ status, expectedHeading, expectedLink }) => {
      getSuggestions.mockResolvedValue({ status, suggestions: [] });

      renderSuggestions();

      await waitFor(() => {
        expect(screen.getByText(expectedHeading)).toBeInTheDocument();
      });
      expect(screen.getByText(expectedLink)).toBeInTheDocument();
    }
  );

  it("renders an error and error message when loading fails", async () => {
    getSuggestions.mockRejectedValue(new Error("LLM unavailable"));

    renderSuggestions();

    await waitFor(() => {
      expect(screen.getByText("Try Again")).toBeInTheDocument();
    });
    expect(screen.getByText("LLM unavailable")).toBeInTheDocument();
  });

  it("renders the ready state with suggestion details and actions", async () => {
    getSuggestions.mockResolvedValue({
      status: "ready",
      suggestions: [makeSuggestion()],
    });

    renderSuggestions();

    await waitFor(() => {
      expect(screen.getByText("The Thing")).toBeInTheDocument();
    });
    expect(screen.getByText("Because you loved Alien")).toBeInTheDocument();
    expect(screen.getByText("Watchlist")).toBeInTheDocument();
    expect(screen.getByText("Seen it")).toBeInTheDocument();
    expect(screen.getByTitle("Dismiss")).toBeInTheDocument();
  });

  it("shows the daily regeneration limit message using the backend's exact wording", async () => {
    getSuggestions.mockResolvedValue({ status: "ready", suggestions: [makeSuggestion()] });
    // Must match backend/routers/suggestions.py's regenerate_suggestions detail string verbatim —
    // Suggestions.jsx keys off `err.message.includes("3 times")`.
    regenerateSuggestions.mockRejectedValueOnce(
      new Error("You can regenerate suggestions up to 3 times per day.")
    );

    renderSuggestions();
    await waitFor(() => expect(screen.getByText("The Thing")).toBeInTheDocument());

    fireEvent.click(screen.getByText("Refresh"));

    await waitFor(() => {
      expect(
        screen.getByText("Daily regeneration limit reached. Try again tomorrow.")
      ).toBeInTheDocument();
    });
  });

  it("shows the raw error message for non-rate-limit regenerate failures", async () => {
    getSuggestions.mockResolvedValue({ status: "ready", suggestions: [makeSuggestion()] });
    regenerateSuggestions.mockRejectedValueOnce(new Error("LLM unavailable"));

    renderSuggestions();
    await waitFor(() => expect(screen.getByText("The Thing")).toBeInTheDocument());

    fireEvent.click(screen.getByText("Refresh"));

    await waitFor(() => {
      expect(screen.getByText("LLM unavailable")).toBeInTheDocument();
    });
  });

  it("dismisses one suggestion while leaving the other visible", async () => {
    const a = makeSuggestion({ id: "a", movie: { ...makeSuggestion().movie, title: "Movie A" } });
    const b = makeSuggestion({ id: "b", movie: { ...makeSuggestion().movie, title: "Movie B" } });
    getSuggestions.mockResolvedValue({ status: "ready", suggestions: [a, b] });
    dismissSuggestion.mockResolvedValue({});

    renderSuggestions();
    await waitFor(() => expect(screen.getByText("Movie A")).toBeInTheDocument());

    fireEvent.click(screen.getAllByTitle("Dismiss")[0]);

    await waitFor(() => expect(screen.queryByText("Movie A")).not.toBeInTheDocument());
    expect(screen.getByText("Movie B")).toBeInTheDocument();
  });

  it("replaces the watchlist button with the On Watchlist chip", async () => {
    getSuggestions.mockResolvedValue({ status: "ready", suggestions: [makeSuggestion()] });
    addToWatchlist.mockResolvedValue({ added_to_watchlist_at: "2026-01-01T00:00:00Z" });

    renderSuggestions();
    await waitFor(() => expect(screen.getByText("Watchlist")).toBeInTheDocument());

    fireEvent.click(screen.getByText("Watchlist"));

    await waitFor(() => expect(screen.getByText("On Watchlist")).toBeInTheDocument());
    expect(screen.queryByText("Watchlist")).not.toBeInTheDocument();
  });

  it("shows the all-caught-up screen when the backend reports all_dismissed", async () => {
    getSuggestions.mockResolvedValue({ status: "all_dismissed", suggestions: [] });

    renderSuggestions();

    await waitFor(() => {
      expect(screen.getByText("All caught up!")).toBeInTheDocument();
    });
    expect(screen.getByText("Regenerate Suggestions")).toBeInTheDocument();
  });

  it.each([
    { action: "dismissing", clickTarget: () => screen.getByTitle("Dismiss") },
    { action: "marking seen", clickTarget: () => screen.getByText("Seen it") },
  ])("shows the all-caught-up screen after $action the last suggestion", async ({ clickTarget }) => {
    getSuggestions.mockResolvedValue({ status: "ready", suggestions: [makeSuggestion()] });
    dismissSuggestion.mockResolvedValue({});
    markSuggestionSeen.mockResolvedValue({});

    renderSuggestions();
    await waitFor(() => expect(screen.getByText("The Thing")).toBeInTheDocument());

    fireEvent.click(clickTarget());

    await waitFor(() => {
      expect(screen.getByText("All caught up!")).toBeInTheDocument();
    });
    expect(screen.getByText("Regenerate Suggestions")).toBeInTheDocument();
  });
});
