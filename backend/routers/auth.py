"""Trakt OAuth2 authentication routes."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import jwt
from fastapi import APIRouter, Depends, HTTPException, Response, Request
from fastapi.responses import RedirectResponse

from backend.config import Settings, get_settings
from backend.db import get_supabase
from backend.models import UserResponse
from backend.services.trakt import TraktClient

router = APIRouter(prefix="/api/auth", tags=["auth"])

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
async def callback(code: str, settings: Settings = Depends(get_settings)):
    """Handle the OAuth callback from Trakt."""
    client = TraktClient()
    tokens = await client.exchange_code(code)

    # Fetch user profile
    authed_client = TraktClient(access_token=tokens["access_token"])
    profile = await authed_client.get_user_profile()

    db = get_supabase()

    # Upsert user record
    user_data = {
        "trakt_username": profile["username"],
        "trakt_slug": profile["ids"]["slug"],
        "trakt_access_token": tokens["access_token"],
        "trakt_refresh_token": tokens.get("refresh_token", ""),
        "avatar_url": profile.get("images", {}).get("avatar", {}).get("full"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Check if user exists
    existing = (
        db.table("users")
        .select("id")
        .eq("trakt_slug", profile["ids"]["slug"])
        .execute()
    )

    if existing.data:
        user_id = existing.data[0]["id"]
        db.table("users").update(user_data).eq("id", user_id).execute()
    else:
        user_id = str(uuid.uuid4())
        user_data["id"] = user_id
        user_data["created_at"] = datetime.now(timezone.utc).isoformat()
        db.table("users").insert(user_data).execute()

    # Set session cookie
    token = create_jwt(user_id, settings)
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
async def me(user_id: str = Depends(get_current_user_id)):
    """Return the current authenticated user's profile."""
    db = get_supabase()
    result = db.table("users").select("*").eq("id", user_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="User not found")
    user = result.data[0]
    return UserResponse(
        id=user["id"],
        trakt_username=user["trakt_username"],
        trakt_slug=user["trakt_slug"],
        avatar_url=user.get("avatar_url"),
        created_at=user["created_at"],
    )
