# FilmDuel — Product Requirements Document

## Overview

FilmDuel is a web app that helps users discover and rank movies through pairwise comparisons. Users authenticate with their Trakt account, are shown two films at a time, answer whether they've seen each one, and (if they've seen both) pick which they rate higher. This generates an ELO-ranked list of every film the user has seen. Ratings are synced back to Trakt in real time.

The experience should feel like a game — fast, opinionated, oddly compelling.

---

## Goals

- Let users rapidly build a ranked film library without manually searching for titles
- Surface films they may have forgotten they've seen (from their Trakt history)
- Expose them to popular/trending films they haven't seen yet
- Produce a clean ELO ranking exportable to Letterboxd CSV format
- Sync ratings back to Trakt so the data lives somewhere useful

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI |
| ORM | SQLAlchemy 2.0 (async, declarative `mapped_column` style) |
| Migrations | Alembic (async, runs automatically on deploy) |
| Database | Supabase PostgreSQL (direct connection via asyncpg, NOT supabase-py SDK) |
| Auth | Trakt OAuth2 (Authorization Code flow), JWT httpOnly cookies |
| Frontend | React 18, Vite, Tailwind CSS, shadcn/ui components |
| Deployment | Railway (single service, auto-deploy from `main` branch) |
| DNS | Cloudflare (filmduel.interstellarai.net → Railway) |
| Error tracking | Sentry (FastAPI integration) |
| Movie data | Trakt API + TMDB API (poster images) |

**Key constraints:**

- No separate frontend deployment. FastAPI serves the React build from `/static` and catches all non-API routes with a wildcard that returns `index.html`.
- No supabase-py SDK — we connect directly to the Supabase Postgres instance via `DATABASE_URL` using SQLAlchemy + asyncpg.
- Supabase uses PgBouncer in transaction mode — asyncpg must disable prepared statement caching (`statement_cache_size=0`).
- Branch protection on `main` — all changes via PR. Railway auto-deploys on merge to `main`.

### Design Decisions

1. **SQLAlchemy + Alembic over raw Supabase client** — Gives us proper ORM with typed models, versioned migrations that run in CI/deploy, and no vendor lock-in to Supabase's SDK.
2. **Direct Postgres over Supabase SDK** — Supabase is just hosted Postgres. Using the connection string directly means we get full SQLAlchemy power (joins, eager loading, transactions) without the SDK's limitations.
3. **Tailwind + shadcn/ui over plain CSS** — Provides polished, accessible UI components out of the box with minimal overhead. The `cn()` utility (clsx + tailwind-merge) handles conditional classes cleanly.
4. **Transaction pooler (port 6543)** — Supabase's session pooler (5432) holds connections per session; the transaction pooler (6543) is better for serverless/short-lived connections. Requires `statement_cache_size=0` for asyncpg compatibility.
5. **Sentry from day one** — Error tracking wired in before features ship, so we catch issues immediately.
6. **SQLAlchemy models separated from Pydantic schemas** — `db_models.py` contains SQLAlchemy ORM models; `schemas.py` contains Pydantic request/response models. Never conflate the two.

---

## Repository Structure

```
filmduel/
├── backend/
│   ├── main.py            # FastAPI app, mounts static, registers routers
│   ├── db_models.py       # SQLAlchemy ORM models (User, Movie, UserMovie, Duel)
│   ├── schemas.py         # Pydantic request/response models
│   ├── db.py              # SQLAlchemy engine, session factory
│   ├── config.py          # Settings from environment variables (pydantic-settings)
│   ├── routers/
│   │   ├── auth.py        # Trakt OAuth routes
│   │   ├── movies.py      # Movie pool, duel pair generation
│   │   ├── duels.py       # Submit duel results
│   │   └── rankings.py    # Fetch ELO rankings, export CSV
│   └── services/
│       ├── trakt.py       # Trakt API client (async httpx)
│       ├── elo.py         # ELO calculation logic
│       └── sync.py        # Push ratings to Trakt
├── alembic.ini
├── backend/migrations/    # Alembic migrations
│   ├── env.py
│   └── versions/
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── pages/
│   │   │   ├── Login.jsx
│   │   │   ├── Duel.jsx
│   │   │   └── Rankings.jsx
│   │   ├── components/
│   │   │   ├── MovieCard.jsx
│   │   │   └── Nav.jsx
│   │   └── api.js         # Thin fetch wrapper for backend API
│   ├── package.json
│   └── vite.config.js
├── Dockerfile
├── railway.toml
├── .env.example
└── README.md
```

---

## Environment Variables

