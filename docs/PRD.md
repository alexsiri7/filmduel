# FilmDuel — Product Requirements Document

## Overview

FilmDuel is a web app that helps users discover and rank movies through pairwise comparisons. Users authenticate with their Trakt account, classify films rapidly via a Tinder-style swipe session, then duel seen films against each other to build an ELO-ranked library. Ratings sync back to Trakt in real time.

The experience has two distinct modes that alternate naturally:
- **Swipe** — fast, mindless sorting. Seen it or not?
- **Duel** — deliberate, opinionated ranking. Which do you rate higher?

The experience should feel like a game — fast, opinionated, oddly compelling.

---

## Goals

- Rapidly classify a large film pool as seen/unseen without friction
- Generate meaningful ELO rankings through enjoyable head-to-head duels
- Always show interesting match-ups (good vs good, bad vs bad — not random)
- Surface films the user has forgotten they've seen
- Sync ratings back to Trakt so the data lives somewhere useful
- Export rankings to Letterboxd CSV format

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
- No separate frontend deployment. FastAPI serves the React build from `/static` and catches all non-API routes with a wildcard returning `index.html`.
- No supabase-py SDK — connect directly via `DATABASE_URL` using SQLAlchemy + asyncpg.
- Supabase uses PgBouncer in transaction mode — asyncpg must set `statement_cache_size=0`.
- Branch protection on `main` — all changes via PR. Railway auto-deploys on merge.

### Design Decisions

1. **SQLAlchemy + Alembic over raw Supabase client** — proper ORM, typed models, versioned migrations, no vendor lock-in.
2. **Direct Postgres over Supabase SDK** — full SQLAlchemy power (joins, eager loading, transactions).
3. **Tailwind + shadcn/ui** — polished accessible components, `cn()` utility for conditional classes.
4. **Transaction pooler (port 6543)** — better for short-lived connections. Requires `statement_cache_size=0`.
5. **Sentry from day one** — catch issues immediately after deploy.
6. **SQLAlchemy models separated from Pydantic schemas** — `db_models.py` for ORM, `schemas.py` for request/response. Never conflate.
7. **Swipe phase separated from duel phase** — classification (seen/unseen) and ranking are distinct activities with distinct UIs. Mixing them makes both feel like homework.

---

## Repository Structure

```
filmduel/
├── backend/
│   ├── main.py
│   ├── db_models.py       # SQLAlchemy ORM models
│   ├── schemas.py         # Pydantic request/response models
│   ├── db.py              # SQLAlchemy engine, async session factory
│   ├── config.py          # pydantic-settings from env vars
│   ├── routers/
│   │   ├── auth.py
│   │   ├── swipe.py       # Swipe session: get cards, submit results
│   │   ├── duels.py       # Duel pairs and results
│   │   └── rankings.py    # ELO rankings, CSV export, stats
│   └── services/
│       ├── trakt.py       # Async httpx Trakt API client
│       ├── elo.py         # ELO + K-factor logic
│       ├── pool.py        # Film pool management, pair selection
│       └── sync.py        # Push ratings to Trakt
├── alembic/
│   ├── env.py
│   └── versions/
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── pages/
│   │   │   ├── Login.jsx
│   │   │   ├── Swipe.jsx      # Tinder-style classification
│   │   │   ├── Duel.jsx       # Head-to-head ranking
│   │   │   └── Rankings.jsx
│   │   ├── components/
│   │   │   ├── SwipeCard.jsx
│   │   │   ├── MovieCard.jsx
│   │   │   └── Nav.jsx
│   │   └── api.js
│   ├── package.json
│   └── vite.config.js
├── Dockerfile
├── railway.toml
├── .env.example
└── README.md
```

---

## Environment Variables

```bash
# Database — Supabase Postgres via transaction pooler (port 6543)
DATABASE_URL=postgresql+asyncpg://postgres.PROJECT_REF:PASSWORD@aws-0-REGION.pooler.supabase.com:6543/postgres

# Trakt OAuth2 — https://trakt.tv/oauth/applications
TRAKT_CLIENT_ID=
TRAKT_CLIENT_SECRET=
TRAKT_REDIRECT_URI=https://filmduel.interstellarai.net/auth/callback

# TMDB — https://www.themoviedb.org/settings/api
TMDB_API_KEY=

# Sentry
SENTRY_DSN=

# App
SECRET_KEY=       # openssl rand -hex 32
BASE_URL=https://filmduel.interstellarai.net
```

---

## Database Schema

