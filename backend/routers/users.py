"""User profile, settings, consent, and sync routes."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.db import get_db
from backend.rate_limit import limiter
from backend.db_models import User, UserMovie
from backend.routers.auth import (
    COOKIE_NAME,
    ensure_fresh_token,
    get_current_user,
)
from backend.schemas import ConsentAccept, UserResponse, UserSettingsUpdate
from backend.services.pool import populate_movie_pool, sync_pool_background
from backend.services.tmdb import backfill_posters_background
from backend.services.trakt import TraktClient

logger = logging.getLogger(__name__)

router = APIRouter(tags=["users"])

# Must match the version string sent by frontend/src/components/ConsentModal.jsx
CURRENT_PRIVACY_POLICY_VERSION = "1.0"


def _build_user_response(user: User) -> UserResponse:
    return UserResponse(
        id=str(user.id),
        trakt_username=user.trakt_username,
        created_at=user.created_at,
        sync_ratings_to_trakt=user.sync_ratings_to_trakt,
        privacy_policy_accepted=user.privacy_policy_accepted,
    )


@router.get("/api/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    """Return the current authenticated user's profile."""
    return _build_user_response(user)


@router.patch("/api/me/settings", response_model=UserResponse)
@limiter.limit("30/minute")
async def update_settings(
    body: UserSettingsUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update user preferences."""
    current_user.sync_ratings_to_trakt = body.sync_ratings_to_trakt
    await db.commit()
    return _build_user_response(current_user)


@router.post("/api/me/consent", response_model=UserResponse)
@limiter.limit("10/minute")
async def accept_consent(
    body: ConsentAccept,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record that the user has accepted the privacy policy (GDPR consent)."""
    if body.version != CURRENT_PRIVACY_POLICY_VERSION:
        raise HTTPException(
            status_code=400,
            detail=f"Unrecognized policy version '{body.version}'. Expected '{CURRENT_PRIVACY_POLICY_VERSION}'.",
        )
    current_user.privacy_policy_accepted = True
    current_user.privacy_policy_accepted_at = datetime.now(timezone.utc)
    current_user.privacy_policy_version = CURRENT_PRIVACY_POLICY_VERSION
    await db.commit()
    return _build_user_response(current_user)


@router.delete("/api/me", status_code=204)
@limiter.limit("3/hour")
async def delete_account(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete the authenticated user's account (GDPR Art. 17).

    Best-effort revokes the Trakt access token at the upstream, then
    cascade-deletes the User row (and all dependent rows via ON DELETE CASCADE).
    """
    from fastapi import Response

    settings = get_settings()
    client = TraktClient(client_id=settings.TRAKT_CLIENT_ID)
    await client.revoke_token(
        current_user.trakt_access_token,
        client_secret=settings.TRAKT_CLIENT_SECRET,
    )

    await db.execute(delete(User).where(User.id == current_user.id))
    await db.commit()

    response = Response(status_code=204)
    response.delete_cookie(COOKIE_NAME)
    return response


@router.post("/api/sync")
@limiter.limit("3/hour")
async def sync_trakt(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger a manual Trakt re-sync, bypassing the 1-hour cooldown.

    Rate limited to 3 calls per hour per user.
    """

    # Count movies before sync so we can report new additions
    before_count_result = await db.execute(
        select(func.count())
        .select_from(UserMovie)
        .where(UserMovie.user_id == current_user.id)
    )
    before_count = before_count_result.scalar() or 0

    # Ensure fresh Trakt token
    current_user = await ensure_fresh_token(current_user, db)

    # Force sync (bypass cooldown by resetting last_seen_at)
    current_user.last_seen_at = datetime.now(timezone.utc) - timedelta(hours=2)
    await db.flush()

    await populate_movie_pool(current_user, db)
    await db.commit()

    # Count movies after sync
    after_count_result = await db.execute(
        select(func.count())
        .select_from(UserMovie)
        .where(UserMovie.user_id == current_user.id)
    )
    after_count = after_count_result.scalar() or 0
    new_movies = max(0, after_count - before_count)

    # Backfill posters in background
    background_tasks.add_task(backfill_posters_background)

    logger.info(
        "Manual sync user_id=%s: %d new movies (total: %d)",
        current_user.id,
        new_movies,
        after_count,
    )

    return {
        "new_movies": new_movies,
        "total_movies": after_count,
    }
