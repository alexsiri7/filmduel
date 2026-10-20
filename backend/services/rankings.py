"""Rankings business logic — queries, stats, and CSV export."""

from __future__ import annotations

import csv
import io
import re
import uuid
from collections.abc import Iterable
from typing import Optional

from sqlalchemy import (
    Float,
    bindparam,
    cast,
    false,
    func,
    literal_column,
    select,
    true,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from backend.db_models import Movie, UserMovie
from backend.services.elo import percentile_rating

_DECADE_RE = re.compile(r"[0-9]{4}s?")


def parse_decade(decade: str) -> tuple[int, int]:
    """Parse a decade string like '1990s' into (start, end) years inclusive."""
    if not _DECADE_RE.fullmatch(decade):
        raise ValueError(f"Invalid decade: {decade!r}")
    start = int(decade.rstrip("s"))
    return start, start + 9


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
        count_stmt = count_stmt.where(
            Movie.year >= decade_start, Movie.year <= decade_end
        )

    stmt = stmt.order_by(UserMovie.elo.desc()).offset(offset).limit(limit)

    result = await db.execute(stmt)
    user_movies = result.unique().scalars().all()

    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    return user_movies, total


async def get_elo_ratings(
    db: AsyncSession,
    user_id: uuid.UUID,
    elos: Iterable[float],
    media_type: str = "movie",
) -> dict[float, int]:
    """Return the 1-10 rating of each ELO in ``elos``, keyed by ELO.

    Each ELO is rated against the user's ranked films of this media_type;
    genre/decade filters deliberately do not apply, so a film's rating is the
    same everywhere. The percentile counts are computed in SQL so the
    population never leaves the database (SEC-12, #784).
    """
    probes = sorted(set(elos))
    if not probes:
        return {}

    population = (
        select(
            UserMovie.elo.label("elo"),
            literal_column("1").label("weight"),
            false().label("probe"),
        )
        .join(Movie, UserMovie.movie_id == Movie.id)
        .where(
            UserMovie.user_id == user_id,
            UserMovie.seen.is_(True),
            UserMovie.battles > 0,
            Movie.media_type == media_type,
        )
    )
    # Weight-0 probe rows let an ELO outside the population still be ranked.
    probe_rows = select(
        func.unnest(cast(bindparam("elos", probes), ARRAY(Float))).label("elo"),
        literal_column("0").label("weight"),
        true().label("probe"),
    )
    points = population.union_all(probe_rows).subquery("points")
    distinct_elos = (
        select(
            points.c.elo,
            func.sum(points.c.weight).label("equal"),
            func.bool_or(points.c.probe).label("probe"),
        )
        .group_by(points.c.elo)
        .subquery("distinct_elos")
    )
    counted = select(
        distinct_elos.c.elo,
        distinct_elos.c.probe,
        (
            func.sum(distinct_elos.c.equal).over(order_by=distinct_elos.c.elo)
            - distinct_elos.c.equal
        ).label("below"),
        distinct_elos.c.equal,
        func.sum(distinct_elos.c.equal).over().label("n"),
    ).subquery("counted")
    stmt = select(counted.c.elo, counted.c.below, counted.c.equal, counted.c.n).where(
        counted.c.probe
    )
    result = await db.execute(stmt)
    # sum() over integers comes back as numeric.
    return {
        row.elo: percentile_rating(int(row.below), int(row.equal), int(row.n))
        for row in result.all()
    }


async def get_user_stats(
    db: AsyncSession, user_id: uuid.UUID, media_type: str = "movie"
) -> dict:
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
        .select_from(UserMovie)
        .join(Movie, UserMovie.movie_id == Movie.id)
        .where(*ranked_filters)
    )
    agg_result = await db.execute(agg_stmt)
    total_movies, total_battles_sum, avg_elo = agg_result.one()

    unseen_stmt = (
        select(func.count())
        .select_from(UserMovie)
        .join(Movie, UserMovie.movie_id == Movie.id)
        .where(
            UserMovie.user_id == user_id,
            UserMovie.seen.is_(False),
            Movie.media_type == media_type,
        )
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
        "average_elo": round(float(avg_elo), 2) if avg_elo is not None else 0.0,
        "highest_rated": highest_rated,
        "lowest_rated": lowest_rated,
    }


# A field can start at the beginning of a cell or, when a spreadsheet in a
# semicolon-delimited locale re-splits the comma CSV, after any ";" or line
# break in it — optionally behind '"' characters, which that re-split reads as
# the field's own quoting. Comma-CSV quoting does not stop the re-split, so each
# such start is neutralized. "\r\n" is one break: "\r" alone only counts when
# no "\n" follows, so the prefix never lands inside the pair.
_FORMULA_FIELD_START = re.compile(r'(^|(?:;|\r\n|\r(?!\n)|\n)"*)(?=[=+\-@\t\r\n])')


def _sanitize_csv_cell(value: str) -> str:
    """Prevent CSV formula injection by prepending a single quote to dangerous prefixes."""
    return _FORMULA_FIELD_START.sub(r"\1'", value)


async def export_rankings_csv(
    db: AsyncSession, user_id: uuid.UUID, media_type: str = "movie"
) -> str:
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
        .limit(10000)  # safety cap — Letterboxd CSV is unrealistic above this count
    )
    result = await db.execute(stmt)
    user_movies = result.unique().scalars().all()
    ratings = await get_elo_ratings(
        db, user_id, [um.elo for um in user_movies], media_type
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Position", "Title", "Year", "imdbID", "Rating10"])

    for i, um in enumerate(user_movies):
        movie = um.movie
        writer.writerow(
            [
                i + 1,
                _sanitize_csv_cell(movie.title),
                movie.year or "",
                _sanitize_csv_cell(movie.imdb_id or ""),
                ratings[um.elo],
            ]
        )

    return output.getvalue()
