"""Movie pair generation endpoint."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import get_db
from backend.db_models import User, UserMovie
from backend.rate_limit import limiter
from backend.routers.auth import get_current_user
from backend.schemas import MediaType, MovieWithStateSchema, MoviePairResponse
from backend.services.pair_selection import select_pair
from backend.utils.tokens import decode_pair_token, encode_pair_token

logger = logging.getLogger(__name__)

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
        media_type=movie.media_type,
        seen=um.seen,
        elo=um.elo,
        battles=um.battles,
    )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get("/pair", response_model=MoviePairResponse)
@limiter.limit("60/minute")
async def get_movie_pair(
    request: Request,
    mode: str = Query(default="discovery"),
    last_pair_token: Optional[str] = Query(default=None),
    media_type: MediaType = Query(default="movie"),
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
        last_pair_ids = decode_pair_token(last_pair_token)

    try:
        pair = await select_pair(db, uid, last_pair_ids, media_type)
    except ValueError:
        raise HTTPException(status_code=404, detail="No eligible pair found")

    movie_a, movie_b = pair
    schema_a = _user_movie_to_schema(movie_a)
    schema_b = _user_movie_to_schema(movie_b)
    token = encode_pair_token(str(movie_a.movie_id), str(movie_b.movie_id))

    return MoviePairResponse(
        movie_a=schema_a,
        movie_b=schema_b,
        next_pair_token=token,
    )
