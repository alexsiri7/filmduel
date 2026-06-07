"""Rating sync service — pushes ELO-derived ratings to Trakt."""

from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from backend.config import get_settings
from backend.db_models import UserMovie
from backend.services.elo import elo_to_trakt_rating
from backend.services.trakt import TraktClient
from backend.services.simkl import SimklClient

logger = logging.getLogger(__name__)


async def _rate_with_retry(
    client: TraktClient, trakt_id: int, rating: int, media_type: str = "movie"
) -> None:
    """Submit a single rating to Trakt, retrying once on 5xx."""
    for attempt in range(2):
        try:
            await client.rate(trakt_id, rating, media_type=media_type)
            return
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status >= 500 and attempt == 0:
                logger.warning(
                    "Trakt 5xx (status=%d) for trakt_id=%s, retrying", status, trakt_id
                )
                continue
            logger.error(
                "Failed to sync rating for trakt_id=%s: HTTP %d", trakt_id, status
            )
            return
        except Exception:
            logger.exception("Unexpected error syncing trakt_id=%s", trakt_id)
            return


async def sync_post_duel(
    access_token: str,
    movie_ratings: list[tuple[int, int]],
    media_type: str = "movie",
) -> None:
    """Fire-and-forget: sync two specific movie/show ratings to Trakt after a duel.

    Args:
        access_token: User's current Trakt access token.
        movie_ratings: List of (trakt_id, elo) pairs to sync.
        media_type: "movie" or "show".
    """
    settings = get_settings()
    client = TraktClient(client_id=settings.TRAKT_CLIENT_ID, access_token=access_token)
    for trakt_id, elo in movie_ratings:
        rating = elo_to_trakt_rating(elo)
        await _rate_with_retry(client, trakt_id, rating, media_type)


async def sync_ratings_to_trakt(
    user_id: uuid.UUID,
    access_token: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """Sync all of a user's ELO rankings to Trakt as ratings.

    Returns a summary of synced/failed counts.
    """
    settings = get_settings()
    client = TraktClient(client_id=settings.TRAKT_CLIENT_ID, access_token=access_token)

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
            await client.rate(
                um.movie.trakt_id, trakt_rating, media_type=um.movie.media_type
            )
            synced += 1
        except Exception:
            logger.exception("Failed to sync rating for trakt_id=%s", um.movie.trakt_id)
            failed += 1

    return {"synced": synced, "failed": failed}


async def _rate_with_retry_simkl(
    client: SimklClient, simkl_id: int, rating: int, media_type: str = "movie"
) -> None:
    """Submit a single rating to SIMKL, retrying once on 5xx."""
    for attempt in range(2):
        try:
            await client.rate(simkl_id, rating, media_type=media_type)
            return
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status >= 500 and attempt == 0:
                logger.warning(
                    "SIMKL 5xx (status=%d) for simkl_id=%s, retrying",
                    status,
                    simkl_id,
                )
                continue
            logger.error(
                "Failed to sync rating for simkl_id=%s: HTTP %d", simkl_id, status
            )
            return
        except Exception:
            logger.exception("Unexpected error syncing simkl_id=%s", simkl_id)
            return


async def sync_post_duel_simkl(
    access_token: str,
    movie_ratings: list[tuple[int, int]],
    media_type: str = "movie",
) -> None:
    """Fire-and-forget: sync two specific movie/show ratings to SIMKL after a duel."""
    settings = get_settings()
    client = SimklClient(
        client_id=settings.SIMKL_CLIENT_ID, access_token=access_token
    )
    for simkl_id, elo in movie_ratings:
        rating = elo_to_trakt_rating(elo)
        await _rate_with_retry_simkl(client, simkl_id, rating, media_type)


async def sync_ratings_to_simkl(
    user_id: uuid.UUID,
    access_token: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """Sync all of a user's ELO rankings to SIMKL as ratings."""
    settings = get_settings()
    client = SimklClient(
        client_id=settings.SIMKL_CLIENT_ID, access_token=access_token
    )

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
        simkl_rating = elo_to_trakt_rating(um.elo)
        try:
            await client.rate(
                um.movie.trakt_id, simkl_rating, media_type=um.movie.media_type
            )
            synced += 1
        except Exception:
            logger.exception(
                "Failed to sync SIMKL rating for trakt_id=%s", um.movie.trakt_id
            )
            failed += 1

    return {"synced": synced, "failed": failed}
