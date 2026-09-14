"""Rating sync service — pushes ELO-derived ratings to Trakt."""

from __future__ import annotations

import logging
import uuid

import httpx
from sqlalchemy import select

from backend.config import get_settings
from backend.db import async_session_factory
from backend.db_models import Movie, User
from backend.services.elo import elo_to_trakt_rating
from backend.services.token_refresh import ensure_fresh_token
from backend.services.trakt import TraktClient

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


async def sync_ratings_background(
    user_id: uuid.UUID,
    movie_a_id: uuid.UUID,
    new_elo_a: int,
    movie_b_id: uuid.UUID,
    new_elo_b: int,
) -> None:
    """Fire-and-forget Trakt rating sync after a duel with a winner."""
    try:
        async with async_session_factory() as session:
            user_stmt = select(User).where(User.id == user_id).with_for_update()
            result = await session.execute(user_stmt)
            user = result.scalar_one_or_none()
            if (
                not user
                or not user.trakt_access_token
                or not user.sync_ratings_to_trakt
            ):
                return
            user = await ensure_fresh_token(user, session)
            await session.commit()
            access_token = user.trakt_access_token
            movies_stmt = select(Movie.id, Movie.trakt_id, Movie.media_type).where(
                Movie.id.in_([movie_a_id, movie_b_id])
            )
            result = await session.execute(movies_stmt)
            rows = result.all()
            trakt_map = {row.id: row.trakt_id for row in rows}
            # Both movies in a duel are the same media_type
            media_type = rows[0].media_type if rows else "movie"
        movie_ratings = []
        if movie_a_id in trakt_map:
            movie_ratings.append((trakt_map[movie_a_id], new_elo_a))
        if movie_b_id in trakt_map:
            movie_ratings.append((trakt_map[movie_b_id], new_elo_b))
        if movie_ratings:
            await sync_post_duel(access_token, movie_ratings, media_type)
    except Exception:
        logger.exception(
            "Background rating sync failed for user %s (token refresh or sync error)",
            user_id,
        )
