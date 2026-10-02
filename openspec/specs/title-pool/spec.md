# Title Pool

## Purpose

There must always be something to swipe or duel. The title pool combines broad lists (popular, trending), personal ones (recommendations, watch history, ratings) and on-demand expansion into one catalog of films and shows, so a user starts from what they have already watched and keeps discovering more.

## Requirements

### Requirement: The library is imported from the user's provider

After a user first consents, the system SHALL import in the background, for both movies and shows, the provider's popular, trending and recommended lists and the user's watch history and ratings. The user's profile SHALL report the import as importing, complete or failed; an import that has not finished within 20 minutes SHALL be reported as failed; and the user SHALL be able to retry an import that is not running, at most 3 times per hour. A failure in one source SHALL NOT prevent the others from being imported, and SHALL mark the import as failed.

#### Scenario: First import
- GIVEN a user who has just consented
- WHEN the consent is recorded
- THEN the import starts in the background and the profile reports "importing"
- AND when every source has been fetched the profile reports "complete"

#### Scenario: Import interrupted by a deploy
- GIVEN an import that started 25 minutes ago and never finished
- WHEN the user reads their profile
- THEN the import is reported as "failed" and the user can retry it

### Requirement: History and ratings seed the user's state

Titles in the user's watch history SHALL enter their library as seen but unranked. Titles the user has rated on the provider SHALL receive a starting rating mapped linearly from rating 1 to 600 and rating 10 to 1400, used only as the starting point of their first duel; they SHALL stay unranked with no battles until then.

#### Scenario: Rated film imported
- GIVEN the user rated a film 10 on Trakt
- WHEN it is imported
- THEN it is seen, unranked, with a starting rating of 1400 and no battles

### Requirement: One shared catalog, private per-user state

Title metadata (title, year, genres, overview, runtime, poster, community rating on a 0–100 scale, external ids) SHALL be kept once and shared by all users, while seen status, rating and battle count SHALL be private to each user. Refreshing the catalog SHALL NOT reset any user's state. A title imported from SIMKL whose IMDB id matches an existing entry of the same media type SHALL reuse that entry rather than create a second one.

#### Scenario: Re-import keeps rankings
- GIVEN a ranked film with 12 battles
- WHEN the pool is re-imported and the film's metadata changes
- THEN the film still has its rating and 12 battles

#### Scenario: SIMKL after Trakt
- GIVEN a film already in the catalog from Trakt
- WHEN the same film arrives from SIMKL with the same IMDB id
- THEN no second catalog entry is created and the user's state stays on one entry

### Requirement: The pool refreshes on return and on demand

When a consented user signs in, the pool SHALL be refreshed in the background. The user SHALL be able to trigger a refresh manually at most 3 times per hour; the result SHALL report how many titles were added and the new total.

#### Scenario: Manual sync
- GIVEN a user with 400 titles in their library
- WHEN they trigger a sync and the provider returns 12 new titles
- THEN they are told 12 were added and the total is 412

#### Scenario: Too many syncs
- GIVEN a user who synced 3 times in the last hour
- WHEN they sync again
- THEN the request is refused as rate limited

### Requirement: Only titles with posters are shown

Posters SHALL be fetched from TMDB in the background, never delaying a request, and swipe cards and suggestions SHALL only offer titles that have a poster. The TMDB credential SHALL never appear in a request URL when a read access token is configured.

#### Scenario: Poster missing
- GIVEN an unknown title whose poster has not been fetched yet
- WHEN swipe cards are chosen
- THEN that title is not offered

### Requirement: The pool expands when the unknown pile runs low

When a swipe submission leaves fewer than 50 unclassified titles of that media type, the system SHALL expand the pool in the background, in priority order: provider recommendations, TMDB titles similar to the user's top-ranked, provider anticipated titles, then deeper popular pages; it SHALL stop at about 100 new titles, SHALL NOT repeat a source for the same key within 7 days, SHALL run at most one expansion per user and media type at a time, and SHALL NOT change the state of titles already in the library.

#### Scenario: Running low
- GIVEN a user with 45 unclassified movies
- WHEN they submit a swipe session
- THEN an expansion starts without delaying the response
- AND new movies arrive unclassified

### Requirement: Movies and shows are separate worlds

Every pool, swipe, duel, ranking, suggestion and tournament operation SHALL be scoped to one media type, movie or show, defaulting to movie, with independent libraries, ratings and rankings. A nav toggle SHALL switch between them and SHALL be remembered across visits on the same browser. Any other media type SHALL be rejected.

#### Scenario: Show duels leave movies alone
- GIVEN a user with ranked movies and ranked shows
- WHEN they duel two shows
- THEN no movie's rating or rank changes

#### Scenario: Toggle remembered
- GIVEN a user who switched to TV Shows
- WHEN they return to the app later on the same browser
- THEN TV Shows is selected
