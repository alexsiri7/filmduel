-- FilmDuel initial schema for Supabase (PostgreSQL)

-- Enable UUID generation
create extension if not exists "uuid-ossp";

-- Users table (linked to Trakt accounts)
create table users (
    id uuid primary key default uuid_generate_v4(),
    trakt_username text not null,
    trakt_slug text unique not null,
    trakt_access_token text not null,
    trakt_refresh_token text not null default '',
    avatar_url text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index idx_users_trakt_slug on users(trakt_slug);

-- Movies table (canonical movie records)
create table movies (
    id uuid primary key default uuid_generate_v4(),
    trakt_id integer unique not null,
    tmdb_id integer,
    imdb_id text,
    title text not null,
    year integer,
    poster_url text,
    overview text,
    created_at timestamptz not null default now()
);

create index idx_movies_trakt_id on movies(trakt_id);
create index idx_movies_tmdb_id on movies(tmdb_id);

-- Per-user movie pool (movies available for duels)
create table movie_pool (
    id uuid primary key default uuid_generate_v4(),
    user_id uuid not null references users(id) on delete cascade,
    movie_id uuid not null references movies(id) on delete cascade,
    source text not null default 'popular', -- 'popular', 'trending', 'watched', 'watchlist'
    duel_count integer not null default 0,
    created_at timestamptz not null default now(),
    unique(user_id, movie_id)
);

create index idx_movie_pool_user on movie_pool(user_id);

-- Duels (head-to-head comparisons)
create table duels (
    id uuid primary key default uuid_generate_v4(),
    user_id uuid not null references users(id) on delete cascade,
    movie_a_id uuid not null references movies(id),
    movie_b_id uuid not null references movies(id),
    outcome text, -- 'a_wins', 'b_wins', 'a_only', 'b_only', 'neither'
    status text not null default 'pending', -- 'pending', 'completed'
    created_at timestamptz not null default now(),
    completed_at timestamptz
);

create index idx_duels_user on duels(user_id);
create index idx_duels_status on duels(user_id, status);

-- Rankings (per-user ELO ratings for each movie)
create table rankings (
    id uuid primary key default uuid_generate_v4(),
    user_id uuid not null references users(id) on delete cascade,
    movie_id uuid not null references movies(id) on delete cascade,
    elo_rating double precision not null default 1500.0,
    duel_count integer not null default 0,
    win_count integer not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique(user_id, movie_id)
);

create index idx_rankings_user_elo on rankings(user_id, elo_rating desc);

-- Row-level security policies (enable RLS on all tables)
alter table users enable row level security;
alter table movies enable row level security;
alter table movie_pool enable row level security;
alter table duels enable row level security;
alter table rankings enable row level security;

-- Service role bypasses RLS, so the backend (using service role key) has full access.
-- If you add anon/authenticated access later, add policies here.
