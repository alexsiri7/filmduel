import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import MovieCard from "../components/MovieCard";

const baseMovie = {
  id: 1,
  title: "Blade Runner",
  year: 1982,
  poster_url: "https://example.com/poster.jpg",
  genres: ["Sci-fi", "Drama", "Thriller"],
  elo: 1450,
  battles: 12,
};

describe("MovieCard", () => {
  it("renders movie title", () => {
    render(<MovieCard movie={baseMovie} />);
    expect(screen.getByText("Blade Runner")).toBeInTheDocument();
  });

  it("renders movie year", () => {
    render(<MovieCard movie={baseMovie} />);
    expect(screen.getByText("1982")).toBeInTheDocument();
  });

  it("renders poster image with correct alt text", () => {
    render(<MovieCard movie={baseMovie} />);
    const img = screen.getByAltText("Blade Runner poster");
    expect(img).toBeInTheDocument();
    expect(img).toHaveAttribute("src", "https://example.com/poster.jpg");
  });

  it("shows genre badges (max 2)", () => {
    render(<MovieCard movie={baseMovie} />);
    expect(screen.getByText("Sci-fi")).toBeInTheDocument();
    expect(screen.getByText("Drama")).toBeInTheDocument();
    expect(screen.queryByText("Thriller")).not.toBeInTheDocument();
  });

  it("handles missing poster gracefully with placeholder", () => {
    const movie = { ...baseMovie, poster_url: null };
    render(<MovieCard movie={movie} />);
    const img = screen.getByAltText("Blade Runner poster");
    expect(img).toHaveAttribute(
      "src",
      "https://via.placeholder.com/300x450?text=No+Poster"
    );
  });

  it("calls onClick when clickable=true", () => {
    const handleClick = vi.fn();
    render(<MovieCard movie={baseMovie} onClick={handleClick} clickable={true} />);
    const card = screen.getByRole("button");
    fireEvent.click(card);
    expect(handleClick).toHaveBeenCalledOnce();
  });

  it("has role=button when clickable", () => {
    render(<MovieCard movie={baseMovie} onClick={() => {}} clickable={true} />);
    expect(screen.getByRole("button")).toBeInTheDocument();
  });

  it("does not call onClick when clickable=false", () => {
    const handleClick = vi.fn();
    render(<MovieCard movie={baseMovie} onClick={handleClick} clickable={false} />);
    // No button role when not clickable
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows ELO delta when provided (positive)", () => {
    render(<MovieCard movie={baseMovie} delta={15} />);
    expect(screen.getByText("+15")).toBeInTheDocument();
  });

  it("shows ELO delta when provided (negative)", () => {
    render(<MovieCard movie={baseMovie} delta={-10} />);
    expect(screen.getByText("-10")).toBeInTheDocument();
  });

  it("does not show ELO delta when not provided", () => {
    render(<MovieCard movie={baseMovie} />);
    expect(screen.queryByText(/[+-]\d+/)).not.toBeInTheDocument();
  });

  it("handles keyboard Enter to trigger onClick", () => {
    const handleClick = vi.fn();
    render(<MovieCard movie={baseMovie} onClick={handleClick} clickable={true} />);
    const card = screen.getByRole("button");
    fireEvent.keyDown(card, { key: "Enter" });
    expect(handleClick).toHaveBeenCalledOnce();
  });

  it("handles no genres gracefully", () => {
    const movie = { ...baseMovie, genres: [] };
    render(<MovieCard movie={movie} />);
    expect(screen.getByText("Blade Runner")).toBeInTheDocument();
  });
});