Managed via Alembic. The SQL below is reference only — do not run manually.

```sql
-- Users
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

-- Shared movie cache
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
  community_rating numeric(4,1),  -- Trakt community score 0-100
  cached_at timestamptz default now()
);

-- Per-user movie state
create table user_movies (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id) on delete cascade,
  movie_id uuid references movies(id) on delete cascade,
  seen boolean,              -- null=unknown, true=seen, false=not seen
  elo integer,               -- NULL until first real duel (seen=true, battles>=1)
  seeded_elo integer,        -- from imported Trakt rating, used as first-duel starting point
  battles integer not null default 0,
  trakt_rating integer,      -- last value synced to Trakt (1-10)
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
  pair_type text not null,   -- 'ranked_vs_ranked' | 'ranked_vs_unranked' | 'ranked_vs_unknown'
  created_at timestamptz default now()
);

-- Swipe history
create table swipe_results (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id) on delete cascade,
  movie_id uuid references movies(id) on delete cascade,
  seen boolean not null,
  created_at timestamptz default now()
);

-- Indexes
create index on user_movies(user_id);
create index on user_movies(user_id, seen);
create index on user_movies(user_id, elo desc) where elo is not null;
create index on user_movies(user_id, seen, battles) where seen = true;
create index on duels(user_id);
create index on swipe_results(user_id);
```

---

## Film State Model

| State | `seen` | `battles` | `elo` | Participates in |
|---|---|---|---|---|
| **Unknown** | `null` | `0` | `null` | Swipe sessions only |
| **Unseen** | `false` | any | `null` | Never shown again |
| **Seen — unranked** | `true` | `0` | `null` | Duel as challenger |
| **Ranked** | `true` | `≥1` | integer | Duel as anchor or challenger |

**Critical rules:**
- `elo` is `NULL` until `seen=true AND battles≥1`. DB default is `NULL`, not 1000.
- `seen=false` films never appear in swipe or duel again.
- Rankings page only shows `seen=true AND battles≥1`.
- Films from Trakt watch history import as Seen — unranked.
- Films with existing Trakt ratings get a `seeded_elo` but still have `battles=0` and `elo=NULL` until their first duel.

---

## Core Game Loop

```
On first login:
  1. Import Trakt watch history → mark as seen=true
  2. Import Trakt ratings → set seeded_elo
  3. Always start with a Swipe Session (10 cards)
  4. After swipe: enter Duel Loop

Duel Loop:
  - Select pair using weighted selection (see Duel Pair Selection below)
  - After each duel result: backend returns next_action
  - If next_action == "swipe": frontend shows swipe interstitial before next duel
  - Otherwise: animate next pair in immediately

next_action logic (evaluated server-side after every duel):
  - seen_unranked = count(user_movies where seen=true, battles=0)
  - If seen_unranked < 3: next_action = "swipe"
  - Else: next_action = "duel"

Swipe Session:
  - Show 10 films one at a time, full poster, swipe or tap seen/not seen
  - Films drawn from Unknown pool, weighted by community rating band
  - Progress indicator: 3 / 10
  - On completion: show summary ("You've seen 6 of these") then return to duel
```

The loop is **organic, not staged**. There is no "finish introducing all unranked films before refining" — every duel draw comes from a single weighted pool that naturally balances new introductions against refinement based on how settled each film's ranking is. Swipe sessions feed that pool on demand rather than on a fixed schedule.

---

## Swipe Session

### Film selection for swipe

Draw from `user_movies where seen IS NULL`. Weight by community rating band to match the user's established taste:

1. Find user's median ELO across all ranked films (default 1000 if no ranked films)
2. Map median ELO to a quality band (see table below)
3. 60% of cards from that band, 20% from band above, 20% from band below

### Swipe API

```
GET  /api/swipe/cards          Returns 10 unknown films
POST /api/swipe/results        Submit all 10 results in one call
```

Swipe results body:
```json
{
  "results": [
    { "movie_id": "uuid", "seen": true },
    { "movie_id": "uuid", "seen": false }
  ]
}
```

On submission: bulk upsert all 10 `user_movies.seen` values in a single query. Return:
```json
{ "seen_count": 6, "unseen_count": 4 }
```

The swipe interstitial is triggered by `next_action: "swipe"` in the duel result response — not by a separate polling endpoint. Remove `/api/swipe/status`.

---

## ELO System

### Quality bands