All config comes from environment variables. Provide an `.env.example` with every variable documented.

```bash
# Database — Supabase Postgres via transaction pooler (port 6543)
# URL-encode special chars in password (e.g. ! → %21)
DATABASE_URL=postgresql+asyncpg://postgres.PROJECT_REF:PASSWORD@aws-0-REGION.pooler.supabase.com:6543/postgres

# Trakt OAuth2 — https://trakt.tv/oauth/applications
TRAKT_CLIENT_ID=
TRAKT_CLIENT_SECRET=
TRAKT_REDIRECT_URI=https://filmduel.interstellarai.net/auth/callback

# TMDB — https://www.themoviedb.org/settings/api (free, instant)
TMDB_API_KEY=

# Sentry — https://sentry.io
SENTRY_DSN=

# App
SECRET_KEY=                  # random 32-byte hex (generate with: openssl rand -hex 32)
BASE_URL=https://filmduel.interstellarai.net
```

---

## Database Schema

Schema is managed via Alembic migrations — the SQL below is for reference only. Do not run it manually; Alembic handles all schema creation and migration on deploy.

```sql
-- Users (one row per Trakt account)
create table users (
  id uuid primary key default gen_random_uuid(),
  trakt_user_id text unique not null,
  trakt_username text not null,
  trakt_access_token text not null,
  trakt_refresh_token text not null,
  trakt_token_expires_at timestamptz not null,
  created_at timestamptz default now(),
  last_seen_at timestamptz default now()
);

-- Movies (shared cache of Trakt movie data, not per-user)
create table movies (
  id uuid primary key default gen_random_uuid(),
  trakt_id integer unique not null,
  imdb_id text,
  tmdb_id integer,
  title text not null,
  year integer,
  genres text[],
  overview text,
  runtime integer,
  poster_url text,
  cached_at timestamptz default now()
);

-- Per-user movie state
create table user_movies (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id) on delete cascade,
  movie_id uuid references movies(id) on delete cascade,
  seen boolean,           -- null=unknown, true=seen, false=not seen
  elo integer,            -- NULL until first real duel (seen=true, battles>0)
  seeded_elo integer,     -- from Trakt rating import, used as starting point for first duel
  battles integer not null default 0,
  trakt_rating integer,   -- last value synced to Trakt (1-10)
  last_dueled_at timestamptz,
  updated_at timestamptz default now(),
  unique(user_id, movie_id)
);

-- Duel history
create table duels (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id) on delete cascade,
  winner_movie_id uuid references movies(id),
  loser_movie_id uuid references movies(id),
  winner_elo_before integer,
  loser_elo_before integer,
  winner_elo_after integer,
  loser_elo_after integer,
  mode text not null default 'discovery',  -- 'discovery' | 'refinement' | 'playoff'
  created_at timestamptz default now()
);

-- Indexes
create index on user_movies(user_id);
create index on user_movies(user_id, seen);
create index on user_movies(user_id, elo desc) where elo is not null;
create index on duels(user_id);
```

---

## Film State Model

A film's state in `user_movies` determines how it participates in duels and rankings. There are four states:

| State | `seen` | `battles` | `elo` | Description |
|---|---|---|---|---|
| **Unknown** | `null` | `0` | `null` | In the pool, never shown to user yet |
| **Unseen** | `false` | any | `null` | User confirmed they haven't seen it. Never shown again. No ELO ever. |
| **Seen -- unranked** | `true` | `0` | `null` | User confirmed they've seen it, but no duel result yet |
| **Ranked** | `true` | `>=1` | integer | Has a real ELO from at least one duel |

**Critical rules:**
- `elo` is `NULL` until a film is both `seen=true` AND `battles>=1`. The DB column default is `NULL`, not `1000`. There is no "default ELO" -- a film either has a real ELO or it doesn't.
- A film with `seen=false` never appears in a duel pair again and never receives an ELO.
- The rankings page only shows films where `seen=true AND battles>=1` (i.e. Ranked state).
- Films imported from Trakt watch history start as Seen -- unranked (`seen=true, battles=0, elo=null`).
- Films imported with an existing Trakt rating start with a `seeded_elo` value and `battles=0`. They are Seen -- unranked but have a starting ELO seed that will be used as their initial value once they enter their first duel.

---

## ELO System

### ELO column behaviour

- `elo` is `NULL` for Unknown, Unseen, and Seen -- unranked films.
- On a film's first duel win/loss, `elo` is set for the first time (not updated from null -- set from scratch using the seeded value if available, or 1000 as the bootstrap value for that first calculation only).
- After the first duel, `elo` is always an integer and is updated on every subsequent duel.

