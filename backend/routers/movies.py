"""Movie pair generation endpoint."""

from __future__ import annotations

import base64
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import get_db
from backend.db_models import User, UserMovie
from backend.schemas import MovieWithStateSchema, MoviePairResponse
from backend.routers.auth import get_current_user
from backend.services.pair_selection import select_pair

router = APIRouter(prefix="/api/movies", tags=["movies"])


# ---------------------------------------------------------------------------
# Schema / token helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


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

    try:
        pair = await select_pair(db, uid, last_pair_ids)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    movie_a, movie_b = pair
    schema_a = _user_movie_to_schema(movie_a)
    schema_b = _user_movie_to_schema(movie_b)
    token = _encode_pair_token(str(movie_a.movie_id), str(movie_b.movie_id))

    return MoviePairResponse(
        movie_a=schema_a,
        movie_b=schema_b,
        next_pair_token=token,
    )
