import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import Swipe from "../pages/Swipe";
import { fetchSwipeCards, submitSwipeResults } from "../api";

const mockNavigate = vi.fn();

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => mockNavigate };
});

vi.mock("../api", () => ({
  fetchSwipeCards: vi.fn(),
  submitSwipeResults: vi.fn(),
}));

const cardA = { id: 1, title: "Card A", poster_url: null, genres: [] };
const cardB = { id: 2, title: "Card B", poster_url: null, genres: [] };

function renderSwipe() {
  return render(
    <MemoryRouter>
      <Swipe />
    </MemoryRouter>
  );
}

describe("Swipe", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("submits exactly once with all results after swiping every card", async () => {
    fetchSwipeCards.mockResolvedValue([cardA, cardB]);
    submitSwipeResults.mockResolvedValue({
      seen_count: 1,
      unseen_count: 1,
      next_action: "duel",
    });

    renderSwipe();

    await waitFor(() => expect(screen.getByText("1 / 2")).toBeInTheDocument());

    fireEvent.click(screen.getByText("Seen it"));
    await waitFor(() => expect(screen.getByText("2 / 2")).toBeInTheDocument());

    fireEvent.click(screen.getByText("Never seen it"));

    await waitFor(() => {
      expect(screen.getByText("Swipe Complete")).toBeInTheDocument();
    });

    expect(submitSwipeResults).toHaveBeenCalledTimes(1);
    expect(submitSwipeResults).toHaveBeenCalledWith(
      [
        { movie_id: 1, seen: true },
        { movie_id: 2, seen: false },
      ],
      "movie"
    );

    expect(screen.getByText("You've seen 1 of these films")).toBeInTheDocument();
    expect(screen.getByText("Start Dueling")).toBeInTheDocument();
    expect(screen.getByText("Swipe More")).toBeInTheDocument();
  });

  it("auto-continues into a new round when next_action is swipe", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fetchSwipeCards.mockResolvedValue([cardA, cardB]);
    submitSwipeResults.mockResolvedValue({
      seen_count: 0,
      unseen_count: 2,
      next_action: "swipe",
    });

    renderSwipe();

    await waitFor(() => expect(screen.getByText("1 / 2")).toBeInTheDocument());

    fireEvent.click(screen.getByText("Seen it"));
    await waitFor(() => expect(screen.getByText("2 / 2")).toBeInTheDocument());

    fireEvent.click(screen.getByText("Seen it"));

    await waitFor(() => {
      expect(screen.getByText("Round Complete")).toBeInTheDocument();
    });
    expect(screen.getByText("Loading more films...")).toBeInTheDocument();
    expect(screen.queryByText("Start Dueling")).not.toBeInTheDocument();

    // No intermediate call-count assertion here: with shouldAdvanceTime: true the
    // fake clock also tracks real elapsed time, so on a slow/loaded runner the
    // 1500ms timer could already have fired by this point.
    await vi.advanceTimersByTimeAsync(1500);

    await waitFor(() => expect(fetchSwipeCards).toHaveBeenCalledTimes(2));
  });

  it("does not strand the user when submission fails", async () => {
    fetchSwipeCards.mockResolvedValue([cardA, cardB]);
    submitSwipeResults.mockRejectedValue(new Error("boom"));

    renderSwipe();

    await waitFor(() => expect(screen.getByText("1 / 2")).toBeInTheDocument());

    fireEvent.click(screen.getByText("Seen it"));
    await waitFor(() => expect(screen.getByText("2 / 2")).toBeInTheDocument());

    fireEvent.click(screen.getByText("Never seen it"));

    await waitFor(() => {
      expect(submitSwipeResults).toHaveBeenCalledTimes(1);
    });

    // The swipe buttons are re-enabled after the failed submit (`.finally`).
    await waitFor(() => {
      expect(screen.getByText("Seen it").closest("button")).not.toBeDisabled();
      expect(screen.getByText("Never seen it").closest("button")).not.toBeDisabled();
    });

    // Known gap: Swipe.jsx's error screen only renders when `!cards.length`,
    // but cards are still populated after the last swipe, so the "boom"
    // error is never shown to the user. Pinning current behavior here —
    // flagged separately as a silent-failure UX bug, not filed as a bd
    // issue (bd's Dolt database isn't initialized in this worktree).
    expect(screen.queryByText("boom")).not.toBeInTheDocument();
  });

  describe("initial load", () => {
    it("shows an empty-pool message and navigates home", async () => {
      fetchSwipeCards.mockResolvedValue([]);

      renderSwipe();

      await waitFor(() => {
        expect(
          screen.getByText(/No unknown films left to swipe/)
        ).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText("Back to Duels"));
      expect(mockNavigate).toHaveBeenCalledWith("/");
    });

    it("shows the error and retries on failure", async () => {
      fetchSwipeCards.mockRejectedValueOnce(new Error("network down"));
      fetchSwipeCards.mockResolvedValueOnce([cardA, cardB]);

      renderSwipe();

      await waitFor(() => {
        expect(screen.getByText("network down")).toBeInTheDocument();
      });
      expect(screen.getByText("Try Again")).toBeInTheDocument();

      fireEvent.click(screen.getByText("Try Again"));

      await waitFor(() => expect(fetchSwipeCards).toHaveBeenCalledTimes(2));
      await waitFor(() => expect(screen.getByText("1 / 2")).toBeInTheDocument());
    });
  });
});
