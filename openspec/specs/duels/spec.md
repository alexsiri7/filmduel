# Duels

## Purpose

The duel is the heart of FilmDuel: two titles the user has seen, one tap to say which they rate higher. Every seen title should keep being drawn into duels, and every duel should be close enough to teach the ranking something.

## Requirements

### Requirement: Pairs anchor on the least-dueled title and match the closest rating

A pair SHALL be drawn only from titles the user has marked seen, of the selected media type. The anchor SHALL be chosen at random among those with the fewest battles, across all of the user's seen titles. The challenger SHALL be chosen at random among the 5 other seen titles whose effective rating (current rating, else starting rating, else 1000) is closest to the anchor's. If the anchor was in the previous pair, its previous partner SHALL be skipped unless it is the only other title. With fewer than two seen titles, the user SHALL be sent to swipe.

#### Scenario: Unranked films are drawn in first
- GIVEN 300 seen films, 40 of them with no battles
- WHEN a pair is requested
- THEN the anchor is one of the 40 with no battles

#### Scenario: No immediate rematch
- GIVEN the previous pair was A vs B and A is chosen as anchor again
- AND other seen films exist
- WHEN a pair is requested
- THEN B is not the challenger

#### Scenario: Too few seen films
- GIVEN a user with one seen film
- WHEN a pair is requested
- THEN they are sent to swipe

### Requirement: Only offered pairs can be dueled

Each pair SHALL carry an encrypted token binding the user and the two titles. A duel submission SHALL be refused with "Invalid pair token" when the token is missing, cannot be decrypted, is older than 15 minutes, was issued to another user, or names different titles. A submission naming the same title twice SHALL be refused with "A movie cannot duel against itself".

#### Scenario: Token from another user
- GIVEN a pair token issued to user A
- WHEN user B submits a duel with it
- THEN the submission is refused with "Invalid pair token"

#### Scenario: Expired token
- GIVEN a pair served 20 minutes ago
- WHEN the duel is submitted
- THEN the submission is refused with "Invalid pair token"

### Requirement: Outcomes move titles through their states

A duel SHALL have one of five outcomes. When A or B wins, both titles SHALL be marked seen, both ratings updated and both battle counts incremented. When only one was seen, that one SHALL be marked seen and the other marked not seen unless it already has battles. When neither was seen, each SHALL be marked not seen unless it already has battles. Every outcome SHALL be recorded in the duel history, with ratings before and after for a win.

#### Scenario: Only seen A
- GIVEN an unclassified film A and an unranked film B
- WHEN the user answers "Only seen A"
- THEN A is seen, B is not seen, and no rating changes

#### Scenario: Ranked film protected
- GIVEN film B has 5 battles
- WHEN the user answers "Haven't seen either"
- THEN B keeps its seen status and rating

### Requirement: The server says when to swipe

Every duel and swipe submission SHALL return a next action: swipe when the user has fewer than 3 seen-but-unranked titles or fewer than 10 seen titles of that media type, otherwise duel. The swipe prompt SHALL appear between duels, never in the middle of one, and the user SHALL be able to dismiss it and keep dueling.

#### Scenario: Running out of unranked films
- GIVEN a user with 2 seen-but-unranked films and 50 seen films
- WHEN they submit a duel
- THEN the next action is swipe and the swipe prompt appears before the next pair

### Requirement: The duel screen is one tap

The duel screen SHALL show two posters side by side with a "vs" badge, each with title, year and genres, and rating and battle count once ranked. Tapping a poster SHALL pick it as the winner. Three secondary buttons, "Only seen {A}", "Only seen {B}" and "Haven't seen either", SHALL record the pair without changing ratings. The next pair SHALL be requested as soon as the submission is accepted, so it reflects this duel's result. A failed submission SHALL keep the pair on screen with a retry. A stats bar SHALL show duels played, titles ranked and titles left to discover.

#### Scenario: Pick a winner
- GIVEN a pair on screen
- WHEN the user taps the left poster
- THEN the left title is recorded as the winner and the next pair appears

#### Scenario: Submission fails
- GIVEN a pair on screen
- WHEN the user's pick cannot be saved
- THEN the pair stays on screen and the user can retry the pick

### Requirement: Concurrent duels do not lose updates

Two duels submitted at once for the same user SHALL both be applied fully, with no lost rating update and no deadlock.

#### Scenario: Double submission
- GIVEN two tabs submit duels involving the same film at the same time
- WHEN both are processed
- THEN the film's battle count increases by two

### Requirement: A broken duel flow is noticed

After every deploy, a smoke test SHALL fetch a pair and submit a duel as a test user, and a spike in rejected duel submissions SHALL raise an alert. Rejected duels SHALL be logged as warnings and frontend errors SHALL reach error tracking.

#### Scenario: Duels start failing
- GIVEN a deploy that makes every duel submission fail
- WHEN the post-deploy smoke test runs
- THEN it fails and the failure is reported
