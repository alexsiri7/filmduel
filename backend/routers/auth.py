"""Trakt OAuth2 authentication routes."""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import jwt
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
)
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import Settings, get_settings
from backend.rate_limit import limiter
from backend.db import async_session_factory, get_db
from backend.db_models import User, UserMovie
from backend.schemas import UserResponse, UserSettingsUpdate
from backend.services.pool import populate_movie_pool
from backend.services.tmdb import backfill_posters
from backend.services.trakt import TraktClient

logger = logging.getLogger(__name__)

# Trakt's documented token lifetime is 90 days (7776000 s).
# Used as a fallback when expires_in is absent from the API response.
_TRAKT_TOKEN_DEFAULT_TTL_SECONDS = 7776000

router = APIRouter(tags=["auth"])

COOKIE_NAME = "filmduel_session"
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 72  # 3-day absolute lifetime per issued token
REFRESH_INTERVAL = timedelta(hours=12)  # re-issue cookie at most once per 12h


def create_jwt(user_id: str, settings: Settings) -> str:
    """Create a signed JWT for session management."""
    payload = {
        "sub": user_id,
        "jti": secrets.token_hex(16),
        "iss": "filmduel",
        "aud": "filmduel",
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=JWT_ALGORITHM)


def set_session_cookie(response: Response, user_id: str, settings: Settings) -> None:
    """Issue a fresh session cookie for user_id."""
    response.set_cookie(
        COOKIE_NAME,
        create_jwt(user_id, settings),
        httponly=True,
        secure=settings.is_https,
        samesite="lax",
        max_age=JWT_EXPIRY_HOURS * 3600,
    )


async def get_current_user_id(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> str:
    """Extract and verify user ID from session cookie.

    Also performs server-side revocation check (catches logout from another
    device) and re-issues the cookie at most once per REFRESH_INTERVAL
    (bounded sliding session).
    """
    settings = get_settings()
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
            issuer="filmduel",
            audience="filmduel",
        )
        user_id = payload.get("sub")
        iat = datetime.fromtimestamp(payload["iat"], tz=timezone.utc)
        if not user_id:
            raise HTTPException(
                status_code=401, detail="Invalid session — missing subject"
            )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid session")

    # Server-side revocation: catches logout from another device or admin revoke.
    invalid_before = await db.scalar(
        select(User.tokens_invalid_before).where(User.id == uuid.UUID(user_id))
    )
    if invalid_before is None:
        raise HTTPException(status_code=401, detail="User not found")
    if invalid_before.tzinfo is None:
        invalid_before = invalid_before.replace(tzinfo=timezone.utc)
    if iat < invalid_before:
        raise HTTPException(status_code=401, detail="Session revoked")

    # Sliding refresh: only re-issue if the token is older than REFRESH_INTERVAL.
    if datetime.now(timezone.utc) - iat > REFRESH_INTERVAL:
        set_session_cookie(response, user_id, settings)
    return user_id


