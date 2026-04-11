"""Movie pair generation endpoint — Discovery mode pair selection."""

from __future__ import annotations

import base64
import random
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from backend.db import get_db
from backend.db_models import Movie, User, UserMovie
from backend.schemas import MovieWithStateSchema, MoviePairResponse
from backend.routers.auth import get_current_user

router = APIRouter(prefix="/api/movies", tags=["movies"])


def _user_movie_to_schema(um: UserMovie) -> MovieWithStateSchema:
    """Convert a UserMovie (with loaded movie relationship) to response schema."""
    movie = um.movie
    return MovieWithStateSchema(
        id=str(movie.id),
        trakt_id=movie.trakt_id,
        tmdb_id=movie.tmdb_id,
        imdb_id=movie.imdb_id,
        title=movie.title,
        year=movie.year,
        poster_url=movie.poster_url,
        overview=movie.overview,
        genres=movie.genres,
        seen=um.seen,
        elo=um.elo,
        battles=um.battles,
    )


def _encode_pair_token(id_a: str, id_b: str) -> str:
    """Encode a pair of movie IDs into an opaque base64 token."""
    raw = f"{id_a},{id_b}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_pair_token(token: str) -> set[str] | None:
    """Decode a pair token back into a set of two movie ID strings."""
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        parts = raw.split(",")
        if len(parts) == 2:
            return {parts[0], parts[1]}
    except Exception:
        pass
    return None


def _pick_anchor(ranked: list[UserMovie]) -> UserMovie:
    """Pick an anchor weighted toward the 900-1100 ELO band."""
    weights = []
    for um in ranked:
        elo = um.elo or 1000
        # Gaussian-ish weight centered on 1000, sigma ~100
        dist = abs(elo - 1000)
        weight = max(0.1, 1.0 / (1 + (dist / 100) ** 2))
        weights.append(weight)
    return random.choices(ranked, weights=weights, k=1)[0]


def _pick_challenger(
    challengers: list[UserMovie], exclude_id: str
) -> UserMovie | None:
    """Pick a challenger weighted toward fewer battles, excluding a movie ID."""
    filtered = [um for um in challengers if str(um.movie_id) != exclude_id]
    if not filtered:
        return None
    weights = [1.0 / (1 + um.battles) for um in filtered]
    return random.choices(filtered, weights=weights, k=1)[0]