| Band | ELO range | Community rating |
|---|---|---|
| Elite | 1300+ | 80–100 |
| Strong | 1100–1299 | 65–79 |
| Mid | 900–1099 | 45–64 |
| Weak | 700–899 | 25–44 |
| Poor | <700 | 0–24 |

### ELO column behaviour

- `elo` is `NULL` for Unknown, Unseen, and Seen — unranked films.
- On a film's first duel: use `seeded_elo` if available, otherwise 1000 as bootstrap value for that calculation only.
- After first duel: `elo` is always a real integer updated on every subsequent duel.

### K-factor

K=64 for first 5 battles (provisional), K=32 thereafter.

```python
def k_factor(battles: int) -> int:
    return 64 if battles < 5 else 32

def expected_score(rating_a: int, rating_b: int) -> float:
    return 1 / (1 + 10 ** ((rating_b - rating_a) / 400))

def update_elo(winner_elo: int, loser_elo: int,
               winner_battles: int, loser_battles: int) -> tuple[int, int]:
    exp = expected_score(winner_elo, loser_elo)
    new_winner = round(winner_elo + k_factor(winner_battles) * (1 - exp))
    new_loser  = round(loser_elo  + k_factor(loser_battles)  * (0 - (1 - exp)))
    return new_winner, new_loser
```

### ELO → Trakt rating

```python
trakt_rating = max(1, min(10, round((elo - 600) * 9 / 800) + 1))
```

---

## Duel Pair Selection

### Philosophy

The pair selection is a **single weighted pool** — not discrete stages with shifting ratios. Every seen film has a weight based on how settled its ranking is. Films that need more duels naturally get selected more often. New films entering the pool (from swipe sessions) automatically compete for selection without any special-casing.

This produces a living ranking that is always refining itself, with new films trickling in continuously rather than being processed in batches.

### Settlement weight

Every seen film (`seen=true`) gets a selection weight:

```python
weight = 1 / (battles + 1)
```

| Battles | Weight | Meaning |
|---|---|---|
| 0 | 1.000 | Unranked — highest priority |
| 1 | 0.500 | Very noisy — high priority |
| 4 | 0.200 | Settling — medium priority |
| 9 | 0.100 | Stable — low priority |
| 19 | 0.050 | Settled — occasional calibration |

A film with 0 battles is selected 10× more often than one with 9 battles. This ensures new films get introduced quickly while established films keep getting refined — without either dominating.

### Anchor rule

Every duel must include at least one **anchor** — a film with `battles ≥ 1` and a real ELO. This gives the challenger a reference point and keeps duels meaningful.

- Draw film A from all seen films using settlement weights, **excluding `battles=0`** (anchor pool)
- Draw film B from all seen films using settlement weights, **including `battles=0`** (full pool minus A)

If the anchor pool is empty (no film has been dueled yet — bootstrap state): draw both from `seen=true, battles=0` films, matched by community rating band. The first duel is the only exception to the anchor rule.

### Quality band matching

After selecting the anchor (film A), constrain film B to the same community rating band as A's current ELO band. This enforces good-vs-good and bad-vs-bad matchups.

```python
def elo_to_band(elo: int | None) -> str:
    if elo is None: return "mid"      # unranked films use community_rating directly
    if elo >= 1300: return "elite"
    if elo >= 1100: return "strong"
    if elo >= 900:  return "mid"
    if elo >= 700:  return "weak"
    return "poor"

def community_rating_to_band(rating: float | None) -> str:
    if rating is None: return "mid"
    if rating >= 80: return "elite"
    if rating >= 65: return "strong"
    if rating >= 45: return "mid"
    if rating >= 25: return "weak"
    return "poor"
```

For film B:
- If `battles ≥ 1`: match on `elo_to_band(b.elo) == elo_to_band(a.elo)`
- If `battles == 0`: match on `community_rating_to_band(b.community_rating) == elo_to_band(a.elo)`

If no film in the target band is available, expand to adjacent bands (±1 step).

### Match distance variation

Within same-band ranked-vs-ranked pairs, vary the ELO distance to produce both refinement and sanity-check duels:

- 70% **close matches** (ELO diff < 150) — resolves genuine toss-ups
- 30% **wide matches** (ELO diff > 300) — catches films that drifted to wrong tier

Apply this only when both films have `battles ≥ 1`. For introductory duels (B has `battles=0`), distance variation doesn't apply.

### Algorithm

