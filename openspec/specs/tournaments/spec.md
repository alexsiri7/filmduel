# Tournaments

## Purpose

A tournament is a celebration of taste the user already has: a fixed bracket of their ranked titles, visible progression and a definitive champion. Its matches are real duels, so playing one also sharpens the main ranking.

## Requirements

### Requirement: A bracket is built from ranked titles

A user SHALL be able to create a tournament of 8, 16, 32 or 64 titles from their ranked titles of the selected media type, optionally filtered by genre or decade. Creation SHALL require at least 4 matching titles and a bracket no larger than twice the matching pool, and the create form SHALL offer only the sizes that would be accepted. Titles SHALL be seeded by rating, seed 1 against the lowest seed; when the pool is smaller than the bracket, top seeds SHALL receive round-one byes that are already resolved. Every round SHALL exist from the start, and a user SHALL create at most 100 tournaments in 24 hours.

#### Scenario: Too few films
- GIVEN a user with 3 ranked horror films
- WHEN they try to create a horror tournament
- THEN creation is refused with a message to keep dueling

#### Scenario: Byes for top seeds
- GIVEN 13 ranked horror films
- WHEN a 16-title horror tournament is created
- THEN seeds 1 to 3 advance to round two by bye
- AND round one has 5 playable matches

#### Scenario: Bracket too large
- GIVEN 20 ranked sci-fi films
- WHEN the user opens the create form with a sci-fi filter
- THEN 32 is the largest size offered and 64 is refused

### Requirement: Matches are real duels

The next match offered SHALL never be a bye. Submitting a match winner SHALL update ratings exactly as a regular duel does, record it in the duel history linked to the match, trigger rating sync, and advance the winner into the next round. Resolving the final SHALL complete the tournament with its champion and completion time. The match screen SHALL offer only picking a winner, without the not-seen options.

#### Scenario: Final played
- GIVEN a tournament whose only unplayed match is the final
- WHEN the user picks the winner
- THEN the tournament is completed and the winner is its champion
- AND both finalists' main ratings changed as in a regular duel

### Requirement: Tournaments can be browsed and abandoned

A user SHALL see their own tournaments, newest first, each with its progress: "Completed", "Abandoned", or the current round's played and total matches. Opening a tournament SHALL show the whole bracket in round and position order. Another user's tournament SHALL be reported as not found. A user SHALL be able to abandon a tournament, which keeps it listed as abandoned.

#### Scenario: Someone else's tournament
- GIVEN a tournament owned by user A
- WHEN user B opens it
- THEN it is reported as not found

### Requirement: AI can curate a themed tournament

A user with AI features available SHALL be able to ask for an AI-curated tournament. The AI SHALL receive the top three times the bracket size of the filtered pool by rating and SHALL select exactly the bracket size from that list, with a name, tagline and theme description shown before play. Selected titles SHALL be seeded by rating; the AI SHALL never set matchups. An AI failure SHALL create nothing and report that curation failed. Before any match has been played, the user SHALL be able to regenerate at most 3 times with the same theme hint and pool.

#### Scenario: Curated bracket
- GIVEN a user with 60 ranked films and AI features on
- WHEN they request an AI-curated 16-title tournament
- THEN the AI chooses 16 of their top 48 films and names the theme
- AND the bracket is seeded by rating

#### Scenario: Fourth regeneration
- GIVEN an AI-curated tournament regenerated 3 times
- WHEN the user asks to regenerate again
- THEN the request is refused

#### Scenario: Regenerating after play
- GIVEN an AI-curated tournament with one match played
- WHEN the user asks to regenerate
- THEN the request is refused
