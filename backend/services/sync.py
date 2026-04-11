"""Rating sync service — pushes ELO-derived ratings to Trakt."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from backend.models import UserMovie
from backend.services.elo import elo_to_trakt_rating
from backend.services.trakt import TraktClient

logger = logging.getLogger(__name__)


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
            await client.rate_movie(um.movie.trakt_id, trakt_rating)
            synced += 1
        except Exception:
            logger.exception(
                "Failed to sync rating for trakt_id=%s", um.movie.trakt_id
            )
            failed += 1

    return {"synced": synced, "failed": failed}
