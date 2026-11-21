import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, beforeEach, vi } from "vitest";
import Settings from "../pages/Settings";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    getMe: vi.fn(),
    updateSettings: vi.fn(() => Promise.resolve()),
    deleteAccount: vi.fn(() => Promise.resolve(null)),
    withdrawConsent: vi.fn(() => Promise.resolve(null)),
  };
});

import { getMe, updateSettings } from "../api";

describe("Settings page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getMe.mockResolvedValue({ use_ai_features: true, trakt_username: "x" });
    updateSettings.mockResolvedValue(null);
  });

  const renderSettings = () =>
    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>
    );

  it("exposes the AI Suggestions and Sync to Trakt toggles", async () => {
    renderSettings();
    await waitFor(() => {
      expect(screen.getByRole("switch", { name: /ai suggestions/i })).toBeInTheDocument();
      expect(screen.getByRole("switch", { name: /sync to trakt/i })).toBeInTheDocument();
    });
  });

  it("exposes Download My Data, Withdraw Consent, Delete My Account and Sign Out", async () => {
    renderSettings();
    await waitFor(() => {
      const link = screen.getByRole("link", { name: /download my data/i });
      expect(link).toHaveAttribute("href", "/api/me/export");
      expect(screen.getByRole("button", { name: /withdraw consent/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /delete my account/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /sign out/i })).toBeInTheDocument();
    });
  });

  it("toggling AI Suggestions calls updateSettings", async () => {
    renderSettings();
    const toggle = await screen.findByRole("switch", { name: /ai suggestions/i });
    toggle.click();
    await waitFor(() => {
      expect(updateSettings).toHaveBeenCalledWith({ use_ai_features: false });
    });
  });
});
