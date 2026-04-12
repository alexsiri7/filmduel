"""Rankings, stats, and CSV export routes."""

from __future__ import annotations

import io
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import get_db
from backend.db_models import User, UserMovie
from backend.schemas import MovieSchema, RankedMovie, RankingsResponse, StatsResponse
from backend.routers.auth import get_current_user
from backend.services.elo import elo_to_trakt_rating
from backend.services.rankings import (
    export_rankings_csv,
    get_user_rankings,
    get_user_stats,
)

router = APIRouter(prefix="/api/rankings", tags=["rankings"])


def _build_ranked_movie(um: UserMovie, rank: int) -> RankedMovie:
    movie = um.movie
    return RankedMovie(
        rank=rank,
        movie=MovieSchema(
            id=str(movie.id),
            trakt_id=movie.trakt_id,
            tmdb_id=movie.tmdb_id,
            imdb_id=movie.imdb_id,
            title=movie.title,
            year=movie.year,
            poster_url=movie.poster_url,
            overview=movie.overview,
            genres=movie.genres,
        ),
        elo=um.elo,
        battles=um.battles,
        trakt_rating=elo_to_trakt_rating(um.elo),
    )


@router.get("", response_model=RankingsResponse)
async def get_rankings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    genre: Optional[str] = Query(default=None),
    decade: Optional[str] = Query(default=None),
):
    """Return the user's ranked movies sorted by ELO descending."""
    user_movies, total = await get_user_rankings(
        db, current_user.id, genre=genre, decade=decade, limit=limit, offset=offset
    )
    rankings = [
        _build_ranked_movie(um, rank=offset + i + 1)
        for i, um in enumerate(user_movies)
    ]
    return RankingsResponse(rankings=rankings, total=total)


@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate stats for the user's rankings."""
    stats = await get_user_stats(db, current_user.id)

    if stats["highest_rated"] is None:
        return StatsResponse(
            total_duels=stats["total_duels"],
            total_movies_ranked=stats["total_movies_ranked"],
            unseen_count=stats["unseen_count"],
            average_elo=stats["average_elo"],
        )

    highest = _build_ranked_movie(stats["highest_rated"], rank=1)
    lowest = _build_ranked_movie(
        stats["lowest_rated"], rank=stats["total_movies_ranked"]
    )

    return StatsResponse(
        total_duels=stats["total_duels"],
        total_movies_ranked=stats["total_movies_ranked"],
        unseen_count=stats["unseen_count"],
        average_elo=stats["average_elo"],
        highest_rated=highest,
        lowest_rated=lowest,
    )


@router.get("/export/csv")
async def export_csv(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Export rankings as a Letterboxd-compatible CSV."""
    csv_content = await export_rankings_csv(db, current_user.id)
    output = io.StringIO(csv_content)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=filmduel_rankings.csv"},
    )
