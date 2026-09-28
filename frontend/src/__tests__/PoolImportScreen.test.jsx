import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import PoolImportScreen from "../components/PoolImportScreen";

vi.mock("../api", () => ({
  getMe: vi.fn(),
  retryPoolImport: vi.fn(),
}));

import { getMe, retryPoolImport } from "../api";

describe("PoolImportScreen", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.useRealTimers());

  it("polls until the import completes, then calls onDone", async () => {
    vi.useFakeTimers();
    getMe
      .mockResolvedValueOnce({ pool_import_status: "importing" })
      .mockResolvedValueOnce({ pool_import_status: "complete" });
    const onDone = vi.fn();
    render(<PoolImportScreen initialStatus="importing" onDone={onDone} />);
    expect(screen.getByText(/importing your library/i)).toBeInTheDocument();

    await act(() => vi.advanceTimersByTimeAsync(3000));
    expect(getMe).toHaveBeenCalledTimes(1);
    expect(onDone).not.toHaveBeenCalled();

    await act(() => vi.advanceTimersByTimeAsync(3000));
    expect(getMe).toHaveBeenCalledTimes(2);
    expect(onDone).toHaveBeenCalled();
  });

  it("keeps polling through a failed status check", async () => {
    vi.useFakeTimers();
    getMe
      .mockRejectedValueOnce(new Error("Network error"))
      .mockResolvedValueOnce({ pool_import_status: "complete" });
    const onDone = vi.fn();
    render(<PoolImportScreen initialStatus="importing" onDone={onDone} />);

    await act(() => vi.advanceTimersByTimeAsync(3000));
    expect(screen.getByText(/importing your library/i)).toBeInTheDocument();

    await act(() => vi.advanceTimersByTimeAsync(3000));
    expect(onDone).toHaveBeenCalled();
  });

  it("offers a retry on failure that restarts the import", async () => {
    retryPoolImport.mockResolvedValueOnce({ pool_import_status: "importing" });
    render(<PoolImportScreen initialStatus="failed" onDone={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: /retry import/i }));

    await waitFor(() => {
      expect(retryPoolImport).toHaveBeenCalledOnce();
      expect(screen.getByText(/importing your library/i)).toBeInTheDocument();
    });
  });

  it("shows the retry error and stays on the failed view", async () => {
    retryPoolImport.mockRejectedValueOnce(new Error("Too many requests"));
    render(<PoolImportScreen initialStatus="failed" onDone={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: /retry import/i }));

    await waitFor(() => {
      expect(screen.getByText("Too many requests")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /retry import/i })).not.toBeDisabled();
    });
  });

  it("continue anyway calls onDone", () => {
    const onDone = vi.fn();
    render(<PoolImportScreen initialStatus="failed" onDone={onDone} />);
    fireEvent.click(screen.getByRole("button", { name: /continue anyway/i }));
    expect(onDone).toHaveBeenCalledOnce();
  });
});