### Seeding ELO from existing Trakt ratings

If the user has an existing Trakt rating (1-10) for a film at import time, store a `seeded_elo` value:

```
seeded_elo = 600 + (trakt_rating - 1) * (800 / 9)
```

This maps: 1->600, 5.5->1000, 10->1400. Store in `seeded_elo` column on `user_movies` (nullable integer).

### ELO calculation

Standard ELO. Use K=64 for a film's first 5 battles (provisional period -- converges faster), then K=32 thereafter.

```python
def expected_score(rating_a: int, rating_b: int) -> float:
    return 1 / (1 + 10 ** ((rating_b - rating_a) / 400))

def k_factor(battles: int) -> int:
    return 64 if battles < 5 else 32

def update_elo(winner_elo: int, loser_elo: int, winner_battles: int, loser_battles: int) -> tuple[int, int]:
    exp = expected_score(winner_elo, loser_elo)
    kw = k_factor(winner_battles)
    kl = k_factor(loser_battles)
    new_winner = round(winner_elo + kw * (1 - exp))
    new_loser = round(loser_elo + kl * (0 - (1 - exp)))
    return new_winner, new_loser
```

When a film enters its first duel, use `seeded_elo` if present, otherwise use 1000 as the bootstrap starting point for that calculation only.

### ELO -> Trakt rating conversion (for sync)

```
trakt_rating = max(1, min(10, round((elo - 600) * 9 / 800) + 1))
```

---

## Game Modes

FilmDuel has three distinct game modes. The active mode is passed as a parameter to `GET /api/movies/pair` and stored on each duel record.

### Discovery mode (default)

**Purpose:** Expand the ranked library. Introduce unseen/unknown films by measuring them against established anchors.

**Pair selection rule:** One film must be **Ranked** (the anchor). The other is drawn from **Seen -- unranked** or **Unknown** films (the challenger).

- The anchor is weighted toward films in the 900-1100 ELO band (mid-range anchors are most informative).
- The challenger is weighted toward films with `seen=true, battles=0` first (known seen but unranked), then `seen=null` (unknown).
- Never pair two unranked films in Discovery mode.

**Bootstrap exception:** If the user has zero Ranked films (brand new user with no Trakt ratings), run a special bootstrap duel: pick two Seen -- unranked films and let them fight. This produces the first Ranked film, which then becomes the anchor for all future Discovery duels.

### Refinement mode

**Purpose:** Sharpen existing rankings. Battle Ranked films against each other.

**Pair selection rule:** Both films must be **Ranked**.

- Weight toward films with fewer battles (noisier rankings benefit more from refinement).
- Weight toward films with similar ELO (close matchups are more informative than a 1400 vs 600 blowout). Target ELO difference < 200.
- Never pair the same two films twice in the same session.

### Playoff mode

**Purpose:** Run a tournament within a filtered subset of the user's ranked films.

**Pair selection rule:** Both films must be **Ranked**, filtered by a playoff definition (genre, decade, director, custom list).

- Request parameters: `mode=playoff&filter_type=genre&filter_value=horror`
- Supported filter types: `genre`, `decade` (e.g. `1990s`), `director` (Trakt person ID)
- Minimum pool size: 4 films matching the filter. Return an error if fewer than 4 ranked films match.
- Pair selection within playoff: same as Refinement (similar ELO, fewer battles first).

---

## Pair Selection Algorithm

`GET /api/movies/pair?mode=discovery|refinement|playoff&filter_type=...&filter_value=...`

```
function select_pair(user_id, mode, filter):

  if mode == "discovery":
    anchors = user_movies where user_id=user_id, seen=true, battles>=1, elo IS NOT NULL
    if len(anchors) == 0:
      # Bootstrap: first ever duel
      challengers = user_movies where seen=true, battles=0
      if len(challengers) < 2: return error("not enough seen films")
      return pick_two_random(challengers)

    anchor = weighted_sample(anchors, weight_toward_elo_band(900, 1100))
    challengers = user_movies where seen=true, battles=0  (prefer)
                  OR seen=null                             (fallback)
    challenger = weighted_sample(challengers, weight_toward_fewer_battles)
    return (anchor, challenger)

  if mode == "refinement":
    ranked = user_movies where seen=true, battles>=1, elo IS NOT NULL
    if len(ranked) < 2: return error("not enough ranked films")
    film_a = weighted_sample(ranked, weight_toward_fewer_battles)
    film_b = weighted_sample(ranked - {film_a}, weight_toward_similar_elo(film_a))
    return (film_a, film_b)

  if mode == "playoff":
    ranked = user_movies where seen=true, battles>=1, elo IS NOT NULL, matches filter
    if len(ranked) < 4: return error("not enough ranked films for this filter")
    film_a = weighted_sample(ranked, weight_toward_fewer_battles)
    film_b = weighted_sample(ranked - {film_a}, weight_toward_similar_elo(film_a))
    return (film_a, film_b)
```

