"""Rankings business logic — queries, stats, and CSV export."""

from __future__ import annotations

import csv
import io
import uuid
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from backend.db_models import Movie, UserMovie


def parse_decade(decade: str) -> tuple[int, int]:
    """Parse a decade string like '1990s' into (start, end) years inclusive."""
    start = int(decade.rstrip("s"))
    return start, start + 9


def elo_to_letterboxd_rating(elo: int) -> int:
    """Map ELO to a 1-10 scale for Letterboxd/Trakt export."""
    return max(1, min(10, round((elo - 600) * 9 / 800) + 1))


async def get_user_rankings(
    db: AsyncSession,
    user_id: uuid.UUID,
    genre: Optional[str] = None,
    decade: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    media_type: str = "movie",
) -> tuple[list[UserMovie], int]:
    """Return (ranked user_movies with loaded movies, total count).

    Filters: seen=True, battles>0, media_type, optional genre, optional decade.
    Ordered by ELO descending.
    """
    base_filters = [
        UserMovie.user_id == user_id,
        UserMovie.seen.is_(True),
        UserMovie.battles > 0,
    ]

    # Always join Movie for media_type filter
    stmt = (
        select(UserMovie)
        .options(joinedload(UserMovie.movie))
        .join(Movie, UserMovie.movie_id == Movie.id)
        .where(*base_filters, Movie.media_type == media_type)
    )
    count_stmt = (
        select(func.count())
        .select_from(UserMovie)
        .join(Movie, UserMovie.movie_id == Movie.id)
        .where(*base_filters, Movie.media_type == media_type)
    )

    if genre:
        stmt = stmt.where(Movie.genres.any(genre))
        count_stmt = count_stmt.where(Movie.genres.any(genre))

    if decade:
        decade_start, decade_end = parse_decade(decade)
        stmt = stmt.where(Movie.year >= decade_start, Movie.year <= decade_end)
        count_stmt = count_stmt.where(Movie.year >= decade_start, Movie.year <= decade_end)

    stmt = stmt.order_by(UserMovie.elo.desc()).offset(offset).limit(limit)

    result = await db.execute(stmt)
    user_movies = result.unique().scalars().all()

    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    return user_movies, total


async def get_user_stats(db: AsyncSession, user_id: uuid.UUID, media_type: str = "movie") -> dict:
    """Return aggregate stats for the user's rankings.

    Returns dict with keys: total_duels, total_movies_ranked, unseen_count,
    average_elo, highest_rated (UserMovie|None), lowest_rated (UserMovie|None).
    """
    ranked_filters = [
        UserMovie.user_id == user_id,
        UserMovie.seen.is_(True),
        UserMovie.battles > 0,
        Movie.media_type == media_type,
    ]

    agg_stmt = (
        select(
            func.count(UserMovie.id),
            func.sum(UserMovie.battles),
            func.avg(UserMovie.elo),
        )
        .join(Movie, UserMovie.movie_id == Movie.id)
        .where(*ranked_filters)
    )
    agg_result = await db.execute(agg_stmt)
    total_movies, total_battles_sum, avg_elo = agg_result.one()

    unseen_stmt = (
        select(func.count())
        .select_from(UserMovie)
        .join(Movie, UserMovie.movie_id == Movie.id)
        .where(UserMovie.user_id == user_id, UserMovie.seen.is_(False), Movie.media_type == media_type)
    )
    unseen_count = (await db.execute(unseen_stmt)).scalar() or 0

    if not total_movies:
        return {
            "total_duels": 0,
            "total_movies_ranked": 0,
            "unseen_count": unseen_count,
            "average_elo": 0.0,
            "highest_rated": None,
            "lowest_rated": None,
        }

    highest_stmt = (
        select(UserMovie)
        .options(joinedload(UserMovie.movie))
        .join(Movie, UserMovie.movie_id == Movie.id)
        .where(*ranked_filters)
        .order_by(UserMovie.elo.desc())
        .limit(1)
    )
    highest_result = await db.execute(highest_stmt)
    highest_rated = highest_result.unique().scalars().first()

    lowest_stmt = (
        select(UserMovie)
        .options(joinedload(UserMovie.movie))
        .join(Movie, UserMovie.movie_id == Movie.id)
        .where(*ranked_filters)
        .order_by(UserMovie.elo.asc())
        .limit(1)
    )
    lowest_result = await db.execute(lowest_stmt)
    lowest_rated = lowest_result.unique().scalars().first()

    return {
        "total_duels": (total_battles_sum or 0) // 2,
        "total_movies_ranked": total_movies,
        "unseen_count": unseen_count,
        "average_elo": round(float(avg_elo), 2) if avg_elo else 0.0,
        "highest_rated": highest_rated,
        "lowest_rated": lowest_rated,
    }


async def export_rankings_csv(db: AsyncSession, user_id: uuid.UUID, media_type: str = "movie") -> str:
    """Return CSV string content for Letterboxd export."""
    stmt = (
        select(UserMovie)
        .options(joinedload(UserMovie.movie))
        .join(Movie, UserMovie.movie_id == Movie.id)
        .where(
            UserMovie.user_id == user_id,
            UserMovie.seen.is_(True),
            UserMovie.battles > 0,
            Movie.media_type == media_type,
        )
        .order_by(UserMovie.elo.desc())
    )
    result = await db.execute(stmt)
    user_movies = result.unique().scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Position", "Title", "Year", "imdbID", "Rating10"])

    for i, um in enumerate(user_movies):
        movie = um.movie
        trakt_rating = elo_to_letterboxd_rating(um.elo)
        writer.writerow([
            i + 1,
            movie.title,
            movie.year or "",
            movie.imdb_id or "",
            trakt_rating,
        ])

    return output.getvalue()
