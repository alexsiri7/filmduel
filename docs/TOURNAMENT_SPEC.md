# FilmDuel — Tournament Mode Spec

## Overview
Tournament mode: structured bracket within a filtered subset of ranked films.
Fixed bracket, visible progression, definitive winner.

## Flow
1. Create: pick filter (genre/decade/all) + bracket size (8/16/32/64)
2. Seed by ELO (1 vs last, 2 vs second-to-last)
3. Preview bracket, then play round by round
4. Winner advances, bracket updates visually
5. Champion crowned when final played

## Schema
- tournaments: id, user_id, name, filter_type/value, bracket_size, status, champion_movie_id
- tournament_matches: id, tournament_id, round, position, movie_a_id, movie_b_id, winner_movie_id, duel_id

## API
- POST /api/tournaments — create + seed
- GET /api/tournaments — list
- GET /api/tournaments/:id — bracket state
- GET /api/tournaments/:id/next — next match
- POST /api/tournaments/:id/matches/:mid — submit result
- DELETE /api/tournaments/:id — abandon

## Frontend
- /tournaments — list + create
- /tournaments/:id — bracket visualization + play
