"""Rankings, stats, and CSV export routes."""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from backend.db import get_supabase
from backend.models import (
    Movie,
    RankedMovie,
    RankingsResponse,
    StatsResponse,
)
from backend.routers.auth import get_current_user_id

router = APIRouter(prefix="/api/rankings", tags=["rankings"])


def _build_ranked_movie(row: dict, rank: int) -> RankedMovie:
    movie_data = row["movies"]
    return RankedMovie(
        rank=rank,
        movie=Movie(
            id=movie_data["id"],
            trakt_id=movie_data["trakt_id"],
            tmdb_id=movie_data.get("tmdb_id"),
            imdb_id=movie_data.get("imdb_id"),
            title=movie_data["title"],
            year=movie_data.get("year"),
            poster_url=movie_data.get("poster_url"),
            overview=movie_data.get("overview"),
        ),
        elo_rating=row["elo_rating"],
        duel_count=row["duel_count"],
        win_count=row["win_count"],
    )


@router.get("", response_model=RankingsResponse)
async def get_rankings(
    user_id: str = Depends(get_current_user_id),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Return the user's ranked movies sorted by ELO descending."""
    db = get_supabase()
    result = (
        db.table("rankings")
        .select("*, movies(*)")
        .eq("user_id", user_id)
        .order("elo_rating", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )

    count_result = (
        db.table("rankings")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .execute()
    )

    rankings = [
        _build_ranked_movie(row, rank=offset + i + 1)
        for i, row in enumerate(result.data or [])
    ]

    return RankingsResponse(rankings=rankings, total=count_result.count or 0)


@router.get("/stats", response_model=StatsResponse)
async def get_stats(user_id: str = Depends(get_current_user_id)):
    """Return aggregate stats for the user's rankings."""
    db = get_supabase()
    result = (
        db.table("rankings")
        .select("*, movies(*)")
        .eq("user_id", user_id)
        .order("elo_rating", desc=True)
        .execute()
    )
    rows = result.data or []

    if not rows:
        return StatsResponse(
            total_duels=0,
            total_movies_ranked=0,
            average_elo=0.0,
        )

    total_duels = sum(r["duel_count"] for r in rows) // 2  # each duel counted twice
    elos = [r["elo_rating"] for r in rows]

    highest = _build_ranked_movie(rows[0], rank=1)
    lowest = _build_ranked_movie(rows[-1], rank=len(rows))

    return StatsResponse(
        total_duels=total_duels,
        total_movies_ranked=len(rows),
        average_elo=round(sum(elos) / len(elos), 2),
        highest_rated=highest,
        lowest_rated=lowest,
    )


@router.get("/export/csv")
async def export_csv(user_id: str = Depends(get_current_user_id)):
    """Export rankings as a Letterboxd-compatible CSV."""
    db = get_supabase()
    result = (
        db.table("rankings")
        .select("*, movies(*)")
        .eq("user_id", user_id)
        .order("elo_rating", desc=True)
        .execute()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    # Letterboxd CSV format
    writer.writerow(["Position", "Title", "Year", "imdbID", "Rating10"])

    rows = result.data or []
    elos = [r["elo_rating"] for r in rows] if rows else []
    min_elo = min(elos) if elos else 0
    max_elo = max(elos) if elos else 0

    for i, row in enumerate(rows):
        movie = row["movies"]
        # Map ELO to 1-10 Letterboxd rating
        if max_elo != min_elo:
            normalized = (row["elo_rating"] - min_elo) / (max_elo - min_elo)
            rating = max(1, min(10, round(normalized * 9) + 1))
        else:
            rating = 5
        writer.writerow([
            i + 1,
            movie["title"],
            movie.get("year", ""),
            movie.get("imdb_id", ""),
            rating,
        ])

    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=filmduel_rankings.csv"},
    )
