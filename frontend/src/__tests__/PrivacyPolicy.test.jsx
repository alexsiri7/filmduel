import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { MemoryRouter } from "react-router-dom";
import PrivacyPolicy from "../pages/PrivacyPolicy";

describe("PrivacyPolicy", () => {
  it("renders AI data sharing section with Watch Suggestions and AI-Curated Tournaments headings", () => {
    render(
      <MemoryRouter>
        <PrivacyPolicy />
      </MemoryRouter>
    );
    // The AI Data Sharing section heading labels appear as <strong> elements within paragraphs
    const watchSuggestionsEls = screen.getAllByText(/Watch Suggestions/i);
    expect(watchSuggestionsEls.length).toBeGreaterThan(0);
    const aiTournamentEls = screen.getAllByText(/AI-Curated Tournaments/i);
    expect(aiTournamentEls.length).toBeGreaterThan(0);
  });
});
