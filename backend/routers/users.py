"""User profile, settings, consent, and sync routes."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.db import async_session_factory, get_db
from backend.rate_limit import limiter
from backend.db_models import User, UserMovie
from backend.routers.auth import (
    delete_session_cookie,
    ensure_fresh_token,
    ensure_fresh_simkl_token,
    get_current_user,
    require_consent,
)
from backend.schemas import ConsentAccept, UserResponse, UserSettingsUpdate
from backend.services.data_export import export_user_data
from backend.services.pool import populate_movie_pool
from backend.services.tmdb import backfill_posters_background
from backend.services.trakt import TraktClient
from backend.services.simkl import SimklClient

logger = logging.getLogger(__name__)

router = APIRouter(tags=["users"])

# When updating the privacy policy:
# 1. Update this constant to the new version string
# 2. Update CURRENT_PRIVACY_POLICY_VERSION in frontend/src/constants.js to match
# 3. Update the privacy policy text in frontend/src/pages/PrivacyPolicy.jsx
# Mismatch between this constant and the stored user value triggers re-consent for existing users.
CURRENT_PRIVACY_POLICY_VERSION = "2.1"

# An import still "importing" after this long is reported as failed: its process
# died (e.g. a deploy restart). Must exceed the worst case of every provider
# fetch exhausting its retries (~13 minutes).
POOL_IMPORT_STALE_AFTER = timedelta(minutes=20)


def _effective_pool_import_status(user: User) -> str | None:
    if user.pool_import_status != "importing":
        return user.pool_import_status
    started = user.pool_import_started_at
    if started is None:
        return "failed"
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - started > POOL_IMPORT_STALE_AFTER:
        return "failed"
    return "importing"


def _build_user_response(user: User) -> UserResponse:
    return UserResponse(
        id=str(user.id),
        trakt_username=user.trakt_username,
        simkl_username=user.simkl_username,
        created_at=user.created_at,
        sync_ratings_to_trakt=user.sync_ratings_to_trakt,
        sync_ratings_to_simkl=user.sync_ratings_to_simkl,
        use_ai_features=user.use_ai_features,
        privacy_policy_accepted=user.privacy_policy_accepted,
        privacy_policy_version=user.privacy_policy_version,
        pool_import_status=_effective_pool_import_status(user),
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
    if body.sync_ratings_to_trakt is not None:
        current_user.sync_ratings_to_trakt = body.sync_ratings_to_trakt
    if body.sync_ratings_to_simkl is not None:
        current_user.sync_ratings_to_simkl = body.sync_ratings_to_simkl
    if body.use_ai_features is not None:
        current_user.use_ai_features = body.use_ai_features
    await db.commit()
    return _build_user_response(current_user)


async def _force_pool_sync(user: User, db: AsyncSession) -> tuple[User, bool]:
    """Refresh provider tokens, then run a pool sync that bypasses the 1-hour cooldown.

    The bool is False when some provider fetch failed after retries.
    """
    if user.trakt_access_token_enc:
        user = await ensure_fresh_token(user, db)
    if user.simkl_access_token_enc:
        user = await ensure_fresh_simkl_token(user, db)

    complete = await populate_movie_pool(user, db, force=True)
    return user, complete


def _start_pool_import(user: User) -> None:
    user.pool_import_status = "importing"
    user.pool_import_started_at = datetime.now(timezone.utc)


def _record_pool_import_outcome(user_id: uuid.UUID, started_at: datetime, status: str):
    # A retry restamps started_at, so a superseded run's outcome matches no row.
    return (
        update(User)
        .where(User.id == user_id, User.pool_import_started_at == started_at)
        .values(pool_import_status=status)
    )


async def _run_pool_import(user_id: uuid.UUID, started_at: datetime) -> None:
    """Background provider import that records its outcome in pool_import_status."""
    try:
        async with async_session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return
            user, complete = await _force_pool_sync(user, session)
            await session.execute(
                _record_pool_import_outcome(
                    user_id, started_at, "complete" if complete else "failed"
                )
            )
            await session.commit()
            return
    except Exception:
        logger.exception("Pool import failed for user %s", user_id)

    try:
        async with async_session_factory() as session:
            await session.execute(_record_pool_import_outcome(user_id, started_at, "failed"))
            await session.commit()
    except Exception:
        logger.exception("Could not mark pool import failed for user %s", user_id)


@router.post("/api/me/consent", response_model=UserResponse)
@limiter.limit("10/minute")
async def accept_consent(
    body: ConsentAccept,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record that the user has accepted the privacy policy (GDPR consent).

    The first acceptance also starts the initial provider import in the
    background; its progress is reported as pool_import_status.
    """
    if body.version != CURRENT_PRIVACY_POLICY_VERSION:
        raise HTTPException(
            status_code=400,
            detail=f"Unrecognized policy version. Expected '{CURRENT_PRIVACY_POLICY_VERSION}'.",
        )
    first_consent = not current_user.privacy_policy_accepted
    current_user.privacy_policy_accepted = True
    current_user.privacy_policy_accepted_at = datetime.now(timezone.utc)
    current_user.privacy_policy_version = CURRENT_PRIVACY_POLICY_VERSION
    if first_consent:
        _start_pool_import(current_user)
    await db.commit()

    if first_consent:
        # Initial library import is deferred from the OAuth callback to here so no
        # provider data is ingested before consent is recorded (#571).
        background_tasks.add_task(
            _run_pool_import, current_user.id, current_user.pool_import_started_at
        )
        background_tasks.add_task(backfill_posters_background)

    return _build_user_response(current_user)


