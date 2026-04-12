import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect } from "vitest";
import Login from "../pages/Login";

describe("Login", () => {
  const renderLogin = () =>
    render(
      <MemoryRouter>
        <Login />
      </MemoryRouter>
    );

  it("renders 'Sign in with Trakt' button", () => {
    renderLogin();
    expect(screen.getByText("Sign in with Trakt")).toBeInTheDocument();
  });

  it("sign in button links to /auth/login", () => {
    renderLogin();
    const link = screen.getByText("Sign in with Trakt").closest("a");
    expect(link).toHaveAttribute("href", "/auth/login");
  });

  it("renders FILMDUEL branding", () => {
    renderLogin();
    expect(screen.getByText("FILMDUEL")).toBeInTheDocument();
  });

  it("renders tagline text", () => {
    renderLogin();
    expect(screen.getByText("Rate films. Rank everything.")).toBeInTheDocument();
  });

  it("renders the logo image", () => {
    renderLogin();
    const logo = screen.getByAltText("FilmDuel");
    expect(logo).toBeInTheDocument();
    expect(logo.tagName).toBe("IMG");
  });
});
