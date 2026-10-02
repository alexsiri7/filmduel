# Rankings and Export

## Purpose

The ranked list is the payoff for all the dueling: the user's titles in order, browsable by genre and decade, and portable to Letterboxd.

## Requirements

### Requirement: The leaderboard shows only ranked titles

The rankings SHALL list only titles the user has seen and dueled at least once, of the selected media type, ordered by rating descending, 50 per page and at most 200 per request. Each row SHALL show rank, poster, title, year, rating, 1–10 score, battle count and links to the title on Trakt and IMDB. Rank numbers SHALL continue across pages, and every page SHALL stay within the selected media type. The top title SHALL be visually distinguished.

#### Scenario: Unranked film hidden
- GIVEN a seen film with no battles
- WHEN the user views their rankings
- THEN it is not listed

#### Scenario: Second page of shows
- GIVEN a user viewing TV show rankings with 80 ranked shows
- WHEN they load more
- THEN shows ranked 51 to 80 are appended, numbered 51 to 80, and no movies appear

### Requirement: Rankings filter by genre and decade

The leaderboard SHALL offer filter pills for All, each genre among the user's ranked titles, and each decade. Filtering SHALL NOT change any title's 1–10 score. An invalid decade SHALL be refused.

#### Scenario: Filter by decade
- GIVEN ranked films from the 1990s and 2000s
- WHEN the user selects 1990s
- THEN only 1990s films are listed, with the same scores they have unfiltered

### Requirement: Stats summarise progress

The user SHALL be able to see, per media type, total duels, number ranked, number left to discover, average rating, and the highest and lowest rated titles. With nothing ranked, the counts SHALL be zero and no highest or lowest title SHALL be given.

#### Scenario: New user
- GIVEN a user with no ranked films
- WHEN they view their stats
- THEN every count is zero and no highest or lowest film is shown

### Requirement: Rankings export to Letterboxd

The user SHALL be able to download their ranked titles of the selected media type as a Letterboxd-compatible CSV named filmduel_rankings.csv, with columns Position, Title, Year, imdbID and Rating10 in rank order, Rating10 being the 1–10 score. Cells beginning with a formula character SHALL be prefixed with a single quote. Exports SHALL be capped at 10,000 rows and 10 per hour. A floating button on the rankings page SHALL start the export.

#### Scenario: Formula in a title
- GIVEN a ranked film titled "=HYPERLINK(...)"
- WHEN the CSV is exported
- THEN the cell reads "'=HYPERLINK(...)"
