import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import ReportIssueModal from "../components/ReportIssueModal";

vi.mock("../api", () => ({
  submitFeedback: vi.fn(),
}));

vi.mock("../components/ScreenshotEditor", () => ({
  default: ({ imageDataUrl, onSave }) => (
    <div>
      <span data-testid="editor-input">{imageDataUrl}</span>
      <button onClick={() => onSave("data:image/jpeg;base64,EDITED")}>mock-done</button>
    </div>
  ),
}));

import { submitFeedback } from "../api";

describe("ReportIssueModal", () => {
  const onClose = vi.fn();

  beforeEach(() => {
    onClose.mockReset();
    submitFeedback.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  const renderModal = () => render(<ReportIssueModal onClose={onClose} />);

  // Returns the data URL FileReader produces for this file, so a second attach can
  // be awaited on the new value rather than on a preview the first attach left behind.
  const attachFile = async (container, name) => {
    const dataUrl = `data:image/png;base64,${btoa(name)}`;
    const input = container.querySelector('input[type="file"]');
    fireEvent.change(input, {
      target: { files: [new File([name], name, { type: "image/png" })] },
    });
    await waitFor(() =>
      expect(screen.getByAltText("Screenshot preview")).toHaveAttribute("src", dataUrl)
    );
    return dataUrl;
  };

  const includeScreenshot = () =>
    fireEvent.click(screen.getByRole("checkbox", { name: /include screenshot/i }));

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

  it("screenshot opt-in checkbox defaults to unchecked (OFF by default)", () => {
    renderModal();
    const checkbox = screen.getByRole("checkbox", { name: /include screenshot/i });
    expect(checkbox).not.toBeChecked();
  });

  it("submits null screenshot when checkbox is unchecked", async () => {
    submitFeedback.mockResolvedValueOnce({ id: "abc", created_at: "2026-05-16" });
    renderModal();
    fillForm();
    fireEvent.click(screen.getByText("Submit"));
    await waitFor(() => expect(submitFeedback).toHaveBeenCalled());
    // Third argument (screenshot) must be null when checkbox is unchecked
    expect(submitFeedback).toHaveBeenCalledWith("Bug", "Details", null);
  });

  it("submits the edited screenshot, not the file that was read from disk", async () => {
    submitFeedback.mockResolvedValueOnce({ id: "abc", created_at: "2026-09-10" });
    const { container } = renderModal();
    includeScreenshot();
    const original = await attachFile(container, "shot.png");

    fireEvent.click(screen.getByText("Edit Screenshot"));
    expect(screen.getByTestId("editor-input")).toHaveTextContent(original);
    fireEvent.click(screen.getByText("mock-done"));

    fillForm();
    fireEvent.click(screen.getByText("Submit"));

    await waitFor(() => expect(submitFeedback).toHaveBeenCalled());
    expect(submitFeedback).toHaveBeenCalledWith("Bug", "Details", "data:image/jpeg;base64,EDITED");
  });

  it("discards a previous edit when a different file is chosen", async () => {
    submitFeedback.mockResolvedValueOnce({ id: "abc", created_at: "2026-09-10" });
    const { container } = renderModal();
    includeScreenshot();
    await attachFile(container, "first.png");

    fireEvent.click(screen.getByText("Edit Screenshot"));
    fireEvent.click(screen.getByText("mock-done"));
    const second = await attachFile(container, "second.png");

    fillForm();
    fireEvent.click(screen.getByText("Submit"));

    await waitFor(() => expect(submitFeedback).toHaveBeenCalled());
    expect(submitFeedback).toHaveBeenCalledWith("Bug", "Details", second);
  });
});
