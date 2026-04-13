import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, beforeEach, vi } from "vitest";
import Nav from "../components/Nav";

describe("Nav", () => {
  beforeEach(() => {
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

  it("active nav item (Current Duel) has amber bg styling on /", () => {
    renderNav("/");
    const duelLink = screen.getByText("Current Duel").closest("a");
    expect(duelLink.className).toContain("bg-[#E8A020]");
  });

  it("active nav item (Rankings) has amber styling on /rankings", () => {
    renderNav("/rankings");
    const rankingsLink = screen.getByText("Rankings").closest("a");
    expect(rankingsLink.className).toContain("bg-[#E8A020]");
  });

  it("inactive nav item does NOT have amber bg", () => {
    renderNav("/");
    const swipeLink = screen.getByText("Swipe").closest("a");
    expect(swipeLink.className).not.toContain("bg-[#E8A020]");
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
    // Mock window.location for redirect
    const originalLocation = window.location;
    delete window.location;
    window.location = { href: "" };

    renderNav();
    fireEvent.click(screen.getByText("Sign Out"));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "/auth/logout",
        expect.objectContaining({ method: "POST" })
      );
    });

    window.location = originalLocation;
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