**Anti-repeat:** The server tracks the last pair served (stored in the session or returned as an opaque `last_pair_token` in the response). The pair selection must not return the same combination of two films consecutively.

---

## Duel Outcomes

`POST /api/duels`

```json
{
  "movie_a_id": "uuid",
  "movie_b_id": "uuid",
  "outcome": "a_wins" | "b_wins" | "a_only" | "b_only" | "neither",
  "mode": "discovery" | "refinement" | "playoff"
}
```

| Outcome | Meaning | ELO update | State changes |
|---|---|---|---|
| `a_wins` | Seen both, prefer A | Update both | Both -> Ranked (if not already) |
| `b_wins` | Seen both, prefer B | Update both | Both -> Ranked (if not already) |
| `a_only` | Only seen A | None | A -> Seen -- unranked (if unknown), B -> Unseen |
| `b_only` | Only seen B | None | B -> Seen -- unranked (if unknown), A -> Unseen |
| `neither` | Seen neither | None | Both -> Unseen |

On `a_wins` or `b_wins`, sync both films' ratings to Trakt asynchronously after updating ELO.

---

## Trakt OAuth2 Flow

### Step 1 -- Redirect to Trakt

`GET /auth/login`

- Build Trakt auth URL: `https://trakt.tv/oauth/authorize?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}`
- Redirect user there

### Step 2 -- Handle callback

`GET /auth/callback?code={code}`

- Exchange code for tokens via `POST https://api.trakt.tv/oauth/token`
- Fetch user profile via `GET https://api.trakt.tv/users/me`
- Upsert user row in `users` table
- Issue a signed JWT (`python-jose` or `PyJWT`) containing `user_id` and expiry
- Set JWT as an httpOnly cookie named `session`
- Redirect to `/`

### Step 3 -- Auth middleware

- FastAPI dependency `get_current_user` reads `session` cookie, validates JWT, returns user row
- All protected routes use this dependency
- If token is missing or invalid, return 401

### Step 4 -- Token refresh

- Before every Trakt API call, check if `trakt_token_expires_at` is within 1 hour
- If so, refresh using `POST https://api.trakt.tv/oauth/token` with `grant_type=refresh_token`
- Update user row with new tokens

### Logout

`POST /auth/logout` -- delete `session` cookie, return 200

---

## Movie Pool

### Sources

**Source 1 -- Trakt popular movies**
- `GET https://api.trakt.tv/movies/popular?limit=100&extended=full`
- Fetch on first login, refresh weekly

**Source 2 -- Trakt trending movies**
- `GET https://api.trakt.tv/movies/trending?limit=100&extended=full`
- Same caching strategy

**Source 3 -- User's Trakt watch history**
- `GET https://api.trakt.tv/users/{username}/watched/movies?extended=full`
- Fetch on first login, sync once per hour per session
- Films from this source: `seen=true` in `user_movies`
- If user has Trakt ratings, also fetch `GET https://api.trakt.tv/users/{username}/ratings/movies` and set `seeded_elo` accordingly

### Pool management

- All sources upserted into shared `movies` table (deduped by `trakt_id`)
- `user_movies` rows created for new films: `seen=null, elo=null, battles=0`
- Films already in watch history: `seen=true`
- Always request `?extended=full` to get `overview`, `runtime`, `genres`, and `ids` (which includes `tmdb` for poster lookup)
- Target pool: ~500 films per user (100 popular + 100 trending + full watch history)

### Poster images

Use TMDB API to fetch poster paths when caching a movie:
`GET https://api.themoviedb.org/3/movie/{tmdb_id}?api_key={TMDB_API_KEY}`

Store the full URL as `https://image.tmdb.org/t/p/w500{poster_path}` in `movies.poster_url`. Fall back to a placeholder if TMDB returns no poster.

---

## API Routes

All routes under `/api`. Auth-protected routes require `session` cookie.

### Auth
```
GET  /auth/login                    Redirect to Trakt OAuth
GET  /auth/callback                 OAuth callback, set cookie, redirect to /
POST /auth/logout                   Clear session cookie
GET  /api/me                        Current user profile and stats
```

