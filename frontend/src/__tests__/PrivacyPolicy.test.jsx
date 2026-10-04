import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { MemoryRouter } from "react-router-dom";
import PrivacyPolicy from "../pages/PrivacyPolicy";
import { CURRENT_PRIVACY_POLICY_VERSION } from "../constants";

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

  it("points the Access right at the Download My Data export", () => {
    render(
      <MemoryRouter>
        <PrivacyPolicy />
      </MemoryRouter>
    );
    expect(screen.getByText(/Download My Data/)).toBeInTheDocument();
  });

  it("discloses the 180-day duel retention and the duel history kept until deletion", () => {
    render(
      <MemoryRouter>
        <PrivacyPolicy />
      </MemoryRouter>
    );
    const duelRetention = screen.getByText(/full record of each duel/);
    expect(duelRetention).toHaveTextContent(/kept for 180 days/);
    expect(duelRetention).toHaveTextContent(
      /duel history is kept until you delete your account/
    );
  });

  it("shows the policy version users are asked to consent to", () => {
    render(
      <MemoryRouter>
        <PrivacyPolicy />
      </MemoryRouter>
    );
    expect(
      screen.getByText(`Version ${CURRENT_PRIVACY_POLICY_VERSION}`, { exact: false })
    ).toBeInTheDocument();
  });
});
