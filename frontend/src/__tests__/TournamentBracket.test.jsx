import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import TournamentBracket from "../pages/TournamentBracket";

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => vi.fn(), useParams: () => ({ id: "1" }) };
});

const fakeTournament = {
  id: 1,
  name: "Test Tournament",
  bracket_size: 8,
  status: "in_progress",
  current_round: 1,
  total_rounds: 3,
  matches: [],
};

function setupFetch(tournament = fakeTournament) {
  return vi.fn((url) => {
    if (url.includes("/api/tournaments/1")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(tournament) });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  });
}

describe("TournamentBracket", () => {
  it("renders film label by default", async () => {
    vi.stubGlobal("fetch", setupFetch());
    render(
      <MemoryRouter>
        <TournamentBracket />
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText(/8 films/i)).toBeInTheDocument();
    });
  });

  it("renders show label when mediaType is show", async () => {
    vi.stubGlobal("fetch", setupFetch());
    render(
      <MemoryRouter>
        <TournamentBracket mediaType="show" />
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText(/8 shows/i)).toBeInTheDocument();
    });
  });
});
