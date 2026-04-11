# FilmDuel

Rank your movies through head-to-head duels. Powered by ELO ratings, Trakt integration, and TMDB posters.

## Stack

- **Backend**: FastAPI + SQLAlchemy 2.0 (async) + Alembic + Trakt OAuth2
- **Database**: PostgreSQL (Supabase via direct connection string)
- **Frontend**: React 18 + Vite + Tailwind CSS + shadcn/ui
- **Hosting**: Railway (Docker)

---

## Quick Setup

### Prerequisites

- Python 3.12+
- Node.js 20+
- A PostgreSQL database (e.g. [Supabase](https://supabase.com))
- A [Trakt](https://trakt.tv/oauth/applications) OAuth application
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

Fill in every value in `.env`:

| Variable | Description |
|---|---|
| `TRAKT_CLIENT_ID` | From your Trakt OAuth app |
| `TRAKT_CLIENT_SECRET` | From your Trakt OAuth app |
| `TRAKT_REDIRECT_URI` | Must match the redirect URI in your Trakt app (`http://localhost:8000/api/auth/callback` for local dev) |
| `SUPABASE_URL` | Your Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role key (bypasses RLS — keep secret) |
| `SECRET_KEY` | Random 32-byte hex string: `openssl rand -hex 32` |
| `BASE_URL` | Where the app is hosted (`http://localhost:8000` locally) |
| `TMDB_API_KEY` | Used for movie poster images |

### 3. Backend

```bash
uvicorn backend.main:app --reload
```

The API is now at `http://localhost:8000`.

### 4. Frontend

```bash
cd frontend
npm install
npm run dev
```

The dev server runs at `http://localhost:5173` and proxies `/api` requests to the backend.

### 5. Docker (production)

```bash
docker build -t filmduel .
docker run -p 8000:8000 --env-file .env filmduel
```

Alembic migrations run automatically on container start.

---

## Deploy to Railway

1. Push this repo to GitHub.
2. Create a new Railway project, connect the repo.
3. Set all environment variables from `.env.example` in the Railway dashboard.
4. Railway detects the `Dockerfile` and builds automatically.
5. Set `TRAKT_REDIRECT_URI` and `BASE_URL` to your Railway app URL (e.g. `https://filmduel.up.railway.app`).
6. Update the redirect URI in your Trakt OAuth app to match.

---

## How It Works

1. **Sign in** with your Trakt account via OAuth2.
2. **Movie pool** is built from Trakt popular/trending lists + your personal watch history.
3. **Duel** — you're shown two movies at a time. Pick the one you prefer, mark them seen/unseen, or skip both.
4. **ELO** updates after each decisive duel (K=32, default rating 1000).
5. **Rankings** — view your sorted list and export as a Letterboxd-compatible CSV.
6. **Trakt sync** — after each win/loss duel, ratings are pushed back to Trakt on a 1-10 scale.

### Token Refresh

Trakt access tokens expire after 90 days. FilmDuel automatically refreshes the token when it has less than 1 hour remaining, so you stay logged in seamlessly.
