"""Movie pair generation endpoint."""

from __future__ import annotations

import random
import uuid

from fastapi import APIRouter, Depends, HTTPException

from backend.db import get_supabase
from backend.models import Movie, MoviePairResponse
from backend.routers.auth import get_current_user_id

router = APIRouter(prefix="/api/movies", tags=["movies"])


def _row_to_movie(row: dict) -> Movie:
    return Movie(
        id=row["id"],
        trakt_id=row["trakt_id"],
        tmdb_id=row.get("tmdb_id"),
        imdb_id=row.get("imdb_id"),
        title=row["title"],
        year=row.get("year"),
        poster_url=row.get("poster_url"),
        overview=row.get("overview"),
    )


@router.get("/pair", response_model=MoviePairResponse)
async def get_movie_pair(user_id: str = Depends(get_current_user_id)):
    """Generate a random pair of movies for a duel.

    Selects two movies from the user's movie pool, preferring movies
    with fewer duels to ensure coverage.
    """
    db = get_supabase()

    # Get movies from the pool (user's watched + popular)
    result = (
        db.table("movie_pool")
        .select("*, movies(*)")
        .eq("user_id", user_id)
        .limit(100)
        .execute()
    )

    if not result.data or len(result.data) < 2:
        raise HTTPException(
            status_code=404,
            detail="Not enough movies in your pool. Watch more movies on Trakt!",
        )

    # Weighted random: prefer movies with fewer duels
    pool = result.data
    weights = [1.0 / (1 + entry.get("duel_count", 0)) for entry in pool]
    chosen = random.choices(pool, weights=weights, k=2)

    # Ensure we got two different movies
    if chosen[0]["movie_id"] == chosen[1]["movie_id"]:
        others = [m for m in pool if m["movie_id"] != chosen[0]["movie_id"]]
        if not others:
            raise HTTPException(status_code=404, detail="Not enough distinct movies.")
        chosen[1] = random.choice(others)

    movie_a = _row_to_movie(chosen[0]["movies"])
    movie_b = _row_to_movie(chosen[1]["movies"])

    # Create a pending duel record
    duel_id = str(uuid.uuid4())
    db.table("duels").insert(
        {
            "id": duel_id,
            "user_id": user_id,
            "movie_a_id": movie_a.id,
            "movie_b_id": movie_b.id,
            "status": "pending",
        }
    ).execute()

    return MoviePairResponse(movie_a=movie_a, movie_b=movie_b, duel_id=duel_id)
