import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect } from "vitest";
import App from "../App";

describe("App", () => {
  it("renders navigation", () => {
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>
    );
    expect(screen.getByText("FilmDuel")).toBeInTheDocument();
  });

  it("renders login page at /login", () => {
    render(
      <MemoryRouter initialEntries={["/login"]}>
        <App />
      </MemoryRouter>
    );
    expect(screen.getByText(/sign in with trakt/i)).toBeInTheDocument();
  });

  it("renders duel page at /", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    );
    // Duel page should be the default route
    expect(document.querySelector("main")).toBeInTheDocument();
  });
});
