# FilmDuel

Rank your movies and TV shows through head-to-head duels. Powered by ELO ratings, Trakt integration, and TMDB posters.

## Stack

- **Backend**: FastAPI + SQLAlchemy 2.0 (async) + Alembic + Trakt OAuth2
- **Database**: PostgreSQL (Supabase via direct connection string)
- **Frontend**: React 18 + Vite + Tailwind CSS + shadcn/ui
- **Hosting**: Railway (Docker)

## Setup

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

## How It Works

1. Sign in with your Trakt account
2. Movies are pulled from Trakt popular/trending lists + your watch history
3. You're shown two movies at a time — pick the one you prefer
4. ELO ratings update after each duel (K=32, default 1000)
5. View your ranked list and export as Letterboxd-compatible CSV
6. Ratings sync back to Trakt on a 1-10 scale
