"""Backfill users.trakt_uuid for rows created before migration 027 (SEC-01).

For every row with trakt_uuid IS NULL and a stored Trakt token, read
/users/settings with that token (refreshing once if needed) and store
ids.uuid. Rows whose credentials no longer work have trakt_user_id cleared so
they can never be adopted through their slug; the owner gets a fresh account
on next login and can contact support to recover. Idempotent; safe to re-run.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
from sqlalchemy import select

from backend.config import get_settings
from backend.db import async_session_factory
from backend.db_models import User
from backend.services.trakt import TraktClient

logger = logging.getLogger("backfill_trakt_uuid")


async def _resolve_uuid(user: User, settings) -> str | None:
    client = TraktClient(client_id=settings.TRAKT_CLIENT_ID, access_token=user.trakt_access_token)
    try:
        profile = await client.get_profile()
        return str(profile["user"]["ids"]["uuid"])
    except (httpx.HTTPError, KeyError, TypeError):
        pass
    if not user.trakt_refresh_token:
        return None
    try:
        tokens = await TraktClient(client_id=settings.TRAKT_CLIENT_ID).refresh_token(
            user.trakt_refresh_token,
            client_secret=settings.TRAKT_CLIENT_SECRET,
            redirect_uri=settings.TRAKT_REDIRECT_URI,
        )
        user.trakt_access_token = tokens["access_token"]
        user.trakt_refresh_token = tokens.get("refresh_token", user.trakt_refresh_token)
        client = TraktClient(client_id=settings.TRAKT_CLIENT_ID, access_token=tokens["access_token"])
        profile = await client.get_profile()
        return str(profile["user"]["ids"]["uuid"])
    except (httpx.HTTPError, KeyError, TypeError):
        return None


async def main() -> None:
    settings = get_settings()
    resolved = cleared = skipped = 0
    async with async_session_factory() as db:
        rows = (
            await db.execute(
                select(User).where(User.trakt_uuid.is_(None), User.trakt_user_id.is_not(None))
            )
        ).scalars().all()
        logger.info("legacy_rows=%d", len(rows))
        for user in rows:
            if not user.trakt_access_token:
                user.trakt_user_id = None
                cleared += 1
                continue
            found = await _resolve_uuid(user, settings)
            if found:
                user.trakt_uuid = found
                resolved += 1
            else:
                # Credentials dead: make the row unadoptable by slug.
                user.trakt_user_id = None
                cleared += 1
            await db.flush()
        await db.commit()
    logger.info("done resolved=%d cleared=%d skipped=%d", resolved, cleared, skipped)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
