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

  it("calls acceptConsent('1.0') and onAccepted when button is clicked", async () => {
    acceptConsent.mockResolvedValueOnce({});
    const onAccepted = vi.fn();
    render(<ConsentModal onAccepted={onAccepted} />);
    fireEvent.click(screen.getByRole("button", { name: /i accept/i }));
    await waitFor(() => {
      expect(acceptConsent).toHaveBeenCalledWith("1.0");
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
