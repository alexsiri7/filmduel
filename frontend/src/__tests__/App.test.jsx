import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, beforeEach, vi } from "vitest";
import App from "../App";

describe("App", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
      )
    );
  });

  it("renders FILMDUEL branding in nav for authenticated route", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    );
    expect(screen.getByText("FILMDUEL")).toBeInTheDocument();
  });

  it("renders navigation items for authenticated layout", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    );
    expect(screen.getByText("Current Duel")).toBeInTheDocument();
    expect(screen.getAllByText("Swipe").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Rankings").length).toBeGreaterThanOrEqual(1);
  });

  it("renders login page at /login without nav", () => {
    render(
      <MemoryRouter initialEntries={["/login"]}>
        <App />
      </MemoryRouter>
    );
    const buttons = screen.getAllByText(/sign in with trakt/i);
    expect(buttons.length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText("Current Duel")).not.toBeInTheDocument();
  });

  it("shows loading state while checking auth", () => {
    // fetch never resolves
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    );
    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("redirects to /login when unauthenticated", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve({ ok: false, status: 401 }))
    );
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    );
    await waitFor(() => {
      const buttons = screen.getAllByText(/sign in with trakt/i);
      expect(buttons.length).toBeGreaterThanOrEqual(1);
    });
  });

  it("renders mobile bottom nav with Duel, Swipe, Rankings", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    );
    expect(screen.getByText("Duel")).toBeInTheDocument();
    // "Swipe" appears in both desktop and mobile nav
    const swipeLinks = screen.getAllByText("Swipe");
    expect(swipeLinks.length).toBeGreaterThanOrEqual(1);
  });

  it("routes to /rankings correctly", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url) => {
        if (url === "/api/me") {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
        }
        if (url.includes("/api/rankings") && !url.includes("stats")) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ rankings: [] }),
          });
        }
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({}),
        });
      })
    );
    render(
      <MemoryRouter initialEntries={["/rankings"]}>
        <App />
      </MemoryRouter>
    );
    // Auth check triggers, then rankings page loads with "Your rankings" header
    await waitFor(() => {
      expect(screen.getByText("No rankings yet. Start dueling to build your list!")).toBeInTheDocument();
    });
  });
});
