"""Rating sync service — pushes ELO-derived ratings to Trakt."""

from __future__ import annotations

import logging
from typing import Any

from backend.db import get_supabase
from backend.services.trakt import TraktClient

logger = logging.getLogger(__name__)


def elo_to_trakt_rating(elo: float, min_elo: float, max_elo: float) -> int:
    """Map an ELO rating to Trakt's 1-10 scale.

    Linearly maps the user's ELO range onto 1-10.
    """
    if max_elo == min_elo:
        return 5
    normalized = (elo - min_elo) / (max_elo - min_elo)
    return max(1, min(10, round(normalized * 9) + 1))


async def sync_ratings_to_trakt(user_id: str, access_token: str) -> dict[str, Any]:
    """Sync all of a user's ELO rankings to Trakt as ratings.

    Returns a summary of synced/failed counts.
    """
    db = get_supabase()
    client = TraktClient(access_token=access_token)

    # Fetch user's rankings
    result = db.table("rankings").select("*").eq("user_id", user_id).execute()
    rankings = result.data or []

    if not rankings:
        return {"synced": 0, "failed": 0, "message": "No rankings to sync"}

    elos = [r["elo_rating"] for r in rankings]
    min_elo = min(elos)
    max_elo = max(elos)

    synced = 0
    failed = 0

    for ranking in rankings:
        trakt_rating = elo_to_trakt_rating(ranking["elo_rating"], min_elo, max_elo)
        try:
            await client.rate_movie(ranking["trakt_id"], trakt_rating)
            synced += 1
        except Exception:
            logger.exception("Failed to sync rating for trakt_id=%s", ranking["trakt_id"])
            failed += 1

    return {"synced": synced, "failed": failed}
