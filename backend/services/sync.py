"""Rating sync service — pushes ELO-derived ratings to Trakt."""

from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from backend.db import async_session_factory
from backend.models import Movie, UserMovie
from backend.services.elo import elo_to_trakt_rating
from backend.services.trakt import TraktClient

logger = logging.getLogger(__name__)


async def _rate_with_retry(client: TraktClient, trakt_id: int, rating: int) -> None:
    """Call rate_movie and retry once on 5xx. Logs and swallows all failures."""
    try:
        await client.rate_movie(trakt_id, rating)
    except httpx.HTTPStatusError as e:
        if e.response.status_code >= 500:
            try:
                await client.rate_movie(trakt_id, rating)
            except Exception:
                logger.warning("Retry failed for trakt_id=%s: %s", trakt_id, e)
        elif e.response.status_code == 401:
            logger.warning("401 syncing trakt_id=%s — token may be expired", trakt_id)
        else:
            logger.warning("Failed to sync trakt_id=%s: %s", trakt_id, e)
    except Exception:
        logger.exception("Unexpected error syncing trakt_id=%s", trakt_id)


async def sync_duel_ratings(
    user_id: str,
    access_token: str,
    movie_a_id: str,
    movie_b_id: str,
) -> None:
    """Background task: sync ELO ratings for two duel movies to Trakt.

    Fetches the user's full ELO range for normalization, then syncs the
    two movies from the completed duel. Retries once on 5xx. Swallows all
    errors so failures never surface to the user.
    """
    try:
        uid = uuid.UUID(user_id)
        mid_a = uuid.UUID(movie_a_id)
        mid_b = uuid.UUID(movie_b_id)

        async with async_session_factory() as session:
            # Fetch all user_movie ELOs for normalization range
            all_stmt = select(UserMovie.elo).where(
                UserMovie.user_id == uid,
                UserMovie.seen.is_(True),
                UserMovie.battles > 0,
            )
            result = await session.execute(all_stmt)
            all_elos = [row[0] for row in result.all()]
            if not all_elos:
                return

            min_elo = min(all_elos)
            max_elo = max(all_elos)

            # Fetch trakt_ids for the two movies
            movies_stmt = select(Movie.id, Movie.trakt_id).where(
                Movie.id.in_([mid_a, mid_b])
            )
            result = await session.execute(movies_stmt)
            trakt_map = {row.id: row.trakt_id for row in result.all()}

            # Fetch ELOs for the two movies
            um_stmt = select(UserMovie.movie_id, UserMovie.elo).where(
                UserMovie.user_id == uid,
                UserMovie.movie_id.in_([mid_a, mid_b]),
            )
            result = await session.execute(um_stmt)
            elo_map = {row.movie_id: row.elo for row in result.all()}

        client = TraktClient(access_token=access_token)
        for mid in [mid_a, mid_b]:
            if mid in trakt_map and mid in elo_map:
                trakt_rating = elo_to_trakt_rating(elo_map[mid])
                await _rate_with_retry(client, trakt_map[mid], trakt_rating)

    except Exception:
        logger.exception("Error in background duel sync for user %s", user_id)


async def sync_ratings_to_trakt(
    user_id: uuid.UUID,
    access_token: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """Sync all of a user's ELO rankings to Trakt as ratings.

    Returns a summary of synced/failed counts.
    """
    client = TraktClient(access_token=access_token)

    stmt = (
        select(UserMovie)
        .options(joinedload(UserMovie.movie))
        .where(
            UserMovie.user_id == user_id,
            UserMovie.seen.is_(True),
            UserMovie.battles > 0,
        )
    )
    result = await db.execute(stmt)
    user_movies = result.unique().scalars().all()

    if not user_movies:
        return {"synced": 0, "failed": 0, "message": "No rankings to sync"}

    synced = 0
    failed = 0

    for um in user_movies:
        trakt_rating = elo_to_trakt_rating(um.elo)
        try:
            await _rate_with_retry(client, um.movie.trakt_id, trakt_rating)
            synced += 1
        except Exception:
            logger.exception(
                "Failed to sync rating for trakt_id=%s", um.movie.trakt_id
            )
            failed += 1

    return {"synced": synced, "failed": failed}
