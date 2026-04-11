"""TMDB API client — fetch poster URLs for movies."""

from __future__ import annotations

import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.db_models import Movie

logger = logging.getLogger(__name__)


async def fetch_poster_url(tmdb_id: int) -> str | None:
    """Fetch poster URL from TMDB API. Returns full URL or None."""
    settings = get_settings()
    if not settings.TMDB_API_KEY or not tmdb_id:
        return None
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.themoviedb.org/3/movie/{tmdb_id}",
            params={"api_key": settings.TMDB_API_KEY},
        )
        if resp.status_code != 200:
            logger.warning("TMDB API returned %d for tmdb_id=%d", resp.status_code, tmdb_id)
            return None
        data = resp.json()
        poster_path = data.get("poster_path")
        if poster_path:
            return f"https://image.tmdb.org/t/p/w500{poster_path}"
        return None


async def backfill_posters(db: AsyncSession) -> None:
    """Fetch poster URLs for movies that have tmdb_id but no poster_url."""
    stmt = (
        select(Movie)
        .where(Movie.tmdb_id.isnot(None), Movie.poster_url.is_(None))
        .limit(50)
    )
    result = await db.execute(stmt)
    movies = result.scalars().all()

    if not movies:
        return

    logger.info("Backfilling posters for %d movies", len(movies))
    filled = 0
    for movie in movies:
        url = await fetch_poster_url(movie.tmdb_id)
        if url:
            movie.poster_url = url
            filled += 1

    if filled:
        await db.commit()
        logger.info("Backfilled %d poster URLs", filled)
