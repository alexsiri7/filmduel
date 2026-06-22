"""Trakt OAuth2 authentication routes."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import NoReturn
from urllib.parse import urlencode

import httpx
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
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import Settings, get_settings
from backend.rate_limit import limiter
from backend.db import get_db
from backend.db_models import User
from backend.services.pool import sync_pool_background
from backend.services.tmdb import backfill_posters_background
from backend.services.trakt import TraktClient
from backend.services.simkl import SimklClient

logger = logging.getLogger(__name__)

# Trakt's documented token lifetime is 90 days (7776000 s).
# Used as a fallback when expires_in is absent from the API response.
_TRAKT_TOKEN_DEFAULT_TTL_SECONDS = 7776000

# SIMKL tokens are long-lived (no documented expiry; default to 1 year).
_SIMKL_TOKEN_DEFAULT_TTL_SECONDS = 31536000

router = APIRouter(tags=["auth"])

COOKIE_NAME = "filmduel_session"
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 72  # 3-day absolute lifetime per issued token
REFRESH_INTERVAL = timedelta(hours=12)  # re-issue cookie at most once per 12h
SESSION_MAX_LIFETIME = timedelta(days=30)  # absolute hard cap on total session lifetime


def create_jwt(
    user_id: str,
    settings: Settings,
    orig_iat: datetime | None = None,
) -> str:
    """Create a signed JWT for session management.

    orig_iat: the original login timestamp (datetime), carried forward across
    refreshes. Stored as a Unix timestamp float in the JWT payload.
    Defaults to now on initial login.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "jti": secrets.token_hex(16),
        "iss": "filmduel",
        "aud": "filmduel",
        "exp": now + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": now,
        "orig_iat": (orig_iat or now).timestamp(),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=JWT_ALGORITHM)