```python
def select_duel_pair(user_id, last_pair=None):
    seen_films = query(user_movies, user_id=user_id, seen=True)

    anchor_pool    = [f for f in seen_films if f.battles >= 1]
    full_pool      = seen_films  # all seen films

    # Bootstrap: no anchors yet
    if len(anchor_pool) == 0:
        if len(full_pool) < 2:
            return signal("swipe_needed")
        a, b = pick_two_by_community_rating(full_pool)
        return (a, b)

    # Select anchor (film A) — weighted, battles >= 1 only
    a = weighted_sample(anchor_pool, weight_fn=lambda f: 1/(f.battles+1))

    # Determine match distance for same-band ranked pairs
    use_close = random() < 0.70

    # Select challenger (film B) — weighted, full pool, same band as A
    target_band = elo_to_band(a.elo)
    candidates = [f for f in full_pool if f.id != a.id and band_matches(f, target_band)]

    if len(candidates) == 0:
        # Expand to adjacent bands
        candidates = [f for f in full_pool if f.id != a.id]

    if use_close and all(f.battles >= 1 for f in candidates):
        # Prefer close ELO match
        candidates.sort(key=lambda f: abs(f.elo - a.elo))
        b = weighted_sample(candidates[:10], weight_fn=lambda f: 1/(f.battles+1))
    else:
        b = weighted_sample(candidates, weight_fn=lambda f: 1/(f.battles+1))

    # Anti-repeat
    if last_pair and {a.id, b.id} == set(last_pair):
        candidates = [f for f in candidates if f.id != b.id]
        b = weighted_sample(candidates, weight_fn=lambda f: 1/(f.battles+1))

    pair_type = classify_pair(a, b)  # for analytics
    return (a, b, pair_type)
```

### Pair type (for analytics only)

Still store on the `duels` table for future analysis, but it's derived from the result, not used to drive selection:

- `ranked_vs_ranked` — both `battles ≥ 1`
- `ranked_vs_unranked` — A has `battles ≥ 1`, B has `battles = 0`

### Swipe refill trigger

Evaluated server-side after every duel submission. Included in the duel result response as `next_action`:

```python
seen_unranked = count(user_movies, user_id=user_id, seen=True, battles=0)
next_action = "swipe" if seen_unranked < 3 else "duel"
```

Frontend shows the swipe interstitial between duels when `next_action == "swipe"`. Never interrupts mid-duel.

---

## Duel Outcomes

```
POST /api/duels
{
  "movie_a_id": "uuid",
  "movie_b_id": "uuid",
  "outcome": "a_wins" | "b_wins" | "a_only" | "b_only" | "neither",
  "pair_type": "ranked_vs_ranked" | "ranked_vs_unranked" | "ranked_vs_unknown"
}
```

| Outcome | ELO update | State changes |
|---|---|---|
| `a_wins` | Update both | Both → Ranked |
| `b_wins` | Update both | Both → Ranked |
| `a_only` | None | A → Seen — unranked; B → Unseen |
| `b_only` | None | B → Seen — unranked; A → Unseen |
| `neither` | None | Both → Unseen |

On `a_wins` or `b_wins`: sync both films to Trakt asynchronously.

---

## Movie Pool

### Sources

| # | Endpoint | Refresh | Notes |
|---|---|---|---|
| 1 | `GET /movies/popular?limit=100&extended=full` | Weekly | Broad well-known pool |
| 2 | `GET /movies/trending?limit=100&extended=full` | Weekly | Recent/buzzy |
| 3 | `GET /users/{u}/watched/movies?extended=full` | Hourly | User history → `seen=true` |
| 4 | `GET /movies/recommended?extended=full` | Daily | Personalised, authenticated |
| 5 | `GET /users/{u}/ratings/movies` | On login | Sets `seeded_elo` |

- Always `?extended=full` for overview, runtime, genres, ids.tmdb, community rating
- `community_rating`: Trakt's `rating` field is 0–10, store as `rating * 10` (0–100 scale)
- TMDB poster: `GET https://api.themoviedb.org/3/movie/{tmdb_id}?api_key=...` → store `https://image.tmdb.org/t/p/w500{poster_path}`

---

## Trakt OAuth2 Flow

**Login:** `GET /auth/login` → redirect to Trakt authorize URL

**Callback:** `GET /auth/callback?code=...`
- Exchange code for tokens
- Fetch `/users/me`
- Upsert user row, issue JWT, set httpOnly `session` cookie, redirect to `/`

**Middleware:** `get_current_user` dependency reads `session` cookie, validates JWT, returns user. Returns 401 if invalid.

**Token refresh:** Before every Trakt call, if token expires within 1 hour: refresh and update user row.

