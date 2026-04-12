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


# TMDB genre_id -> genre name mapping (from TMDB API /genre/movie/list)
TMDB_GENRE_MAP: dict[int, str] = {
    28: "action", 12: "adventure", 16: "animation", 35: "comedy", 80: "crime",
    99: "documentary", 18: "drama", 10751: "family", 14: "fantasy", 36: "history",
    27: "horror", 10402: "music", 9648: "mystery", 10749: "romance",
    878: "science-fiction", 10770: "tv movie", 53: "thriller", 10752: "war",
    37: "western",
}


async def fetch_similar_films(tmdb_id: int, api_key: str) -> list[dict]:
    """Fetch recommended films from TMDB for a given movie.

    Returns list of dicts with keys: tmdb_id, title, year, overview, genres.
    """
    if not api_key or not tmdb_id:
        return []
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.themoviedb.org/3/movie/{tmdb_id}/recommendations",
                params={"api_key": api_key},
                timeout=10.0,
            )
            if resp.status_code != 200:
                logger.warning(
                    "TMDB recommendations returned %d for tmdb_id=%d",
                    resp.status_code, tmdb_id,
                )
                return []
            data = resp.json()
            results = []
            for item in data.get("results", []):
                release_date = item.get("release_date", "")
                year = int(release_date[:4]) if release_date and len(release_date) >= 4 else None
                genres = [
                    TMDB_GENRE_MAP[gid] for gid in item.get("genre_ids", [])
                    if gid in TMDB_GENRE_MAP
                ]
                results.append({
                    "tmdb_id": item["id"],
                    "title": item.get("title", "Unknown"),
                    "year": year,
                    "overview": item.get("overview"),
                    "genres": genres,
                })
            return results
    except Exception:
        logger.exception("Failed to fetch TMDB recommendations for tmdb_id=%d", tmdb_id)
        return []


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