@router.get("/pair", response_model=MoviePairResponse)
async def get_movie_pair(
    mode: str = Query(default="discovery"),
    last_pair_token: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a pair of movies for a duel.

    Discovery mode (default):
    - Picks one Ranked anchor (weighted toward 900-1100 ELO) and one challenger
      from Seen-unranked or Unknown films.
    - Bootstrap: if no Ranked films, picks two random Seen-unranked films.
    - Anti-repeat via last_pair_token.
    """
    uid = current_user.id

    # Decode anti-repeat token
    last_pair_ids: set[str] | None = None
    if last_pair_token:
        last_pair_ids = _decode_pair_token(last_pair_token)

    if mode == "discovery":
        pair = await _select_discovery_pair(db, uid, last_pair_ids)
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported mode: {mode}. Only 'discovery' is implemented.",
        )

    movie_a, movie_b = pair
    schema_a = _user_movie_to_schema(movie_a)
    schema_b = _user_movie_to_schema(movie_b)
    token = _encode_pair_token(str(movie_a.movie_id), str(movie_b.movie_id))

    return MoviePairResponse(
        movie_a=schema_a,
        movie_b=schema_b,
        next_pair_token=token,
    )


async def _select_discovery_pair(
    db: AsyncSession,
    uid,
    last_pair_ids: set[str] | None,
) -> tuple[UserMovie, UserMovie]:
    """Discovery mode pair selection per PRD algorithm."""

    # 1. Query Ranked films: seen=True, battles>=1, elo IS NOT NULL
    ranked_stmt = (
        select(UserMovie)
        .options(joinedload(UserMovie.movie))
        .where(
            UserMovie.user_id == uid,
            UserMovie.seen.is_(True),
            UserMovie.battles >= 1,
            UserMovie.elo.isnot(None),
        )
    )
    ranked_result = await db.execute(ranked_stmt)
    ranked = list(ranked_result.unique().scalars().all())

    # 2. Bootstrap: zero ranked films — pick two random Seen-unranked
    if len(ranked) == 0:
        return await _bootstrap_pair(db, uid, last_pair_ids)

    # 3. Normal discovery: anchor + challenger
    # Query Seen-unranked (preferred challengers)
    seen_unranked_stmt = (
        select(UserMovie)
        .options(joinedload(UserMovie.movie))
        .where(
            UserMovie.user_id == uid,
            UserMovie.seen.is_(True),
            UserMovie.battles == 0,
        )
    )
    seen_unranked_result = await db.execute(seen_unranked_stmt)
    seen_unranked = list(seen_unranked_result.unique().scalars().all())

    # Query Unknown (fallback challengers)
    unknown_stmt = (
        select(UserMovie)
        .options(joinedload(UserMovie.movie))
        .where(
            UserMovie.user_id == uid,
            UserMovie.seen.is_(None),
        )
    )
    unknown_result = await db.execute(unknown_stmt)
    unknown = list(unknown_result.unique().scalars().all())

    # Combine challengers: seen-unranked first, then unknown
    all_challengers = seen_unranked + unknown

    if not all_challengers:
        raise HTTPException(
            status_code=404,
            detail="No challenger films available. All films are already ranked!",
        )

    # Try up to 5 times to avoid repeating last pair
    for _ in range(5):
        anchor = _pick_anchor(ranked)
        challenger = _pick_challenger(all_challengers, str(anchor.movie_id))
        if challenger is None:
            raise HTTPException(
                status_code=404,
                detail="No challenger films available after excluding anchor.",
            )

        pair_ids = {str(anchor.movie_id), str(challenger.movie_id)}
        if last_pair_ids is None or pair_ids != last_pair_ids:
            return anchor, challenger

    # After retries, return whatever we have (anti-repeat is best-effort)
    return anchor, challenger  # type: ignore[return-value]


async def _bootstrap_pair(
    db: AsyncSession,
    uid,
    last_pair_ids: set[str] | None,
) -> tuple[UserMovie, UserMovie]:
    """Bootstrap: pick two films the user can classify.

    Prefers Seen-unranked films (seen=True, battles=0).
    Falls back to Unknown films (seen=None) if not enough seen films exist.
    This lets brand new users start playing immediately with popular/trending
    movies — they mark them as seen/unseen, which builds the initial pool.
    """
    # First try seen-unranked
    stmt = (
        select(UserMovie)
        .options(joinedload(UserMovie.movie))
        .where(
            UserMovie.user_id == uid,
            UserMovie.seen.is_(True),
            UserMovie.battles == 0,
        )
    )
    result = await db.execute(stmt)
    candidates = list(result.unique().scalars().all())

    # Fall back to unknown films if not enough seen ones
    if len(candidates) < 2:
        unknown_stmt = (
            select(UserMovie)
            .options(joinedload(UserMovie.movie))
            .where(
                UserMovie.user_id == uid,
                UserMovie.seen.is_(None),
            )
            .limit(200)
        )
        unknown_result = await db.execute(unknown_stmt)
        unknown = list(unknown_result.unique().scalars().all())
        candidates.extend(unknown)

    if len(candidates) < 2:
        raise HTTPException(
            status_code=404,
            detail="Not enough movies in your pool yet. Your movie library is still loading — try refreshing in a few seconds.",
        )

    for _ in range(5):
        chosen = random.sample(candidates, 2)
        pair_ids = {str(chosen[0].movie_id), str(chosen[1].movie_id)}
        if last_pair_ids is None or pair_ids != last_pair_ids:
            return chosen[0], chosen[1]

    return chosen[0], chosen[1]
