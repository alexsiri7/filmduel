"""Rating sync service — pushes ELO-derived ratings to Trakt."""

from __future__ import annotations

import logging

import httpx

from backend.config import get_settings
from backend.services.elo import elo_to_trakt_rating
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
