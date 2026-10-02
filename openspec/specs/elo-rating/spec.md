# ELO Rating

## Purpose

Head-to-head choices produce a ranking without asking the user to score anything. ELO turns those choices into ratings that settle as evidence accumulates, and a percentile mapping turns ratings into the 1–10 scores other services understand.

## Requirements

### Requirement: Ratings settle as battles accumulate

When a duel has a winner, both titles SHALL be updated with the standard ELO expected-score formula (divisor 400), each with its own K-factor of 300 / sqrt(battles + 1) from its battle count before the duel. Ratings SHALL be stored unrounded and rounded only for display.

#### Scenario: Equal films
- GIVEN two films rated 1000 with 3 battles each
- WHEN one beats the other
- THEN the winner gains 75 points and the loser loses 75

#### Scenario: Independent K-factors
- GIVEN a winner with 0 battles and a loser with 8
- WHEN the duel is scored
- THEN the winner's change uses K 300 and the loser's uses K 100

### Requirement: No rating until the first duel

A title SHALL have no rating until its first duel with a winner. That duel SHALL start from its imported starting rating if it has one, otherwise 1000, and from then on its own rating SHALL be used.

#### Scenario: Seeded first duel
- GIVEN an unranked film with a starting rating of 1400
- WHEN it wins its first duel
- THEN the calculation starts from 1400 and the film now has a rating

### Requirement: 1–10 scores are percentiles

A title's 1–10 score SHALL be its mid-rank percentile among the user's ranked titles of the same media type, ceil(10 × (below + ties / 2) / N) clamped to 1–10, so every user's scores span the whole scale. Tied ratings SHALL share a score. The same score SHALL be used for display, provider sync and Letterboxd export, and filters SHALL NOT change it.

#### Scenario: Ten distinct films
- GIVEN ten ranked films with distinct ratings
- WHEN their scores are computed
- THEN they score 1 to 10 in rating order

#### Scenario: Single ranked film
- GIVEN a user with one ranked film
- WHEN its score is computed
- THEN it scores 5
