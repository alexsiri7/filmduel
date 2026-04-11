"""Rankings, stats, and CSV export routes."""

from __future__ import annotations

import csv
import io
import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from backend.db import get_db
from backend.models import (
    MovieSchema,
    RankedMovie,
    RankingsResponse,
    StatsResponse,
    UserMovie,
)
from backend.routers.auth import get_current_user_id

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
        ),
        elo=um.elo,
        battles=um.battles,
    )


@router.get("", response_model=RankingsResponse)
async def get_rankings(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Return the user's ranked movies sorted by ELO descending."""
    uid = uuid.UUID(user_id)

    # Only show movies the user has actually seen and battled
    stmt = (
        select(UserMovie)
        .options(joinedload(UserMovie.movie))
        .where(UserMovie.user_id == uid, UserMovie.seen.is_(True), UserMovie.battles > 0)
        .order_by(UserMovie.elo.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    user_movies = result.unique().scalars().all()

    # Count total
    count_stmt = (
        select(func.count())
        .select_from(UserMovie)
        .where(UserMovie.user_id == uid, UserMovie.seen.is_(True), UserMovie.battles > 0)
    )
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    rankings = [
        _build_ranked_movie(um, rank=offset + i + 1)
        for i, um in enumerate(user_movies)
    ]

    return RankingsResponse(rankings=rankings, total=total)


@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate stats for the user's rankings."""
    uid = uuid.UUID(user_id)

    stmt = (
        select(UserMovie)
        .options(joinedload(UserMovie.movie))
        .where(UserMovie.user_id == uid, UserMovie.seen.is_(True), UserMovie.battles > 0)
        .order_by(UserMovie.elo.desc())
    )
    result = await db.execute(stmt)
    user_movies = result.unique().scalars().all()

    if not user_movies:
        return StatsResponse(
            total_duels=0,
            total_movies_ranked=0,
            average_elo=0.0,
        )

    total_battles = sum(um.battles for um in user_movies)
    total_duels = total_battles // 2  # each duel increments two movies
    elos = [um.elo for um in user_movies]

    highest = _build_ranked_movie(user_movies[0], rank=1)
    lowest = _build_ranked_movie(user_movies[-1], rank=len(user_movies))

    return StatsResponse(
        total_duels=total_duels,
        total_movies_ranked=len(user_movies),
        average_elo=round(sum(elos) / len(elos), 2),
        highest_rated=highest,
        lowest_rated=lowest,
    )


@router.get("/export/csv")
async def export_csv(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Export rankings as a Letterboxd-compatible CSV."""
    uid = uuid.UUID(user_id)

    stmt = (
        select(UserMovie)
        .options(joinedload(UserMovie.movie))
        .where(UserMovie.user_id == uid, UserMovie.seen.is_(True), UserMovie.battles > 0)
        .order_by(UserMovie.elo.desc())
    )
    result = await db.execute(stmt)
    user_movies = result.unique().scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    # Letterboxd CSV format
    writer.writerow(["Position", "Title", "Year", "imdbID", "Rating10"])

    for i, um in enumerate(user_movies):
        movie = um.movie
        # Map ELO to Trakt 1-10 scale per PRD formula
        trakt_rating = max(1, min(10, round((um.elo - 600) * 9 / 800) + 1))
        writer.writerow([
            i + 1,
            movie.title,
            movie.year or "",
            movie.imdb_id or "",
            trakt_rating,
        ])

    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=filmduel_rankings.csv"},
    )
