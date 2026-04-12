import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import SwipeCard from "../components/SwipeCard";

const baseMovie = {
  id: 1,
  title: "The Matrix",
  year: 1999,
  poster_url: "https://example.com/matrix.jpg",
  genres: ["Sci-fi", "Action"],
  community_rating: 87,
};

describe("SwipeCard", () => {
  it("renders movie poster with correct alt text", () => {
    render(<SwipeCard movie={baseMovie} onSwipe={() => {}} />);
    const img = screen.getByAltText("The Matrix poster");
    expect(img).toBeInTheDocument();
    expect(img).toHaveAttribute("src", "https://example.com/matrix.jpg");
  });

  it("renders movie title", () => {
    render(<SwipeCard movie={baseMovie} onSwipe={() => {}} />);
    expect(screen.getByText("The Matrix")).toBeInTheDocument();
  });

  it("renders movie year", () => {
    render(<SwipeCard movie={baseMovie} onSwipe={() => {}} />);
    expect(screen.getByText("1999")).toBeInTheDocument();
  });

  it("renders genre badges", () => {
    render(<SwipeCard movie={baseMovie} onSwipe={() => {}} />);
    expect(screen.getByText("Sci-fi")).toBeInTheDocument();
    expect(screen.getByText("Action")).toBeInTheDocument();
  });

  it("renders community rating badge", () => {
    render(<SwipeCard movie={baseMovie} onSwipe={() => {}} />);
    expect(screen.getByText("87")).toBeInTheDocument();
  });

  it("shows SEEN label element (initially hidden via opacity)", () => {
    render(<SwipeCard movie={baseMovie} onSwipe={() => {}} />);
    expect(screen.getByText("SEEN")).toBeInTheDocument();
  });

  it("shows NOPE label element (initially hidden via opacity)", () => {
    render(<SwipeCard movie={baseMovie} onSwipe={() => {}} />);
    expect(screen.getByText("NOPE")).toBeInTheDocument();
  });

  it("calls onSwipe(true) on right drag past threshold", () => {
    vi.useFakeTimers();
    const onSwipe = vi.fn();
    render(<SwipeCard movie={baseMovie} onSwipe={onSwipe} />);

    const card = screen.getByText("The Matrix").closest("[class*='select-none']");

    fireEvent.mouseDown(card, { clientX: 0 });
    fireEvent.mouseMove(card, { clientX: 100 }); // past 80px threshold
    fireEvent.mouseUp(card);

    vi.advanceTimersByTime(400);
    expect(onSwipe).toHaveBeenCalledWith(true);
    vi.useRealTimers();
  });

  it("calls onSwipe(false) on left drag past threshold", () => {
    vi.useFakeTimers();
    const onSwipe = vi.fn();
    render(<SwipeCard movie={baseMovie} onSwipe={onSwipe} />);

    const card = screen.getByText("The Matrix").closest("[class*='select-none']");

    fireEvent.mouseDown(card, { clientX: 200 });
    fireEvent.mouseMove(card, { clientX: 50 }); // -150px, past threshold
    fireEvent.mouseUp(card);

    vi.advanceTimersByTime(400);
    expect(onSwipe).toHaveBeenCalledWith(false);
    vi.useRealTimers();
  });

  it("snaps back when drag does not reach threshold", () => {
    const onSwipe = vi.fn();
    render(<SwipeCard movie={baseMovie} onSwipe={onSwipe} />);

    const card = screen.getByText("The Matrix").closest("[class*='select-none']");

    fireEvent.mouseDown(card, { clientX: 0 });
    fireEvent.mouseMove(card, { clientX: 30 }); // below 80px threshold
    fireEvent.mouseUp(card);

    expect(onSwipe).not.toHaveBeenCalled();
  });

  it("handles missing poster with placeholder", () => {
    const movie = { ...baseMovie, poster_url: null };
    render(<SwipeCard movie={movie} onSwipe={() => {}} />);
    const img = screen.getByAltText("The Matrix poster");
    expect(img).toHaveAttribute(
      "src",
      "https://via.placeholder.com/300x450?text=No+Poster"
    );
  });
});
