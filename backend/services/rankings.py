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
) -> tuple[list[UserMovie], int]:
    """Return (ranked user_movies with loaded movies, total count).

    Filters: seen=True, battles>0, optional genre, optional decade.
    Ordered by ELO descending.
    """
    base_filters = [
        UserMovie.user_id == user_id,
        UserMovie.seen.is_(True),
        UserMovie.battles > 0,
    ]

    stmt = (
        select(UserMovie)
        .options(joinedload(UserMovie.movie))
        .where(*base_filters)
    )
    count_stmt = (
        select(func.count())
        .select_from(UserMovie)
        .where(*base_filters)
    )

    needs_movie_join = genre is not None or decade is not None
    if needs_movie_join:
        stmt = stmt.join(Movie, UserMovie.movie_id == Movie.id)
        count_stmt = count_stmt.join(Movie, UserMovie.movie_id == Movie.id)

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


async def get_user_stats(db: AsyncSession, user_id: uuid.UUID) -> dict:
    """Return aggregate stats for the user's rankings.

    Returns dict with keys: total_duels, total_movies_ranked, unseen_count,
    average_elo, highest_rated (UserMovie|None), lowest_rated (UserMovie|None).
    """
    stmt = (
        select(UserMovie)
        .options(joinedload(UserMovie.movie))
        .where(
            UserMovie.user_id == user_id,
            UserMovie.seen.is_(True),
            UserMovie.battles > 0,
        )
        .order_by(UserMovie.elo.desc())
    )
    result = await db.execute(stmt)
    user_movies = result.unique().scalars().all()

    unseen_stmt = (
        select(func.count())
        .select_from(UserMovie)
        .where(UserMovie.user_id == user_id, UserMovie.seen.is_(False))
    )
    unseen_result = await db.execute(unseen_stmt)
    unseen_count = unseen_result.scalar() or 0

    if not user_movies:
        return {
            "total_duels": 0,
            "total_movies_ranked": 0,
            "unseen_count": unseen_count,
            "average_elo": 0.0,
            "highest_rated": None,
            "lowest_rated": None,
        }

    total_battles = sum(um.battles for um in user_movies)
    elos = [um.elo for um in user_movies]

    return {
        "total_duels": total_battles // 2,
        "total_movies_ranked": len(user_movies),
        "unseen_count": unseen_count,
        "average_elo": round(sum(elos) / len(elos), 2),
        "highest_rated": user_movies[0],
        "lowest_rated": user_movies[-1],
    }


async def export_rankings_csv(db: AsyncSession, user_id: uuid.UUID) -> str:
    """Return CSV string content for Letterboxd export."""
    stmt = (
        select(UserMovie)
        .options(joinedload(UserMovie.movie))
        .where(
            UserMovie.user_id == user_id,
            UserMovie.seen.is_(True),
            UserMovie.battles > 0,
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
