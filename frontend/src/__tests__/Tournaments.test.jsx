import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import Tournaments from "../pages/Tournaments";

function setupFetch(poolCount) {
  return vi.fn((url) => {
    if (url.includes("/api/tournaments/pool-count")) {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(poolCount),
      });
    }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) });
  });
}

async function openCreateForm(poolCount) {
  vi.stubGlobal("fetch", setupFetch(poolCount));
  render(
    <MemoryRouter>
      <Tournaments />
    </MemoryRouter>
  );
  fireEvent.click(await screen.findByRole("button", { name: /create tournament/i }));
  return waitFor(() => screen.getByRole("button", { name: "8" }));
}

describe("Tournaments create form", () => {
  it("disables bracket sizes the ranked pool cannot half-fill", async () => {
    await openCreateForm({ count: 5, max_bracket_size: 8 });

    expect(screen.getByRole("button", { name: "8" })).not.toBeDisabled();
    for (const size of ["16", "32", "64"]) {
      expect(screen.getByRole("button", { name: size })).toBeDisabled();
    }
  });

  it("clamps the default selection down to the largest offerable bracket", async () => {
    await openCreateForm({ count: 5, max_bracket_size: 8 });

    // The default is 16; clamped to 8, five films leave three byes.
    await waitFor(() =>
      expect(document.body.textContent).toContain("5 films + 3 byes")
    );
  });

  it("leaves every bracket size enabled when the pool count fails to load", async () => {
    await openCreateForm({ count: 5 });

    for (const size of ["8", "16", "32", "64"]) {
      expect(screen.getByRole("button", { name: size })).not.toBeDisabled();
    }
  });
});