async def get_current_user(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> User:
    """FastAPI dependency: validate JWT cookie and return the full User row."""
    stmt = select(User).where(User.id == uuid.UUID(user_id))
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def ensure_fresh_token(user: User, db: AsyncSession) -> User:
    """Refresh the Trakt access token if it expires within 1 hour.

    Call this before any Trakt API request that needs a valid token.
    Returns the user with up-to-date tokens (already flushed to the session).
    """
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
        ttl = _TRAKT_TOKEN_DEFAULT_TTL_SECONDS
    user.trakt_token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
    user.last_seen_at = datetime.now(timezone.utc)
    await db.flush()

    return user


async def _backfill_posters_background() -> None:
    """Run poster backfill in a standalone session (background task)."""
    async with async_session_factory() as session:
        await backfill_posters(session)


async def _sync_pool_background(user_id, force: bool = False) -> None:
    """Run pool sync in a background task with its own DB session."""
    try:
        async with async_session_factory() as session:
            stmt = select(User).where(User.id == user_id)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            if user:
                if force:
                    # Reset last_seen_at so the throttle doesn't skip
                    user.last_seen_at = datetime.now(timezone.utc) - timedelta(hours=2)
                    await session.flush()
                await populate_movie_pool(user, session)
                await session.commit()
    except Exception:
        logger.exception("Background pool sync failed for user %s", user_id)


OAUTH_STATE_COOKIE = "filmduel_oauth_state"


@router.get("/auth/login")
@limiter.limit("10/minute")
async def login(request: Request, settings: Settings = Depends(get_settings)):
    """Redirect the user to Trakt's OAuth authorization page."""
    state = secrets.token_urlsafe(32)
    params = urlencode(
        {
            "response_type": "code",
            "client_id": settings.TRAKT_CLIENT_ID,
            "redirect_uri": settings.TRAKT_REDIRECT_URI,
            "state": state,
        }
    )
    response = RedirectResponse(f"https://trakt.tv/oauth/authorize?{params}")
    response.set_cookie(
        OAUTH_STATE_COOKIE,
        state,
        httponly=True,
        secure=settings.is_https,
        samesite="lax",
        max_age=300,
    )
    return response


@router.get("/auth/callback")
@limiter.limit("10/minute")
async def callback(
    code: str,
    request: Request,
    background_tasks: BackgroundTasks,
    state: str | None = None,
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
):
    """Handle the OAuth callback from Trakt."""
    # Validate OAuth state parameter to prevent CSRF
    expected_state = request.cookies.get(OAUTH_STATE_COOKIE)
    if not expected_state or not state or state != expected_state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    client = TraktClient(client_id=settings.TRAKT_CLIENT_ID)
    tokens = await client.exchange_code(
        code,
        client_secret=settings.TRAKT_CLIENT_SECRET,
        redirect_uri=settings.TRAKT_REDIRECT_URI,
    )

    # Fetch user profile
    authed_client = TraktClient(
        client_id=settings.TRAKT_CLIENT_ID,
        access_token=tokens["access_token"],
    )
    profile = await authed_client.get_profile()

    trakt_user_id = str(profile["ids"]["slug"])
    ttl = tokens.get("expires_in")
    if ttl is None:
        logger.warning(
            "Trakt exchange_code response missing expires_in; using default TTL"
        )
        ttl = _TRAKT_TOKEN_DEFAULT_TTL_SECONDS
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)

    # Check if user exists
    stmt = select(User).where(User.trakt_user_id == trakt_user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user:
        user.trakt_username = profile["username"]
        user.trakt_access_token = tokens["access_token"]
        user.trakt_refresh_token = tokens.get("refresh_token", "")
        user.trakt_token_expires_at = expires_at
        # Note: last_seen_at is updated by populate_movie_pool after sync
    else:
        user = User(
            trakt_user_id=trakt_user_id,
            trakt_username=profile["username"],
            trakt_access_token=tokens["access_token"],
            trakt_refresh_token=tokens.get("refresh_token", ""),
            trakt_token_expires_at=expires_at,
        )
        db.add(user)

    await db.flush()

    # Kick off movie pool import in the background (uses its own DB session)
    user_id = user.id
    background_tasks.add_task(_sync_pool_background, user_id, force=True)

    # Backfill missing poster URLs in the background
    background_tasks.add_task(_backfill_posters_background)

    response = RedirectResponse(url=settings.BASE_URL)
    set_session_cookie(response, str(user.id), settings)
    response.delete_cookie(OAUTH_STATE_COOKIE)
    return response


@router.post("/auth/logout")
@limiter.limit("10/minute")
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Clear the session cookie and revoke all previously issued JWTs."""
    await db.execute(
        update(User)
        .where(User.id == uuid.UUID(user_id))
        .values(tokens_invalid_before=datetime.now(timezone.utc))
    )
    await db.commit()
    response = Response(status_code=204)
    response.delete_cookie(COOKIE_NAME)
    return response


@router.get("/api/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    """Return the current authenticated user's profile."""
    return UserResponse(
        id=str(user.id),
        trakt_username=user.trakt_username,
        created_at=user.created_at,
        sync_ratings_to_trakt=user.sync_ratings_to_trakt,
    )


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
    return UserResponse(
        id=str(current_user.id),
        trakt_username=current_user.trakt_username,
        created_at=current_user.created_at,
        sync_ratings_to_trakt=current_user.sync_ratings_to_trakt,
    )


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
    background_tasks.add_task(_backfill_posters_background)

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
