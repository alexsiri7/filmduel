"""Trakt OAuth2 authentication routes."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import jwt
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import Settings, get_settings
from backend.db import async_session_factory, get_db
from backend.db_models import User
from backend.schemas import UserResponse
from backend.services.pool import populate_movie_pool
from backend.services.tmdb import backfill_posters
from backend.services.trakt import TraktClient

router = APIRouter(tags=["auth"])

COOKIE_NAME = "filmduel_session"
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 72


def create_jwt(user_id: str, settings: Settings) -> str:
    """Create a signed JWT for session management."""
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=JWT_ALGORITHM)


def get_current_user_id(request: Request) -> str:
    """Extract and verify user ID from session cookie."""
    settings = get_settings()
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload["sub"]
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid session")


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
    user.trakt_token_expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=tokens.get("expires_in", 7776000)
    )
    user.last_seen_at = datetime.now(timezone.utc)
    await db.flush()

    return user


async def _backfill_posters_background() -> None:
    """Run poster backfill in a standalone session (background task)."""
    async with async_session_factory() as session:
        await backfill_posters(session)


async def _sync_pool_background(user_id) -> None:
    """Run pool sync in a background task with its own DB session."""
    import logging

    logger = logging.getLogger(__name__)
    try:
        async with async_session_factory() as session:
            stmt = select(User).where(User.id == user_id)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            if user:
                await populate_movie_pool(user, session)
                await session.commit()
    except Exception:
        logger.exception("Background pool sync failed for user %s", user_id)


@router.get("/auth/login")
async def login(settings: Settings = Depends(get_settings)):
    """Redirect the user to Trakt's OAuth authorization page."""
    params = urlencode(
        {
            "response_type": "code",
            "client_id": settings.TRAKT_CLIENT_ID,
            "redirect_uri": settings.TRAKT_REDIRECT_URI,
        }
    )
    return RedirectResponse(f"https://trakt.tv/oauth/authorize?{params}")


@router.get("/auth/callback")
async def callback(
    code: str,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
):
    """Handle the OAuth callback from Trakt."""
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
    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=tokens.get("expires_in", 7776000)
    )

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
    background_tasks.add_task(_sync_pool_background, user_id)

    # Backfill missing poster URLs in the background
    background_tasks.add_task(_backfill_posters_background)

    # Set session cookie
    token = create_jwt(str(user.id), settings)
    response = RedirectResponse(url=settings.BASE_URL)
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=JWT_EXPIRY_HOURS * 3600,
    )
    return response


@router.post("/auth/logout")
async def logout():
    """Clear the session cookie."""
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
    )