### Movies
```
GET  /api/movies/pair               Return a duel pair
     ?mode=discovery|refinement|playoff
     &filter_type=genre|decade|director
     &filter_value=...
     &last_pair_token=...           Opaque token to avoid repeating last pair
```

Response includes full movie objects (id, title, year, genres, overview, poster_url, seen, elo, battles) plus a `next_pair_token` for the anti-repeat mechanism.

### Duels
```
POST /api/duels                     Submit a duel result
```

### Rankings
```
GET  /api/rankings                  Ranked films (seen=true, battles>=1), ELO desc
     ?limit=50&offset=0
     &filter_type=genre&filter_value=horror   (optional, for playoff view)
GET  /api/rankings/export/csv       Letterboxd-compatible CSV download
GET  /api/stats                     Summary stats for the user
```

Stats response:
```json
{
  "total_duels": 142,
  "films_ranked": 67,
  "films_seen_unranked": 12,
  "films_unseen": 31,
  "films_unknown": 389,
  "top_film": { "title": "...", "elo": 1387 }
}
```

---

## Rating Sync to Trakt

After every `a_wins` or `b_wins` outcome, sync both films to Trakt asynchronously (fire-and-forget, do not block the duel response).

```
POST https://api.trakt.tv/sync/ratings
Authorization: Bearer {user_access_token}
trakt-api-version: 2
Content-Type: application/json

{
  "movies": [
    { "rating": 8, "ids": { "trakt": 12345 } },
    { "rating": 6, "ids": { "trakt": 67890 } }
  ]
}
```

Log failures, retry once on 5xx. On 401, trigger token refresh first then retry.

---

## Frontend

React SPA, three pages. Fast and game-like -- the primary interaction should feel snappy.

### Login page (`/login`)

Single button: "Sign in with Trakt". Shown if no valid session cookie.

### Duel page (`/`) -- main screen

Two movie cards side by side with a "vs" divider. Each card shows: poster, title, year, up to 2 genre tags, ELO + battle count if ranked.

Mode selector (tabs or toggle): Discovery / Refinement / Playoff. Playoff mode shows a filter picker (genre, decade).

Action buttons below the cards:
1. **Seen both -- pick a winner** -> cards become tappable, user taps one
2. **Only seen [Film A]**
3. **Only seen [Film B]**
4. **Haven't seen either**

After any action, immediately prefetch the next pair (start fetch on button tap, before animation completes) and animate the new pair in.

Stats bar: `{duels} duels / {ranked} ranked / {unranked} seen / {unknown} to discover`

### Rankings page (`/rankings`)

Ranked films sorted by ELO descending. Shows rank, poster thumbnail, title, year, ELO, battles. Filter by genre/decade for playoff prep. Export to Letterboxd CSV button. Paginated at 50.

### Nav

FilmDuel / Duel / Rankings / {username} + logout

---

## Implementation Phases

1. **Skeleton** -- FastAPI app, SQLAlchemy + Alembic setup, schema migration, Dockerfile, empty React app with Vite + Tailwind, routing
2. **Auth** -- Trakt OAuth2 end-to-end, JWT session cookie, login page, protected route wrapper
3. **Movie Pool** -- Trakt API client (popular, trending, watch history + ratings), movie upsert, TMDB poster fetch, `user_movies` population
4. **Duels + ELO** -- `GET /api/movies/pair` with Discovery mode, `POST /api/duels`, ELO logic (provisional K=64, then K=32), all four action buttons, next-pair prefetch
5. **Sync + Rankings** -- Trakt rating sync, rankings page, CSV export, stats endpoint
6. **Refinement + Playoff modes** -- pair selection for both modes, mode selector in UI, playoff filter picker
7. **Polish** -- Token refresh, error states, loading skeletons, mobile layout, README

---

## Notes for Claude Code

- Use `async/await` throughout -- all DB and HTTP calls are async
- Trakt API requires `Content-Type: application/json` and `trakt-api-version: 2` headers on every request
- Always request `?extended=full` from Trakt to get full movie metadata
- `movies` table is a shared cache -- multiple users share movie rows. `user_movies` is per-user state
- `elo` column on `user_movies` is nullable -- never default to 1000 in the DB or application logic. A film with `battles=0` has no ELO
- `seeded_elo` (from imported Trakt ratings) is used as the starting value for a film's first duel calculation, then discarded in favour of the live `elo` column
- Pair selection must never return a film with `seen=false`
- Store the `mode` on every duel record for future analytics
- All timestamps UTC ISO 8601
