"""Rankings, stats, and CSV export routes."""

from __future__ import annotations

import io
from collections.abc import Sequence
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import get_db
from backend.db_models import User, UserMovie
from backend.rate_limit import limiter
from backend.routers.auth import get_current_user
from backend.schemas import (
    MediaType,
    MovieSchema,
    RankedMovie,
    RankingsResponse,
    StatsResponse,
)
from backend.services.elo import elo_to_rating
from backend.services.rankings import (
    export_rankings_csv,
    get_ranked_elos,
    get_user_rankings,
    get_user_stats,
)

router = APIRouter(prefix="/api/rankings", tags=["rankings"])


def _build_ranked_movie(
    um: UserMovie, rank: int, sorted_elos: Sequence[float]
) -> RankedMovie:
    return RankedMovie(
        rank=rank,
        movie=MovieSchema.from_model(um.movie),
        elo=round(um.elo),
        battles=um.battles,
        trakt_rating=elo_to_rating(um.elo, sorted_elos),
    )


@router.get("", response_model=RankingsResponse)
@limiter.limit("30/minute")
async def get_rankings(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    genre: Optional[str] = Query(default=None),
    decade: Optional[str] = Query(default=None),
    media_type: MediaType = Query(default="movie"),
):
    """Return the user's ranked movies/shows sorted by ELO descending."""
    try:
        user_movies, total = await get_user_rankings(
            db,
            current_user.id,
            genre=genre,
            decade=decade,
            limit=limit,
            offset=offset,
            media_type=media_type,
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid decade format")
    sorted_elos = (
        await get_ranked_elos(db, current_user.id, media_type) if user_movies else []
    )
    rankings = [
        _build_ranked_movie(um, rank=offset + i + 1, sorted_elos=sorted_elos)
        for i, um in enumerate(user_movies)
    ]
    return RankingsResponse(rankings=rankings, total=total)


@router.get("/stats", response_model=StatsResponse)
@limiter.limit("30/minute")
async def get_stats(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    media_type: MediaType = Query(default="movie"),
):
    """Return aggregate stats for the user's rankings."""
    stats = await get_user_stats(db, current_user.id, media_type=media_type)

    if stats["highest_rated"] is None:
        return StatsResponse(
            total_duels=stats["total_duels"],
            total_movies_ranked=stats["total_movies_ranked"],
            unseen_count=stats["unseen_count"],
            average_elo=stats["average_elo"],
        )

    sorted_elos = await get_ranked_elos(db, current_user.id, media_type)
    highest = _build_ranked_movie(stats["highest_rated"], 1, sorted_elos)
    lowest = _build_ranked_movie(
        stats["lowest_rated"], stats["total_movies_ranked"], sorted_elos
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
# per-user via _rate_limit_key; 10 exports/hour is ample for CSV downloads
@limiter.limit("10/hour")
async def export_csv(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    media_type: MediaType = Query(default="movie"),
):
    """Export rankings as a Letterboxd-compatible CSV."""
    csv_content = await export_rankings_csv(db, current_user.id, media_type=media_type)
    output = io.StringIO(csv_content)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=filmduel_rankings.csv"},
    )
