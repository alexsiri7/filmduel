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
| ORM | SQLAlchemy 2.0 (async, declarative mapped_column style) |
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

---

## Repository Structure

```
filmduel/
├── backend/
│   ├── main.py            # FastAPI app, mounts static, registers routers
│   ├── routers/
│   │   ├── auth.py        # Trakt OAuth routes
│   │   ├── movies.py      # Movie pool, duel pair generation
│   │   ├── duels.py       # Submit duel results
│   │   └── rankings.py    # Fetch ELO rankings, export CSV
│   ├── services/
│   │   ├── trakt.py       # Trakt API client (async httpx)
│   │   ├── elo.py         # ELO calculation logic
│   │   └── sync.py        # Push ratings to Trakt
│   ├── db.py              # Supabase client initialisation
│   ├── models.py          # Pydantic models
│   └── config.py          # Settings from environment variables
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

Run these migrations via Supabase SQL editor or a migration file. No ORM — use the Supabase client directly with raw queries where needed, or the Supabase Python client's table API.

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

-- Movies (local cache of Trakt movie data)
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
  seen boolean,
  elo integer not null default 1000,
  battles integer not null default 0,
  trakt_rating integer,
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
  created_at timestamptz default now()
);

-- Indexes
create index on user_movies(user_id);
create index on user_movies(user_id, seen);
create index on user_movies(user_id, elo desc);
create index on duels(user_id);
```

---

## Trakt OAuth2 Flow

Trakt uses standard Authorization Code flow.

### Step 1 — Redirect to Trakt
`GET /auth/login`
- Build Trakt auth URL: `https://trakt.tv/oauth/authorize?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}`
- Redirect user there

### Step 2 — Handle callback
`GET /auth/callback?code={code}`
- Exchange code for tokens via `POST https://api.trakt.tv/oauth/token`
- Fetch user profile via `GET https://api.trakt.tv/users/me`
- Upsert user row in `users` table
- Issue a signed JWT (use `python-jose` or `PyJWT`) containing `user_id` and expiry
- Set JWT as an httpOnly cookie named `session`
- Redirect to `/` (frontend)

### Step 3 — Auth middleware
- FastAPI dependency `get_current_user` reads `session` cookie, validates JWT, returns user row
- All protected routes use this dependency
- If token is missing or invalid, return 401

### Step 4 — Token refresh
- Before every Trakt API call, check if `trakt_token_expires_at` is within 1 hour
- If so, refresh using `POST https://api.trakt.tv/oauth/token` with `grant_type=refresh_token`
- Update user row with new tokens

### Logout
`POST /auth/logout`
- Delete the `session` cookie
- Return 200

---

## Movie Pool

The pool of movies shown in duels is built from three sources, merged and deduplicated by `trakt_id`.

### Source 1 — Trakt popular movies
- `GET https://api.trakt.tv/movies/popular?limit=100`
- Fetch on user's first login and refresh weekly (store `cached_at` on movies table)
- Gives well-known films that most users will have seen some of

### Source 2 — Trakt trending movies
- `GET https://api.trakt.tv/movies/trending?limit=100`
- Same caching strategy
- Gives recent/buzzy films

### Source 3 — User's Trakt watch history
- `GET https://api.trakt.tv/users/{username}/watched/movies`
- Fetch on first login and sync on each session start (throttle to once per hour)
- These films are pre-marked `seen = true` in `user_movies`
- If the user has Trakt ratings, import those and set initial ELO accordingly

### Pool management
- All three sources are upserted into the `movies` table on fetch
- `user_movies` rows are created with `seen = null` for any movie not already in the user's history
- Target pool size: ~500 movies per user (top 100 popular + 100 trending + all watched history)
- When building a duel pair, query the user's `user_movies` for movies with `seen IS NULL OR seen = true`

---

## ELO System

### Initial ELO
- Default: 1000
- If user has an existing Trakt rating (1–10) for a film, convert to starting ELO:
  - `starting_elo = 600 + (trakt_rating - 1) * (800 / 9)`
  - This maps 1→600, 5.5→1000, 10→1400

### ELO calculation
Standard ELO with K=32:

```python
def expected_score(rating_a: int, rating_b: int) -> float:
    return 1 / (1 + 10 ** ((rating_b - rating_a) / 400))

def update_elo(winner_elo: int, loser_elo: int, k: int = 32) -> tuple[int, int]:
    exp = expected_score(winner_elo, loser_elo)
    new_winner = round(winner_elo + k * (1 - exp))
    new_loser = round(loser_elo + k * (0 - (1 - exp)))
    return new_winner, new_loser
```

### ELO → Trakt rating conversion
Map ELO back to Trakt's 1–10 scale:
`trakt_rating = max(1, min(10, round((elo - 600) * 9 / 800) + 1))`

---

## API Routes

All routes under `/api`. Auth-protected routes require `session` cookie.

### Auth
```
GET  /auth/login           Redirect to Trakt OAuth
GET  /auth/callback        OAuth callback, set cookie, redirect to /
POST /auth/logout          Clear session cookie
GET  /api/me               Return current user profile (username, stats)
```

### Movie Pool
```
GET  /api/movies/pair      Returns a pair of movies for dueling
```

### Duels
```
POST /api/duels            Submit a duel result
```

Body:
```json
{
  "movie_a_id": "uuid",
  "movie_b_id": "uuid",
  "outcome": "a_wins" | "b_wins" | "a_only" | "b_only" | "neither"
}
```

### Rankings
```
GET  /api/rankings?limit=100&offset=0    Paginated ELO rankings
GET  /api/rankings/export/csv            Letterboxd CSV export
GET  /api/stats                          User stats summary
```

---

## Rating Sync to Trakt

After every `a_wins` or `b_wins` outcome, sync both films' ratings to Trakt asynchronously (fire-and-forget, don't block the response).

Log failures but don't surface them to the user. Retry once on 5xx. On 401, trigger token refresh first.

---

## Frontend

React SPA with three pages.

### Login page (`/login`)
- Single button: "Sign in with Trakt"

### Duel page (`/`) — main screen
- Two movie cards side by side with "vs" divider
- Four action buttons: pick winner (seen both), only seen A, only seen B, neither
- Stats bar: duels · ranked · unseen

### Rankings page (`/rankings`)
- Sorted list by ELO descending
- Export to Letterboxd CSV button
- Paginated (50 at a time)

---

## Implementation Phases

1. **Skeleton** — FastAPI app, Supabase init, schema, Dockerfile, empty React
2. **Auth** — Trakt OAuth2, JWT, login page, protected routes
3. **Movie Pool** — Trakt client, movie upsert, pair generation, duel page cards
4. **Duels + ELO** — Duel submission, ELO updates, action buttons
5. **Sync + Rankings** — Trakt sync, rankings page, CSV export, stats
6. **Polish** — Token refresh, error states, loading states, mobile responsive
