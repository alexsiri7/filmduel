# FilmDuel

Rank your movies and TV shows through head-to-head duels. Powered by ELO ratings, Trakt integration, and TMDB posters.

## Stack

- **Backend**: FastAPI + SQLAlchemy 2.0 (async) + Alembic + Trakt OAuth2, SIMKL OAuth2
- **Database**: PostgreSQL (Supabase via direct connection string)
- **Frontend**: React 18 + Vite + Tailwind CSS + shadcn/ui
- **Hosting**: Railway (Docker)

## Setup

### Prerequisites

- Python 3.14 (the hash-locked `backend/requirements*.txt` are compiled for 3.14)
- Node.js 26 (matches the Docker build and CI)
- A PostgreSQL database (e.g. [Supabase](https://supabase.com))
- A [Trakt](https://trakt.tv/oauth/applications) OAuth application
- _(Optional)_ A [SIMKL](https://simkl.com/settings/developer) OAuth application
- A [TMDB](https://www.themoviedb.org/settings/api) API key

### 1. Environment

```bash
cp .env.example .env
# Fill in DATABASE_URL and all other values
```

### 2. Database Migrations

```bash
pip install -r backend/requirements.txt
alembic upgrade head
```

### 3. Backend

```bash
uvicorn backend.main:app --reload
```

### 4. Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend dev server proxies `/api` requests to the backend at `localhost:8000`.

### 5. Docker (production)

```bash
docker build -t filmduel .
docker run -p 8000:8000 --env-file .env filmduel
```

Alembic migrations run automatically on container start.

> **Reverse proxy deployments** (Railway, nginx, etc.): set `FORWARDED_ALLOW_IPS` and
> `SECURE_COOKIES=true` in your `.env` — see `.env.example` for details. Without
> `FORWARDED_ALLOW_IPS`, rate limiting will not correctly identify client IPs. On Railway,
> Render, Fly.io, Heroku and Cloud Run the app refuses to start when `SECURE_COOKIES` is
> unset and `BASE_URL` is not `https://`; on other proxies (nginx etc.) it cannot detect the
> proxy and will silently issue session cookies without the Secure flag (and without the
> `__Host-` prefix), so set `SECURE_COOKIES=true` there too. Without
> `RATE_LIMIT_STORAGE_URI`, rate limits are per-process and reset on every deploy — point it
> at a Redis instance to make them durable and shared across replicas.

## How It Works

1. Sign in with your Trakt account
2. Accept the privacy policy (first-time only)
3. Toggle between **Movies** and **TV Shows** using the nav bar
4. Content is pulled from Trakt popular/trending lists + your watch history
5. You're shown two titles at a time — pick the one you rate higher
6. ELO ratings update after each duel (K=32, default 1000)
7. View your ranked list and export as Letterboxd-compatible CSV
8. Ratings sync back to Trakt on a 1-10 scale
9. Toggle AI Suggestions on/off from the nav settings panel (on by default) — disabling it hides the suggestions page and AI-curated tournament options
