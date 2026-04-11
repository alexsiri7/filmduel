"""Movie pair generation endpoint."""

from __future__ import annotations

import random

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from backend.db import get_db
from backend.models import Movie, MovieSchema, MoviePairResponse, User, UserMovie
from backend.routers.auth import get_current_user

router = APIRouter(prefix="/api/movies", tags=["movies"])


def _movie_to_schema(movie: Movie) -> MovieSchema:
    return MovieSchema(
        id=str(movie.id),
        trakt_id=movie.trakt_id,
        tmdb_id=movie.tmdb_id,
        imdb_id=movie.imdb_id,
        title=movie.title,
        year=movie.year,
        poster_url=movie.poster_url,
        overview=movie.overview,
    )


@router.get("/pair", response_model=MoviePairResponse)
async def get_movie_pair(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a random pair of movies for a duel.

    Selects two movies from the user's pool where seen is NULL or true,
    preferring movies with fewer battles for coverage.
    """
    uid = current_user.id

    # Get user movies eligible for dueling (seen or unknown)
    stmt = (
        select(UserMovie)
        .options(joinedload(UserMovie.movie))
        .where(
            UserMovie.user_id == uid,
            or_(UserMovie.seen.is_(None), UserMovie.seen.is_(True)),
        )
        .limit(200)
    )
    result = await db.execute(stmt)
    user_movies = result.unique().scalars().all()

    if len(user_movies) < 2:
        raise HTTPException(
            status_code=404,
            detail="Not enough movies in your pool. Watch more movies on Trakt!",
        )

    # Weighted random: prefer movies with fewer battles
    weights = [1.0 / (1 + um.battles) for um in user_movies]
    chosen = random.choices(user_movies, weights=weights, k=2)

    # Ensure two different movies
    if chosen[0].movie_id == chosen[1].movie_id:
        others = [um for um in user_movies if um.movie_id != chosen[0].movie_id]
        if not others:
            raise HTTPException(status_code=404, detail="Not enough distinct movies.")
        chosen[1] = random.choice(others)

    movie_a = _movie_to_schema(chosen[0].movie)
    movie_b = _movie_to_schema(chosen[1].movie)

    return MoviePairResponse(movie_a=movie_a, movie_b=movie_b)