@router.post("/api/me/pool-import", response_model=UserResponse)
@limiter.limit("3/hour")
async def retry_pool_import(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_consent),
    db: AsyncSession = Depends(get_db),
):
    """Manually retry the background provider import (#653).

    A no-op while an import is still running.
    """
    if _effective_pool_import_status(current_user) == "importing":
        return _build_user_response(current_user)

    _start_pool_import(current_user)
    await db.commit()
    background_tasks.add_task(
        _run_pool_import, current_user.id, current_user.pool_import_started_at
    )
    background_tasks.add_task(backfill_posters_background)
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
    settings = get_settings()
    if current_user.trakt_access_token_enc:
        trakt_client = TraktClient(client_id=settings.TRAKT_CLIENT_ID)
        await trakt_client.revoke_token(
            current_user.trakt_access_token,
            client_secret=settings.TRAKT_CLIENT_SECRET,
        )
    if current_user.simkl_access_token_enc:
        simkl_client = SimklClient(client_id=settings.SIMKL_CLIENT_ID)
        await simkl_client.revoke_token(
            current_user.simkl_access_token,
            client_secret=settings.SIMKL_CLIENT_SECRET,
        )

    await db.execute(delete(User).where(User.id == current_user.id))
    await db.commit()

    response = Response(status_code=204)
    delete_session_cookie(response, settings)
    return response


@router.get("/api/me/export")
# per-user via _rate_limit_key; matches the rankings CSV export cap
@limiter.limit("10/hour")
async def export_my_data(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Download every personal-data record held for the user as JSON (GDPR Art. 15 / 20).

    Uses get_current_user, not require_consent: the right of access does not
    depend on consent, and a user who withdrew it still needs their data out.
    """
    payload = await export_user_data(db, current_user)
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": "attachment; filename=filmduel_data_export.json"},
    )


@router.post("/api/sync")
@limiter.limit("3/hour")
async def sync_providers(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_consent),
    db: AsyncSession = Depends(get_db),
):
    """Trigger a manual re-sync, bypassing the 1-hour cooldown.

    Rate limited to 3 calls per hour per user.
    """

    # Count movies before sync so we can report new additions
    before_count = await db.scalar(
        select(func.count())
        .select_from(UserMovie)
        .where(UserMovie.user_id == current_user.id)
    ) or 0

    current_user, _ = await _force_pool_sync(current_user, db)
    await db.commit()

    # Count movies after sync
    after_count = await db.scalar(
        select(func.count())
        .select_from(UserMovie)
        .where(UserMovie.user_id == current_user.id)
    ) or 0
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
