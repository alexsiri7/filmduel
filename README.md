# FilmDuel

Rank your movies through head-to-head duels. Powered by ELO ratings, Trakt integration, and TMDB posters.

## Stack

- **Backend**: FastAPI + Supabase + Trakt OAuth
- **Frontend**: React + Vite
- **Hosting**: Railway (Docker)

## Setup

### Prerequisites

- Python 3.12+
- Node.js 20+
- A [Supabase](https://supabase.com) project
- A [Trakt](https://trakt.tv/oauth/applications) OAuth application
- A [TMDB](https://www.themoviedb.org/settings/api) API key

### 1. Database

Run the migration against your Supabase project:

```sql
-- Copy contents of migrations/001_initial_schema.sql into the Supabase SQL editor
```

### 2. Environment

```bash
cp .env.example .env
# Fill in all values
```

### 3. Backend

```bash
cd backend
pip install -r requirements.txt
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

## How It Works

1. Sign in with your Trakt account
2. Movies are pulled from Trakt popular/trending lists + your watch history
3. You're shown two movies at a time — pick the one you prefer
4. ELO ratings update after each duel (K=32)
5. View your ranked list and export as Letterboxd-compatible CSV
6. Ratings can be synced back to Trakt on a 1-10 scale
