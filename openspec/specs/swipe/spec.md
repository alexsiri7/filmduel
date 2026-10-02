# Swipe

## Purpose

Before films can be ranked the user has to say which ones they have seen. Swiping is the fast, mindless half of the game: classify ten titles, then go back to dueling. Keeping it separate from dueling stops either activity from feeling like homework.

## Requirements

### Requirement: A session offers ten unclassified titles matched to taste

A swipe session SHALL offer up to 10 distinct titles of the selected media type that the user has not yet classified. Six SHALL come from the community-rating band matching the user's median rating, two from the band above and two from the band below, topped up at random when a band runs short; a user with no ranked titles SHALL get a random selection. When nothing is left to classify, the user SHALL be told to import more titles.

#### Scenario: Established taste
- GIVEN a user whose median rating falls in the strong band
- WHEN they start a swipe session
- THEN six cards come from the strong band, two from elite and two from mid

#### Scenario: Nothing left
- GIVEN a user with no unclassified titles
- WHEN they start a swipe session
- THEN they are told to import more titles

### Requirement: Cards are classified by swipe or tap

Each card SHALL show the poster, title, year and genre. The user SHALL mark it seen by swiping right or tapping "Seen it", and not seen by swiping left or tapping "Never seen it"; a drag shorter than 80px SHALL NOT count. A progress counter SHALL show the position in the session, and a summary SHALL show how many were seen before returning to duels.

#### Scenario: Short drag
- GIVEN a card on screen
- WHEN the user drags it 50px right and releases
- THEN the card returns to centre and nothing is recorded

#### Scenario: Session summary
- GIVEN the user marked 6 of 10 cards seen
- WHEN the session ends
- THEN the summary reads that they have seen 6 of these

### Requirement: Results are submitted together

The results of a session SHALL be submitted in one request and SHALL return the seen and unseen counts and the next action. Only titles still unclassified in the user's library SHALL be updated; others SHALL be skipped without failing the submission, and a title listed twice SHALL count once. A user SHALL be able to classify at most 2000 titles in any 24 hours; a submission over that cap SHALL be refused whole.

#### Scenario: Stale card
- GIVEN a session in which one title was classified meanwhile through a duel
- WHEN the session is submitted
- THEN that title is skipped and the other nine are recorded

### Requirement: Titles marked not seen never come back

A title the user has marked not seen SHALL never again be offered to them in a swipe session or a duel.

#### Scenario: Not seen
- GIVEN the user swiped a film left
- WHEN later swipe sessions and duels are chosen
- THEN that film never appears
