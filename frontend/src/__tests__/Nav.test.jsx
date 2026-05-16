import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, beforeEach, vi } from "vitest";
import Nav from "../components/Nav";

// ── Sync to Trakt toggle tests (use vi.mock to control api module) ─────────

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    getMe: vi.fn(),
    updateSettings: vi.fn(() => Promise.resolve()),
  };
});

import { getMe, updateSettings } from "../api";


describe("Nav — Sync to Trakt toggle", () => {
  const renderNav = () =>
    render(
      <MemoryRouter>
        <Nav />
      </MemoryRouter>
    );

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders toggle in OFF state when user has sync disabled", async () => {
    getMe.mockResolvedValueOnce({ sync_ratings_to_trakt: false });
    renderNav();
    await waitFor(() => {
      const toggle = screen.getByRole("switch");
      expect(toggle).toHaveAttribute("aria-checked", "false");
    });
  });

  it("renders toggle in ON state when user has sync enabled", async () => {
    getMe.mockResolvedValueOnce({ sync_ratings_to_trakt: true });
    renderNav();
    await waitFor(() => {
      const toggle = screen.getByRole("switch");
      expect(toggle).toHaveAttribute("aria-checked", "true");
    });
  });

  it("toggles ON and calls updateSettings when clicked while OFF", async () => {
    getMe.mockResolvedValueOnce({ sync_ratings_to_trakt: false });
    renderNav();
    await waitFor(() => screen.getByRole("switch"));
    fireEvent.click(screen.getByRole("switch"));
    await waitFor(() => {
      expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true");
      expect(updateSettings).toHaveBeenCalledWith({ sync_ratings_to_trakt: true });
    });
  });

  it("toggles OFF and calls updateSettings when clicked while ON", async () => {
    getMe.mockResolvedValueOnce({ sync_ratings_to_trakt: true });
    renderNav();
    await waitFor(() => screen.getByRole("switch"));
    fireEvent.click(screen.getByRole("switch"));
    await waitFor(() => {
      expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false");
      expect(updateSettings).toHaveBeenCalledWith({ sync_ratings_to_trakt: false });
    });
  });

  it("defaults to OFF when getMe returns null", async () => {
    getMe.mockResolvedValueOnce(null);
    renderNav();
    await waitFor(() => {
      expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false");
    });
  });

  it("rolls back toggle state when updateSettings fails", async () => {
    getMe.mockResolvedValueOnce({ sync_ratings_to_trakt: false });
    updateSettings.mockRejectedValueOnce(new Error("Network error"));
    renderNav();
    await waitFor(() => screen.getByRole("switch"));
    fireEvent.click(screen.getByRole("switch"));
    // After failure, toggle should roll back to OFF
    await waitFor(() => {
      expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false");
    });
  });
});

describe("Nav", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // The api module is mocked above. Set safe defaults for the existing Nav tests.
    getMe.mockResolvedValue(null);
    updateSettings.mockResolvedValue(null);
    // logout is also mocked; stub fetch so the Sign Out test can verify the call
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({ ok: true, status: 204, json: () => Promise.resolve(null) })
      )
    );
  });

  const renderNav = (path = "/") =>
    render(
      <MemoryRouter initialEntries={[path]}>
        <Nav />
      </MemoryRouter>
    );

  it("renders FILMDUEL logo text", () => {
    renderNav();
    expect(screen.getByText("FILMDUEL")).toBeInTheDocument();
  });

  it("renders logo image", () => {
    renderNav();
    const logo = screen.getByAltText("FilmDuel");
    expect(logo).toBeInTheDocument();
  });

  it("shows nav items: Current Duel, Swipe, Rankings", () => {
    renderNav();
    expect(screen.getByText("Current Duel")).toBeInTheDocument();
    expect(screen.getByText("Swipe")).toBeInTheDocument();
    expect(screen.getByText("Rankings")).toBeInTheDocument();
  });

  it("active nav item (Current Duel) has accent bg styling on /", () => {
    renderNav("/");
    const duelLink = screen.getByText("Current Duel").closest("a");
    expect(duelLink.className).toContain("bg-primary-container");
  });

  it("active nav item (Rankings) has accent styling on /rankings", () => {
    renderNav("/rankings");
    const rankingsLink = screen.getByText("Rankings").closest("a");
    expect(rankingsLink.className).toContain("bg-primary-container");
  });

  it("inactive nav item does NOT have accent bg", () => {
    renderNav("/");
    const swipeLink = screen.getByText("Swipe").closest("a");
    expect(swipeLink.className).not.toContain("bg-primary-container");
  });

  it("Report Issue is a button (not a link)", () => {
    renderNav();
    const reportButton = screen.getByText("Report Issue");
    expect(reportButton.tagName).toBe("BUTTON");
  });

  it("clicking Report Issue opens feedback modal", () => {
    renderNav();
    fireEvent.click(screen.getByText("Report Issue"));
    expect(screen.getByPlaceholderText("Brief title of the issue")).toBeInTheDocument();
  });

  it("renders Sign Out button", () => {
    renderNav();
    expect(screen.getByText("Sign Out")).toBeInTheDocument();
  });

  it("Sign Out button calls logout API", async () => {
    vi.stubGlobal("location", { href: "" });

    renderNav();
    fireEvent.click(screen.getByText("Sign Out"));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "/auth/logout",
        expect.objectContaining({ method: "POST" })
      );
    });

    vi.unstubAllGlobals();
  });

  it("renders START DUEL button", () => {
    renderNav();
    expect(screen.getByText("START DUEL")).toBeInTheDocument();
  });

  it("renders The Noir Projectionist subtitle", () => {
    renderNav();
    expect(screen.getByText("The Noir Projectionist")).toBeInTheDocument();
  });
});
