# AI Suggestions

## Purpose

Once a user has ranked enough, their ranking says something about their taste. AI suggestions turn that into a short watchlist of unseen titles, each with a reason, without ever sending the AI the user's identity or raw scores.

## Requirements

### Requirement: AI features need consent and can be switched off

AI features (suggestions and AI-curated tournaments) SHALL be on by default and switchable in settings. Every AI request SHALL be refused unless the user has accepted the current privacy policy ("Privacy policy consent required") and has AI features on ("AI features are disabled. Enable them in settings to use this feature."). With AI features off, the suggestions page and AI tournament options SHALL be hidden.

#### Scenario: AI switched off
- GIVEN a user who turned AI features off
- WHEN they request suggestions
- THEN the request is refused with the AI-disabled message
- AND the suggestions page is not shown in navigation

### Requirement: Suggestions come from the user's own candidates

A user with at least 20 ranked titles of the selected media type SHALL receive up to 6 suggestions chosen by the AI from at most 50 unseen candidates, each with a one-line reason. Suggestions generated in the last 24 hours SHALL be reused. A user with fewer than 20 ranked titles SHALL be told there are not enough; a user with no candidates SHALL be told there are none. Picks outside the candidate list SHALL be dropped. With no AI service configured, the feature SHALL report that it is unavailable.

#### Scenario: Not enough ranked films
- GIVEN a user with 12 ranked films
- WHEN they open suggestions
- THEN no suggestions are shown and they are told they need more ranked films

#### Scenario: AI invents a film
- GIVEN the AI returns an id not in the candidate list
- WHEN suggestions are stored
- THEN that pick is dropped

### Requirement: Suggestions can be dismissed, saved or marked seen

The user SHALL be able to dismiss a suggestion, after which it is never shown again; add it to their watchlist, optionally pushing it to their provider's watchlist; or mark it seen. Acting on another user's suggestion SHALL be reported as not found.

#### Scenario: Dismiss
- GIVEN a suggestion the user dismissed
- WHEN they open suggestions again
- THEN it is not shown

### Requirement: Manual regeneration is capped

The user SHALL be able to replace their suggestions with a fresh set at most 3 times in any 24 hours; a fourth request SHALL be refused as rate limited. Automatic refreshes of stale suggestions SHALL NOT count against this cap, and an empty regeneration SHALL report its reason the same way as a normal request.

#### Scenario: Automatic refresh
- GIVEN a user whose suggestions were refreshed automatically after 24 hours
- WHEN they regenerate manually three times that day
- THEN all three regenerations are allowed

### Requirement: The AI never sees raw scores or identities

Prompts to the AI SHALL describe the user's taste only through coarse preference tiers (highly preferred, preferred, neutral, less preferred) and SHALL carry no raw rating and no account identifier. Titles and other stored strings SHALL be screened for prompt-injection phrases and length-capped, and SHALL be presented to the AI as data, not instructions. The AI's output SHALL be validated against the candidates it was given, and raw AI responses SHALL NOT be written to error logs.

#### Scenario: Hostile title
- GIVEN a catalog title containing "ignore previous instructions"
- WHEN it is included in a prompt
- THEN the phrase is redacted and the title is marked as data
