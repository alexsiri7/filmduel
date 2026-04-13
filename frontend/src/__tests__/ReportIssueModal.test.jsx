import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import ReportIssueModal from "../components/ReportIssueModal";

vi.mock("../api", () => ({
  submitFeedback: vi.fn(),
}));

import { submitFeedback } from "../api";

describe("ReportIssueModal", () => {
  const onClose = vi.fn();

  beforeEach(() => {
    onClose.mockReset();
    submitFeedback.mockReset();
  });

  const renderModal = () => render(<ReportIssueModal onClose={onClose} />);

  const fillForm = () => {
    fireEvent.change(screen.getByPlaceholderText("Brief title of the issue"), {
      target: { value: "Bug" },
    });
    fireEvent.change(screen.getByPlaceholderText("Describe the issue or suggestion..."), {
      target: { value: "Details" },
    });
  };

  it("renders title and description inputs", () => {
    renderModal();
    expect(screen.getByPlaceholderText("Brief title of the issue")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Describe the issue or suggestion...")).toBeInTheDocument();
  });

  it("submit button is disabled when fields are empty", () => {
    renderModal();
    expect(screen.getByText("Submit")).toBeDisabled();
  });

  it("submit button is enabled when both fields have text", () => {
    renderModal();
    fireEvent.change(screen.getByPlaceholderText("Brief title of the issue"), {
      target: { value: "Bug title" },
    });
    fireEvent.change(screen.getByPlaceholderText("Describe the issue or suggestion..."), {
      target: { value: "Some description" },
    });
    expect(screen.getByText("Submit")).not.toBeDisabled();
  });

  it("shows success message and calls onClose after 1500ms on submit", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    submitFeedback.mockResolvedValueOnce({ id: "abc", created_at: "2026-04-13" });
    renderModal();
    fillForm();
    fireEvent.click(screen.getByText("Submit"));
    await waitFor(() => expect(screen.getByText("Thank you for your feedback!")).toBeInTheDocument());
    act(() => vi.advanceTimersByTime(1500));
    expect(onClose).toHaveBeenCalledOnce();
    vi.useRealTimers();
  });

  it("shows error message when submitFeedback rejects", async () => {
    submitFeedback.mockRejectedValueOnce(new Error("Screenshot too large (max 5 MB)"));
    renderModal();
    fillForm();
    fireEvent.click(screen.getByText("Submit"));
    await waitFor(() =>
      expect(screen.getByText("Screenshot too large (max 5 MB)")).toBeInTheDocument()
    );
    expect(onClose).not.toHaveBeenCalled();
  });

  it("does not show success when submitFeedback returns null (401 redirect)", async () => {
    submitFeedback.mockResolvedValueOnce(null);
    renderModal();
    fillForm();
    fireEvent.click(screen.getByText("Submit"));
    await act(async () => {
      await Promise.resolve(); // flush microtasks
    });
    expect(screen.queryByText("Thank you for your feedback!")).not.toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("calls onClose when Cancel is clicked", () => {
    renderModal();
    fireEvent.click(screen.getByText("Cancel"));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
