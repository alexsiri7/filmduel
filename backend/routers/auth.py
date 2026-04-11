"""Trakt OAuth2 authentication routes."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import Settings, get_settings
from backend.db import get_db
from backend.models import User, UserResponse
from backend.services.trakt import TraktClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

COOKIE_NAME = "filmduel_session"
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 72
TOKEN_REFRESH_WINDOW_SECONDS = 3600  # refresh when within 1 hour of expiry


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

    client = TraktClient()
    tokens = await client.refresh_token(user.trakt_refresh_token)

    user.trakt_access_token = tokens["access_token"]
    user.trakt_refresh_token = tokens.get("refresh_token", user.trakt_refresh_token)
    user.trakt_token_expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=tokens.get("expires_in", 7776000)
    )
    user.last_seen_at = datetime.now(timezone.utc)
    await db.flush()

    return user


@router.get("/login")
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


@router.get("/callback")
async def callback(
    code: str,
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
):
    """Handle the OAuth callback from Trakt."""
    client = TraktClient()
    tokens = await client.exchange_code(code)

    # Fetch user profile
    authed_client = TraktClient(access_token=tokens["access_token"])
    profile = await authed_client.get_user_profile()

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
        user.last_seen_at = datetime.now(timezone.utc)
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


@router.post("/logout")
async def logout():
    """Clear the session cookie."""
    response = Response(status_code=204)
    response.delete_cookie(COOKIE_NAME)
    return response


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    """Return the current authenticated user's profile."""
    return UserResponse(
        id=str(user.id),
        trakt_username=user.trakt_username,
        created_at=user.created_at,
    )
