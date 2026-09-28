# Rating Sync

## Purpose

The user's tracking service is where their film data lives long term. When they opt in, FilmDuel writes its duel-derived scores back there so the two never drift apart.

## Requirements

### Requirement: Sync is opt-in per provider

Each user SHALL have a separate setting for syncing scores to Trakt and to SIMKL, both off by default, and each setting SHALL take effect: with it on, scores SHALL be pushed to that provider; with it off, nothing SHALL be pushed there.

#### Scenario: Default user
- GIVEN a user who never changed their sync settings
- WHEN they win a duel
- THEN no score is sent to any provider

#### Scenario: SIMKL sync enabled
- GIVEN a SIMKL user with SIMKL sync turned on
- WHEN they complete a duel with a winner
- THEN both titles' 1–10 scores are sent to SIMKL

### Requirement: Scores are pushed after every decided duel

After every duel or tournament match with a winner, for each enabled provider the system SHALL push both titles' 1–10 scores in the background, refreshing the token first and retrying once on a server error. The duel response SHALL NOT wait for the sync, a failed sync SHALL be logged and never shown to the user, and the sync SHALL NOT hold resources that slow down the user's other requests.

#### Scenario: Trakt is down
- GIVEN Trakt sync is on and Trakt returns a server error twice
- WHEN the user wins a duel
- THEN the duel is recorded and the next pair is shown as usual
- AND the failure is logged after exactly one retry

#### Scenario: Busy user
- GIVEN Trakt sync is on and a sync is in progress
- WHEN the user makes other requests
- THEN those requests are not delayed or timed out by the sync