**Logout:** `POST /auth/logout` → delete cookie.

---

## API Routes

```
GET  /auth/login
GET  /auth/callback
POST /auth/logout
GET  /api/me

GET  /api/swipe/cards
POST /api/swipe/results

GET  /api/duels/pair?last_pair_token=...
POST /api/duels

GET  /api/rankings?limit=50&offset=0&genre=...&decade=...
GET  /api/rankings/export/csv
GET  /api/stats
```

`POST /api/duels` response includes `next_action: "duel" | "swipe"` — the frontend uses this to decide whether to show the swipe interstitial before fetching the next pair. No separate status polling endpoint.

---

## Rating Sync to Trakt

Fire-and-forget after every `a_wins` or `b_wins`.

```
POST https://api.trakt.tv/sync/ratings
Authorization: Bearer {token}
trakt-api-version: 2

{ "movies": [{ "rating": 8, "ids": { "trakt": 12345 } }] }
```

Retry once on 5xx. On 401: refresh token then retry. Log failures to Sentry.

---

## Frontend

React SPA. Four screens.

### Login (`/login`)
Full screen. Logo (large amber). Wordmark. Single CTA: "Sign in with Trakt" (amber pill). Tagline: "Rate films. Rank everything." Minimal dark. Film title card energy.

### Swipe (`/swipe`)
Single full-screen poster card. Title, year, genre pill overlaid at bottom. Two large buttons: "Seen it" (amber) / "Never seen it" (ghost). Progress counter: `4 / 10`. Gesture: swipe right = seen, swipe left = not seen (80px drag threshold). After 10: summary screen showing seen/unseen counts, CTA to start dueling.

### Duel (`/`)
Two tall poster cards side by side. Coral "vs" badge between them. Title, year, genres on each card. ELO + battle count shown if ranked. Four action buttons below:
1. "I've seen both — pick a winner" (amber, primary) → cards become tappable
2. "Only seen [Film A]" (outline)
3. "Only seen [Film B]" (outline)
4. "Haven't seen either" (muted)

After action: prefetch next pair immediately (start on button tap), animate transition. Stats bar: `{duels} duels · {ranked} ranked · {unranked} to rank · {unknown} to discover`. When duel result returns `next_action: "swipe"`: show swipe interstitial between duels — "Time to discover more films" + "Swipe 10 films" CTA. Never interrupt mid-duel.

### Rankings (`/rankings`)
Leaderboard. Filter pills: All · Genre · Decade. Row: rank number (large amber display font), poster thumbnail, title + year, ELO, battles. Top film gets amber left accent. Floating "Export to Letterboxd" button. Paginated at 50.

---

## Implementation Phases

1. **Skeleton** — FastAPI, SQLAlchemy + Alembic, schema, Dockerfile, empty React + Vite + Tailwind
2. **Auth** — Trakt OAuth2, JWT cookie, login page, route protection
3. **Movie Pool** — Trakt client (all 5 sources), upsert, TMDB posters, community rating
4. **Swipe** — `/api/swipe/cards` + `/api/swipe/results` + `/api/swipe/status`, Swipe page with gestures, progress, summary
5. **Duels + ELO** — pair selection with blend ratios, `/api/duels/pair`, `POST /api/duels`, ELO logic, duel UI, prefetch, swipe interstitial
6. **Sync + Rankings** — Trakt sync, rankings page, CSV export, stats
7. **Polish** — token refresh, error states, skeletons, mobile layout, README

---

## Notes for Claude Code

- `async/await` throughout — all DB and HTTP calls are async
- Trakt requires `Content-Type: application/json` and `trakt-api-version: 2` on every request
- Always `?extended=full` from Trakt
- `movies` is a shared cache. `user_movies` is per-user state
- `elo` is nullable — never default to 1000. No ELO until `battles≥1`
- `seeded_elo` used only as starting point for first duel, then `elo` takes over
- `community_rating` = Trakt `rating` field × 10 (stored as 0–100)
- Swipe results: single bulk upsert, not 10 individual queries
- `next_action` is computed server-side after every `POST /api/duels` — check `count(seen=true, battles=0) < 3`
- There is no `/api/swipe/status` endpoint — swipe trigger is embedded in duel result response
- Pair selection uses `weight = 1/(battles+1)` — never blend ratios or staged modes
- Pair selection never returns `seen=false` films
- Store `pair_type` on every duel record (derived from result, not used for selection)
- Swipe gesture: CSS transform + transition, 80px horizontal threshold
- All timestamps UTC ISO 8601
