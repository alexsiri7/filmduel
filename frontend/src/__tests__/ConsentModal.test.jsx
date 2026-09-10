import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import ConsentModal from "../components/ConsentModal";

vi.mock("../api", () => ({
  acceptConsent: vi.fn(),
}));

import { acceptConsent } from "../api";

describe("ConsentModal", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders consent content and accept button", () => {
    render(<ConsentModal onAccepted={vi.fn()} />);
    expect(screen.getByText(/before you continue/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /i accept/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /privacy policy/i })).toBeInTheDocument();
  });

  // Counterpart of backend/tests/test_llm_disclosure.py: both sides pin the same
  // fields, so widening either one without the other fails a test.
  it("itemizes every category of data sent to the AI gateway", () => {
    render(<ConsentModal onAccepted={vi.fn()} />);

    const suggestions = screen.getByText(/AI Watch Suggestions/i).closest("li");
    expect(suggestions).toHaveTextContent(/top 10 and bottom 5 ranked films/i);
    expect(suggestions).toHaveTextContent(/title, year, genres, preference tier/i);
    expect(suggestions).toHaveTextContent(/per-genre affinities/i);
    expect(suggestions).toHaveTextContent(/total ranked count/i);
    expect(suggestions).toHaveTextContent(/up to 50 films/i);
    expect(suggestions).toHaveTextContent(/title, year, genres, community rating/i);
    expect(suggestions).toHaveTextContent(/Requesty\.ai/i);

    const tournaments = screen.getByText(/AI-Curated Tournaments/i).closest("li");
    expect(tournaments).toHaveTextContent(
      /title, year, genres, preference tier, duel count/i
    );
    expect(tournaments).toHaveTextContent(/theme or filter you enter/i);
    expect(tournaments).toHaveTextContent(/Requesty\.ai/i);

    expect(
      screen.getByText(/Raw ELO scores and account identifiers are never transmitted/i)
    ).toBeInTheDocument();
  });

  it("calls acceptConsent('2.1') and onAccepted when button is clicked", async () => {
    acceptConsent.mockResolvedValueOnce({});
    const onAccepted = vi.fn();
    render(<ConsentModal onAccepted={onAccepted} />);
    fireEvent.click(screen.getByRole("button", { name: /i accept/i }));
    await waitFor(() => {
      expect(acceptConsent).toHaveBeenCalledWith("2.1");
      expect(onAccepted).toHaveBeenCalledOnce();
    });
  });

  it("shows Saving... and disables button while loading", async () => {
    let resolve;
    acceptConsent.mockReturnValueOnce(new Promise((r) => { resolve = r; }));
    render(<ConsentModal onAccepted={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /i accept/i }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /saving/i })).toBeDisabled();
    });
    resolve({});
  });

  it("re-enables button and shows error message when acceptConsent throws", async () => {
    acceptConsent.mockRejectedValueOnce(new Error("Network error"));
    render(<ConsentModal onAccepted={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /i accept/i }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /i accept/i })).not.toBeDisabled();
      expect(screen.getByText("Network error")).toBeInTheDocument();
    });
  });

  it("clears error on retry", async () => {
    acceptConsent
      .mockRejectedValueOnce(new Error("Network error"))
      .mockResolvedValueOnce({});
    const onAccepted = vi.fn();
    render(<ConsentModal onAccepted={onAccepted} />);
    fireEvent.click(screen.getByRole("button", { name: /i accept/i }));
    await waitFor(() => {
      expect(screen.getByText("Network error")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /i accept/i }));
    await waitFor(() => {
      expect(screen.queryByText("Network error")).not.toBeInTheDocument();
      expect(onAccepted).toHaveBeenCalledOnce();
    });
  });
});
