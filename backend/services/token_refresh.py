"""Trakt access-token refresh, shared by every router that calls Trakt."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.db_models import User
from backend.services.trakt import TraktClient

logger = logging.getLogger(__name__)

# Trakt's documented token lifetime is 90 days (7776000 s).
# Used as a fallback when expires_in is absent from the API response.
TRAKT_TOKEN_DEFAULT_TTL_SECONDS = 7776000


async def ensure_fresh_token(user: User, db: AsyncSession) -> User:
    """Refresh the Trakt access token if it expires within 1 hour.

    Call this before any Trakt API request that needs a valid token.
    Returns the user with up-to-date tokens (already flushed to the session).
    """
    if not user.trakt_token_expires_at or not user.trakt_access_token_enc:
        return user  # no Trakt token to refresh

    now = datetime.now(timezone.utc)
    expires_at = user.trakt_token_expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at - now > timedelta(hours=1):
        return user

    settings = get_settings()
    client = TraktClient(client_id=settings.TRAKT_CLIENT_ID)
    tokens = await client.refresh_token(
        user.trakt_refresh_token,
        client_secret=settings.TRAKT_CLIENT_SECRET,
        redirect_uri=settings.TRAKT_REDIRECT_URI,
    )

    user.trakt_access_token = tokens["access_token"]
    user.trakt_refresh_token = tokens.get("refresh_token", user.trakt_refresh_token)
    ttl = tokens.get("expires_in")
    if ttl is None:
        logger.warning("Trakt refresh response missing expires_in; using default TTL")
        ttl = TRAKT_TOKEN_DEFAULT_TTL_SECONDS
    user.trakt_token_expires_at = now + timedelta(seconds=ttl)
    user.last_seen_at = now
    await db.flush()

    return user
