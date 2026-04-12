"""Movie pair generation endpoint — duel pair selection."""

from __future__ import annotations

import base64
import random
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from backend.db import get_db
from backend.db_models import Movie, User, UserMovie
from backend.schemas import MovieWithStateSchema, MoviePairResponse
from backend.routers.auth import get_current_user

router = APIRouter(prefix="/api/movies", tags=["movies"])


def _user_movie_to_schema(um: UserMovie) -> MovieWithStateSchema:
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
    raw = f"{id_a},{id_b}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_pair_token(token: str) -> set[str] | None:
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        parts = raw.split(",")
        if len(parts) == 2:
            return {parts[0], parts[1]}
    except Exception:
        pass
    return None


@router.get("/pair", response_model=MoviePairResponse)
async def get_movie_pair(
    mode: str = Query(default="discovery"),
    last_pair_token: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a pair of seen films for a duel.

    Only returns films with seen=true. If not enough seen films
    are available, returns 404 with a signal to go swipe first.
    """
    uid = current_user.id

    last_pair_ids: set[str] | None = None
    if last_pair_token:
        last_pair_ids = _decode_pair_token(last_pair_token)

    pair = await _select_pair(db, uid, last_pair_ids)

    movie_a, movie_b = pair
    schema_a = _user_movie_to_schema(movie_a)
    schema_b = _user_movie_to_schema(movie_b)
    token = _encode_pair_token(str(movie_a.movie_id), str(movie_b.movie_id))

    return MoviePairResponse(
        movie_a=schema_a,
        movie_b=schema_b,
        next_pair_token=token,
    )


async def _select_pair(
    db: AsyncSession,
    uid,
    last_pair_ids: set[str] | None,
) -> tuple[UserMovie, UserMovie]:
    """Select a duel pair from seen films only.

    Uses settlement weight: 1/(battles+1).
    Anchor rule: at least one film must have battles >= 1 (unless bootstrap).
    If not enough seen films, signal swipe needed.
    """

    # All seen films
    seen_stmt = (
        select(UserMovie)
        .options(joinedload(UserMovie.movie))
        .where(
            UserMovie.user_id == uid,
            UserMovie.seen.is_(True),
        )
    )
    seen_result = await db.execute(seen_stmt)
    seen_films = list(seen_result.unique().scalars().all())

    if len(seen_films) < 2:
        raise HTTPException(
            status_code=404,
            detail="Need more seen films to duel. Swipe to classify some movies first!",
        )

    # Split into anchors (ranked, battles >= 1) and full pool
    anchor_pool = [f for f in seen_films if f.battles >= 1 and f.elo is not None]

    # Bootstrap: no anchors yet — pick two seen films by settlement weight
    if len(anchor_pool) == 0:
        return _pick_bootstrap_pair(seen_films, last_pair_ids)

    # Normal: anchor + challenger from full seen pool
    for _ in range(5):
        # Pick anchor weighted by settlement
        anchor = _weighted_sample(anchor_pool)

        # Pick challenger from all seen films (minus anchor)
        candidates = [f for f in seen_films if f.movie_id != anchor.movie_id]
        if not candidates:
            break

        challenger = _weighted_sample(candidates)

        # Anti-repeat
        pair_ids = {str(anchor.movie_id), str(challenger.movie_id)}
        if last_pair_ids is None or pair_ids != last_pair_ids:
            return anchor, challenger

    # Fallback after retries
    return anchor, challenger  # type: ignore


def _pick_bootstrap_pair(
    seen_films: list[UserMovie],
    last_pair_ids: set[str] | None,
) -> tuple[UserMovie, UserMovie]:
    """Bootstrap: pick two seen films when no anchors exist."""
    for _ in range(5):
        a, b = random.sample(seen_films, 2)
        pair_ids = {str(a.movie_id), str(b.movie_id)}
        if last_pair_ids is None or pair_ids != last_pair_ids:
            return a, b
    return a, b  # type: ignore


def _weighted_sample(films: list[UserMovie]) -> UserMovie:
    """Sample one film weighted by settlement: 1/(battles+1)."""
    weights = [1.0 / (f.battles + 1) for f in films]
    return random.choices(films, weights=weights, k=1)[0]
