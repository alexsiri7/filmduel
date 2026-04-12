# FilmDuel — Suggestions & Pool Expansion Spec

## Overview

Two related features:

1. **Watchlist suggestions** — AI-curated "films you should watch next" based on your ranking profile. Uses LLM reasoning over Trakt-sourced candidates.
2. **Background pool expansion** — automatically grows the swipe pool when it runs low, so the user never hits a dead end. No LLM involved — pure data pipeline.

These are distinct systems that share a trigger: both kick in when the unknown pool is getting thin.

---

## Part 1 — Watchlist Suggestions

### Concept

Once a user has 20+ ranked films, FilmDuel knows their taste better than any algorithm. The suggestions feature turns that taste profile into a personalised watchlist of unseen films — with a one-line reason for each pick that makes the recommendation feel personal, not algorithmic.

The flow is:
1. Trakt provides personalised unseen film candidates (Source 4: `/movies/recommended` + expansion sources)
2. The LLM receives the user's taste profile + candidates, selects the best matches, explains each pick
3. Results shown as a "Watch next" screen with poster, reason, and streaming availability link (via JustWatch deep link or Trakt's `available_translations`)

### When to show suggestions

- Dedicated `/suggestions` page accessible from nav
- Refreshed at most once per day per user (cache result)
- Regenerate button for manual refresh (rate-limited to 3 per day)
- Also surfaced as a nudge after a swipe session: "Based on your rankings, here are 6 films worth adding to your watchlist"

### LLM Input

The prompt is a two-part structure: taste profile derived from ranked films, and candidates from the pool.

```
System:
You are a film recommendation assistant for a movie ranking app. 
The user has built a taste profile through head-to-head film duels.
Select 6 films from the candidate list that best match their taste.

Rules:
- Select ONLY films from the candidate list (use trakt_id)
- Write a single specific sentence for each pick explaining WHY 
  it matches this user's taste — reference their actual top films 
  by name where relevant
- Do not pick films the user has already seen
- Prefer variety across genres unless the taste profile is very 
  genre-specific
- Return valid JSON only, no preamble

Return format:
{
  "picks": [
    {
      "trakt_id": 12345,
      "reason": "If you rated Mulholland Drive so highly, Lynch's 
                 earlier Blue Velvet will feel like essential context."
    },
    ...
  ]
}

User taste profile:

Top 10 ranked films:
{top_10: [{title, year, genres, director, elo}]}

Bottom 5 ranked films (films they've seen and rated lowest):
{bottom_5: [{title, year, genres, director, elo}]}

Genres by average ELO (descending):
{genre_affinities: [{"genre": "mystery", "avg_elo": 1280, "count": 8}, ...]}

Candidate unseen films (from personalised Trakt recommendations + TMDB similar):
{candidates: [{trakt_id, title, year, genres, director, community_rating}]}
```

### Taste profile construction

Built server-side before the LLM call. Never send raw ranked films — distill into signal:

**Top 10 by ELO** — the clearest positive signal. Include title, year, genres, director.

**Bottom 5 by ELO** — the clearest negative signal. Prevents the LLM from recommending films in a style the user has demonstrably rejected.

**Genre affinities** — aggregate ELO by genre across all ranked films. `avg_elo` per genre tells the LLM which genres this user tends to love vs tolerate. Only include genres with ≥ 3 ranked films (otherwise the signal is noise).

**Candidate list** — 40–60 unseen films from the pool. Prioritise candidates from TMDB similar (seeded from user's top 10 ranked films) over generic popular/trending, as those are more taste-matched.

### Candidate sourcing

Candidates are drawn from `user_movies where seen IS NULL` — films already in the pool that the user hasn't classified yet. This means the pool expansion (Part 2) directly feeds suggestion quality. A richer pool = better candidates = better picks.

Never generate film names from scratch in the LLM prompt — always select from the provided candidate list. This prevents hallucination and ensures every suggestion links to a real Trakt entry with a poster and metadata.

### Schema

```sql
create table suggestions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id) on delete cascade,
  movie_id uuid references movies(id) on delete cascade,
  reason text not null,             -- LLM-generated explanation
  generated_at timestamptz not null default now(),
  dismissed_at timestamptz,         -- user dismissed this suggestion
  added_to_watchlist_at timestamptz -- user acted on it
);

create index on suggestions(user_id);
create index on suggestions(user_id, dismissed_at) where dismissed_at is null;
```

No need to cache the full LLM response — just persist the individual picks with their reasons. Re-generate on demand.

### API

```
GET  /api/suggestions
     Returns current suggestions (up to 6). 
     If none exist or stale (> 24h): triggers generation, 
     returns 202 with { status: "generating" } if async,
     or waits synchronously (< 5s expected).

POST /api/suggestions/regenerate
     Force regeneration. Rate-limited: 3 per day per user.
     Returns 429 with { next_allowed_at } if exceeded.

POST /api/suggestions/:id/dismiss
     Soft-delete — mark dismissed_at. Excluded from future responses.

POST /api/suggestions/:id/watchlist
     Mark as added_to_watchlist. Optionally add to Trakt watchlist:
     POST https://api.trakt.tv/sync/watchlist with the movie's trakt_id.
```

### Frontend

`/suggestions` page — "Your watchlist" in nav.

Six film cards in a 2×3 grid (mobile: 1-column scroll). Each card:
- Poster (full bleed)
- Title + year
- Reason text (1–2 lines, italic, muted)
- Two actions: "Add to watchlist" (amber) + "Dismiss" (ghost ×)

Dismissed films slide out. If all 6 dismissed: show "Regenerate suggestions" CTA.

Refresh indicator at top: "Generated today" or "Generated 3 days ago · Refresh".

Minimum requirement to show suggestions: 20 ranked films. Below that: "Keep dueling! Once you've ranked 20 films we'll suggest what to watch next." with a progress bar.

---

## Part 2 — Background Pool Expansion

### Problem

The default pool (popular + trending + recommended) exhausts quickly. After a few swipe sessions, a user may have classified most of the ~300 films in the initial pool, leaving the unknown count dangerously low. The swipe session needs material to work with.

### Trigger

After every swipe session submission, the backend checks:

```python
unknown_count = count(user_movies, user_id=user_id, seen=None)
if unknown_count < 50:
    enqueue_background_task("expand_pool", user_id=user_id)
```

The threshold is 50 — high enough to never visibly exhaust the pool between expansion runs.

### Expansion sources (in priority order)

**Source A — TMDB similar films (highest quality)**
For each of the user's top 10 ranked films (by ELO):
```
GET https://api.themoviedb.org/3/movie/{tmdb_id}/recommendations?api_key=...
```
Returns up to 20 films per call. 10 films × 20 results = up to 200 new candidates. These are the most taste-matched candidates because they're seeded from films the user demonstrably loves.

**Source B — Director filmographies**
Find directors appearing 3+ times in the user's top 20 ranked films. For each:
```
GET https://api.trakt.tv/people/{trakt_person_slug}/movies
```
A user who loves 4 Scorsese films in their top 20 probably hasn't seen his full filmography. Fetch it.

**Source C — Trakt anticipated**
```
GET https://api.trakt.tv/movies/anticipated?limit=100&extended=full
```
Upcoming and recently released films. Refresh weekly globally (not per-user). Good for staying current.

**Source D — Deeper pagination of existing sources**
```
GET https://api.trakt.tv/movies/popular?page=2&limit=100&extended=full
GET https://api.trakt.tv/movies/popular?page=3&limit=100&extended=full
```
Pages 2–5 of popular are still high-quality films. Only fetch when Sources A and B have been exhausted.

### Deduplication

All expansion results are upserted into the shared `movies` table by `trakt_id`. New `user_movies` rows created with `seen=null`. If a film is already in `user_movies` for this user (any `seen` value), skip it — don't reset state.

### Expansion tracking

Add a `pool_expansions` table to track what's been fetched, avoid re-running the same sources, and rate-limit Trakt/TMDB calls:

```sql
create table pool_expansions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id) on delete cascade,
  source text not null,       -- 'tmdb_similar' | 'director_filmography' | 
                              --  'anticipated' | 'popular_page_N'
  source_key text,            -- tmdb_id for similar, person_slug for director, 
                              --  page number for pagination
  films_added integer not null default 0,
  ran_at timestamptz not null default now()
);

create index on pool_expansions(user_id, source, source_key);
```

Before running a source, check if it was run in the last 7 days for this user. If so, skip. This prevents hammering the APIs and re-fetching the same results.

### Background task implementation

Use FastAPI's `BackgroundTasks` for the expansion job. It runs after the swipe result response is returned — never blocks the user.

```python
@router.post("/api/swipe/results")
async def submit_swipe_results(
    results: SwipeResults,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # ... process swipe results ...
    
    unknown_count = await get_unknown_count(db, user.id)
    if unknown_count < 50:
        background_tasks.add_task(expand_pool, user_id=user.id)
    
    return {"seen_count": seen, "unseen_count": unseen}
```

The `expand_pool` task runs sources A → D in order, stopping once 100+ new films have been added (no need to run all sources every time).

### TMDB rate limiting

TMDB free tier allows 40 requests per 10 seconds. The expansion task may make up to 10 calls (one per top-ranked film for Source A). Add a 0.3s delay between calls or use a simple token bucket. Log any 429s to Sentry.

### Notes for Claude Code

- Expansion is triggered from the swipe submission endpoint, not the duel endpoint
- Never block the user response — always use `BackgroundTasks`
- The `pool_expansions` table is the guard against re-running stale sources
- Source A (TMDB similar) uses `tmdb_id` from the `movies` table — ensure this is populated when movies are cached
- Upsert logic: `INSERT INTO movies ... ON CONFLICT (trakt_id) DO UPDATE SET cached_at = now()` — always refresh metadata on re-encounter
- New `user_movies` rows get `seen=null, elo=null, battles=0, seeded_elo=null`
- After expansion, the swipe session will naturally surface new films since they have the highest weight in the unknown pool