def set_session_cookie(
    response: Response,
    user_id: str,
    settings: Settings,
    orig_iat: datetime | None = None,
) -> None:
    """Issue a fresh session cookie for user_id.

    orig_iat: original login time forwarded on refresh; None for a new login.
    Cookie max_age is bounded by the shorter of the per-token JWT expiry
    (72 h) and the remaining session lifetime (30-day cap - elapsed).
    """
    now = datetime.now(timezone.utc)
    session_start = orig_iat or now
    remaining = SESSION_MAX_LIFETIME - (now - session_start)
    if remaining <= timedelta(0):
        return  # session cap already reached; do not issue new credentials
    max_age = min(JWT_EXPIRY_HOURS * 3600, int(remaining.total_seconds()))
    response.set_cookie(
        COOKIE_NAME,
        create_jwt(user_id, settings, orig_iat=session_start),
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=max_age,
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

    def _reject(detail: str) -> NoReturn:
        response.delete_cookie(COOKIE_NAME)
        raise HTTPException(status_code=401, detail=detail)

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
        raw_orig = payload.get("orig_iat")
        if raw_orig is not None:
            if not isinstance(raw_orig, (int, float)):
                _reject("Invalid session")
            orig_iat = datetime.fromtimestamp(float(raw_orig), tz=timezone.utc)
        else:
            orig_iat = iat  # legacy tokens: treat iat as orig_iat
        if not user_id:
            _reject("Invalid session — missing subject")
    except jwt.ExpiredSignatureError:
        _reject("Session expired")
    except jwt.InvalidTokenError:
        _reject("Invalid session")

    # Server-side revocation: catches logout from another device or admin revoke.
    invalid_before = await db.scalar(
        select(User.tokens_invalid_before).where(User.id == uuid.UUID(user_id))
    )
    if invalid_before is None:
        _reject("User not found")
    if invalid_before.tzinfo is None:
        invalid_before = invalid_before.replace(tzinfo=timezone.utc)
    if iat < invalid_before:
        _reject("Session revoked")

    now = datetime.now(timezone.utc)

    # Hard cap: absolute 30-day session lifetime regardless of activity.
    if now - orig_iat > SESSION_MAX_LIFETIME:
        _reject("Session expired")

    # Sliding refresh: only re-issue if the token is older than REFRESH_INTERVAL.
    if now - iat > REFRESH_INTERVAL:
        set_session_cookie(response, user_id, settings, orig_iat=orig_iat)
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


async def get_admin_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Require the current user to have admin privileges."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


def require_consent(user: User = Depends(get_current_user)) -> User:
    """FastAPI dependency: reject if user hasn't accepted privacy policy."""
    if not user.privacy_policy_accepted:
        raise HTTPException(
            status_code=403,
            detail="Privacy policy consent required",
        )
    return user


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
        ttl = _TRAKT_TOKEN_DEFAULT_TTL_SECONDS
    user.trakt_token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
    user.last_seen_at = datetime.now(timezone.utc)
    await db.flush()

    return user


async def ensure_fresh_simkl_token(user: User, db: AsyncSession) -> User:
    """Check SIMKL token expiry. SIMKL may not support refresh — log warning."""
    if not user.simkl_token_expires_at or not user.simkl_access_token_enc:
        return user
    now = datetime.now(timezone.utc)
    expires_at = user.simkl_token_expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at - now > timedelta(hours=1):
        return user
    logger.warning("SIMKL token near expiry for user %s", user.id)
    return user


OAUTH_STATE_COOKIE = "filmduel_oauth_state"
OAUTH_SIMKL_STATE_COOKIE = "filmduel_oauth_simkl_state"
OAUTH_PKCE_COOKIE = "filmduel_oauth_pkce"
OAUTH_SIMKL_PKCE_COOKIE = "filmduel_oauth_simkl_pkce"


def _generate_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) per RFC 7636 S256 method.

    code_verifier: 43 URL-safe characters (RFC 7636 §4.1 allows 43-128)
    code_challenge: BASE64URL(SHA256(ASCII(code_verifier)))
    """
    code_verifier = secrets.token_urlsafe(32)  # 43 URL-safe characters
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return code_verifier, code_challenge


def _set_oauth_cookies(
    response: Response,
    state_cookie: str,
    state: str,
    pkce_cookie: str,
    code_verifier: str,
    secure: bool,
) -> None:
    """Set the OAuth state and PKCE verifier cookies on a redirect response."""
    cookie_kwargs = {"httponly": True, "secure": secure, "samesite": "lax", "max_age": 300}
    response.set_cookie(state_cookie, state, **cookie_kwargs)
    response.set_cookie(pkce_cookie, code_verifier, **cookie_kwargs)


@router.get("/auth/login")
@limiter.limit("10/minute")
async def login(request: Request, settings: Settings = Depends(get_settings)):
    """Redirect the user to Trakt's OAuth authorization page."""
    state = secrets.token_urlsafe(32)
    code_verifier, code_challenge = _generate_pkce_pair()
    params = urlencode(
        {
            "response_type": "code",
            "client_id": settings.TRAKT_CLIENT_ID,
            "redirect_uri": settings.TRAKT_REDIRECT_URI,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    response = RedirectResponse(f"https://trakt.tv/oauth/authorize?{params}")
    _set_oauth_cookies(
        response,
        OAUTH_STATE_COOKIE,
        state,
        OAUTH_PKCE_COOKIE,
        code_verifier,
        settings.cookie_secure,
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
    if not expected_state or not state or not hmac.compare_digest(state, expected_state):
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    code_verifier = request.cookies.get(OAUTH_PKCE_COOKIE)
    if not code_verifier:
        raise HTTPException(status_code=400, detail="Missing PKCE verifier")
    client = TraktClient(client_id=settings.TRAKT_CLIENT_ID)
    try:
        tokens = await client.exchange_code(
            code,
            client_secret=settings.TRAKT_CLIENT_SECRET,
            redirect_uri=settings.TRAKT_REDIRECT_URI,
            code_verifier=code_verifier,
        )
    except httpx.HTTPStatusError as exc:
        logger.error(
            "Trakt token exchange failed (status=%s); possible PKCE rejection",
            exc.response.status_code,
        )
        raise HTTPException(
            status_code=502,
            detail="Token exchange with Trakt failed",
        ) from exc

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
    background_tasks.add_task(sync_pool_background, user_id, force=True)

    # Backfill missing poster URLs in the background
    background_tasks.add_task(backfill_posters_background)

    response = RedirectResponse(url=settings.BASE_URL)
    set_session_cookie(response, str(user.id), settings)
    response.delete_cookie(OAUTH_STATE_COOKIE)
    response.delete_cookie(OAUTH_PKCE_COOKIE)
    return response


@router.get("/auth/simkl/login")
@limiter.limit("10/minute")
async def simkl_login(request: Request, settings: Settings = Depends(get_settings)):
    """Redirect the user to SIMKL's OAuth authorization page."""
    state = secrets.token_urlsafe(32)
    code_verifier, code_challenge = _generate_pkce_pair()
    params = urlencode(
        {
            "response_type": "code",
            "client_id": settings.SIMKL_CLIENT_ID,
            "redirect_uri": settings.SIMKL_REDIRECT_URI,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    response = RedirectResponse(f"https://simkl.com/oauth/authorize?{params}")
    _set_oauth_cookies(
        response,
        OAUTH_SIMKL_STATE_COOKIE,
        state,
        OAUTH_SIMKL_PKCE_COOKIE,
        code_verifier,
        settings.cookie_secure,
    )
    return response


@router.get("/auth/simkl/callback")
@limiter.limit("10/minute")
async def simkl_callback(
    code: str,
    request: Request,
    background_tasks: BackgroundTasks,
    state: str | None = None,
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
):
    """Handle the OAuth callback from SIMKL."""
    expected_state = request.cookies.get(OAUTH_SIMKL_STATE_COOKIE)
    if not expected_state or not state or not hmac.compare_digest(state, expected_state):
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    code_verifier = request.cookies.get(OAUTH_SIMKL_PKCE_COOKIE)
    if not code_verifier:
        raise HTTPException(status_code=400, detail="Missing PKCE verifier")
    client = SimklClient(client_id=settings.SIMKL_CLIENT_ID)
    try:
        tokens = await client.exchange_code(
            code,
            client_secret=settings.SIMKL_CLIENT_SECRET,
            redirect_uri=settings.SIMKL_REDIRECT_URI,
            code_verifier=code_verifier,
        )
    except httpx.HTTPStatusError as exc:
        logger.error(
            "SIMKL token exchange failed (status=%s); possible PKCE rejection",
            exc.response.status_code,
        )
        raise HTTPException(
            status_code=502,
            detail="Token exchange with SIMKL failed",
        ) from exc

    access_token = tokens["access_token"]
    refresh_token = tokens.get("refresh_token", "")

    authed_client = SimklClient(
        client_id=settings.SIMKL_CLIENT_ID,
        access_token=access_token,
    )
    profile = await authed_client.get_profile()

    try:
        simkl_user_id = str(profile["user"]["ids"]["simkl"])
        simkl_username = profile["user"].get("name", simkl_user_id)
    except (KeyError, TypeError) as exc:
        logger.error(
            "Unexpected SIMKL profile response (type=%s, keys=%s)",
            type(profile).__name__,
            list(profile.keys()) if isinstance(profile, dict) else "N/A",
        )
        raise HTTPException(
            status_code=502,
            detail="Unexpected response from SIMKL profile API",
        ) from exc
    ttl = tokens.get("expires_in", _SIMKL_TOKEN_DEFAULT_TTL_SECONDS)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)

    stmt = select(User).where(User.simkl_user_id == simkl_user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user:
        user.simkl_username = simkl_username
        user.simkl_access_token = access_token
        user.simkl_refresh_token = refresh_token
        user.simkl_token_expires_at = expires_at
    else:
        user = User(
            simkl_user_id=simkl_user_id,
            simkl_username=simkl_username,
            simkl_access_token=access_token,
            simkl_refresh_token=refresh_token,
            simkl_token_expires_at=expires_at,
        )
        db.add(user)

    await db.flush()

    user_id = user.id
    background_tasks.add_task(sync_pool_background, user_id, force=True)
    background_tasks.add_task(backfill_posters_background)

    response = RedirectResponse(url=settings.BASE_URL)
    set_session_cookie(response, str(user.id), settings)
    response.delete_cookie(OAUTH_SIMKL_STATE_COOKIE)
    response.delete_cookie(OAUTH_SIMKL_PKCE_COOKIE)
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

