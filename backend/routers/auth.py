"""Trakt OAuth2 authentication routes."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import NamedTuple, NoReturn
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
from backend.services.token_refresh import (  # noqa: F401
    TRAKT_TOKEN_DEFAULT_TTL_SECONDS,
    ensure_fresh_token,  # re-exported for routers/users.py and routers/suggestions.py
)
from backend.services.simkl import SimklClient
from backend.utils.cookies import (
    COOKIE_NAME,
    OAUTH_PKCE_COOKIE,
    OAUTH_SIMKL_PKCE_COOKIE,
    OAUTH_SIMKL_STATE_COOKIE,
    OAUTH_STATE_COOKIE,
    cookie_name,
)

logger = logging.getLogger(__name__)

# SIMKL tokens are long-lived (no documented expiry; default to 1 year).
_SIMKL_TOKEN_DEFAULT_TTL_SECONDS = 31536000

router = APIRouter(tags=["auth"])

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
    The name is ``__Host-``-prefixed whenever the cookie is Secure (see
    ``cookie_name``).
    """
    now = datetime.now(timezone.utc)
    session_start = orig_iat or now
    remaining = SESSION_MAX_LIFETIME - (now - session_start)
    if remaining <= timedelta(0):
        return  # session cap already reached; do not issue new credentials
    max_age = min(JWT_EXPIRY_HOURS * 3600, int(remaining.total_seconds()))
    secure = settings.cookie_secure
    response.set_cookie(
        cookie_name(COOKIE_NAME, secure),
        create_jwt(user_id, settings, orig_iat=session_start),
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=max_age,
    )


def _delete_cookie(response: Response, base: str, secure: bool) -> None:
    """Expire the cookie issued as ``cookie_name(base, secure)``.

    Browsers drop any Set-Cookie for a ``__Host-`` name that lacks Secure,
    including the expiry one, so the flag must travel with the name.
    """
    response.delete_cookie(cookie_name(base, secure), secure=secure)


def delete_session_cookie(response: Response, settings: Settings) -> None:
    """Expire the session cookie; the counterpart of set_session_cookie."""
    _delete_cookie(response, COOKIE_NAME, settings.cookie_secure)


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
    token = request.cookies.get(cookie_name(COOKIE_NAME, settings.cookie_secure))
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    def _reject(detail: str) -> NoReturn:
        # Headers staged on the injected `response` are discarded when an
        # HTTPException is raised, so the cookie deletion must travel on the
        # exception itself to reach the client.
        cleared = Response()
        delete_session_cookie(cleared, settings)
        raise HTTPException(
            status_code=401,
            detail=detail,
            headers={"set-cookie": cleared.headers["set-cookie"]},
        )

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


def require_ai_consent(user: User = Depends(get_current_user)) -> User:
    """FastAPI dependency: reject if user hasn't accepted privacy policy or disabled AI features."""
    require_consent(user)
    if not user.use_ai_features:
        raise HTTPException(
            status_code=403,
            detail="AI features are disabled. Enable them in settings to use this feature.",
        )
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
    response.set_cookie(cookie_name(state_cookie, secure), state, **cookie_kwargs)
    response.set_cookie(cookie_name(pkce_cookie, secure), code_verifier, **cookie_kwargs)


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


class _OAuthProvider(NamedTuple):
    """Provider-specific config for the shared OAuth callback helper."""
    name: str
    state_cookie: str
    pkce_cookie: str
    default_ttl: int
    make_client: Callable[..., TraktClient | SimklClient]
    exchange_kwargs: Callable[[Settings], dict]
    extract_user_info: Callable[[dict, dict], tuple[str, str]]
    user_id_column: str  # User model attribute to look up by (e.g. "trakt_user_id")
    user_fields: Callable[[str, str, str, str, datetime], dict]


def _trakt_extract(tokens: dict, profile: dict) -> tuple[str, str]:
    return str(profile["ids"]["slug"]), profile["username"]


def _simkl_extract(tokens: dict, profile: dict) -> tuple[str, str]:
    try:
        user_id = str(profile["user"]["ids"]["simkl"])
        username = profile["user"].get("name", user_id)
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
    return user_id, username


def _make_trakt_client(settings: Settings, **kw) -> TraktClient:
    return TraktClient(client_id=settings.TRAKT_CLIENT_ID, **kw)


def _make_simkl_client(settings: Settings, **kw) -> SimklClient:
    return SimklClient(client_id=settings.SIMKL_CLIENT_ID, **kw)


_TRAKT_PROVIDER = _OAuthProvider(
    name="Trakt",
    state_cookie=OAUTH_STATE_COOKIE,
    pkce_cookie=OAUTH_PKCE_COOKIE,
    default_ttl=TRAKT_TOKEN_DEFAULT_TTL_SECONDS,
    make_client=_make_trakt_client,
    exchange_kwargs=lambda s: {
        "client_secret": s.TRAKT_CLIENT_SECRET,
        "redirect_uri": s.TRAKT_REDIRECT_URI,
    },
    extract_user_info=_trakt_extract,
    user_id_column="trakt_user_id",
    user_fields=lambda uid, uname, access, refresh, exp: {
        "trakt_user_id": uid,
        "trakt_username": uname,
        "trakt_access_token": access,
        "trakt_refresh_token": refresh,
        "trakt_token_expires_at": exp,
    },
)

_SIMKL_PROVIDER = _OAuthProvider(
    name="SIMKL",
    state_cookie=OAUTH_SIMKL_STATE_COOKIE,
    pkce_cookie=OAUTH_SIMKL_PKCE_COOKIE,
    default_ttl=_SIMKL_TOKEN_DEFAULT_TTL_SECONDS,
    make_client=_make_simkl_client,
    exchange_kwargs=lambda s: {
        "client_secret": s.SIMKL_CLIENT_SECRET,
        "redirect_uri": s.SIMKL_REDIRECT_URI,
    },
    extract_user_info=_simkl_extract,
    user_id_column="simkl_user_id",
    user_fields=lambda uid, uname, access, refresh, exp: {
        "simkl_user_id": uid,
        "simkl_username": uname,
        "simkl_access_token": access,
        "simkl_refresh_token": refresh,
        "simkl_token_expires_at": exp,
    },
)


async def _handle_oauth_callback(
    provider: _OAuthProvider,
    code: str,
    request: Request,
    background_tasks: BackgroundTasks,
    state: str | None,
    settings: Settings,
    db: AsyncSession,
) -> Response:
    """Shared OAuth callback logic for Trakt and SIMKL."""
    secure = settings.cookie_secure

    # Validate state
    expected_state = request.cookies.get(cookie_name(provider.state_cookie, secure))
    if not expected_state or not state or not hmac.compare_digest(state, expected_state):
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    code_verifier = request.cookies.get(cookie_name(provider.pkce_cookie, secure))
    if not code_verifier:
        raise HTTPException(status_code=400, detail="Missing PKCE verifier")

    # Exchange code for tokens
    client = provider.make_client(settings)
    try:
        tokens = await client.exchange_code(
            code, code_verifier=code_verifier, **provider.exchange_kwargs(settings)
        )
    except httpx.HTTPStatusError as exc:
        logger.error(
            "%s token exchange failed (status=%s); possible PKCE rejection",
            provider.name,
            exc.response.status_code,
        )
        raise HTTPException(
            status_code=502,
            detail=f"Token exchange with {provider.name} failed",
        ) from exc

    # Fetch profile
    access_token = tokens["access_token"]
    refresh_token = tokens.get("refresh_token", "")
    authed_client = provider.make_client(settings, access_token=access_token)
    profile = await authed_client.get_profile()

    # Extract provider-specific user info
    provider_user_id, username = provider.extract_user_info(tokens, profile)

    ttl = tokens.get("expires_in")
    if ttl is None:
        logger.warning(
            "%s exchange_code response missing expires_in; using default TTL",
            provider.name,
        )
        ttl = provider.default_ttl
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)

    # Upsert user
    column = getattr(User, provider.user_id_column)
    stmt = select(User).where(column == provider_user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    fields = provider.user_fields(
        provider_user_id, username, access_token, refresh_token, expires_at
    )
    if user:
        for k, v in fields.items():
            if k != provider.user_id_column:
                setattr(user, k, v)
    else:
        user = User(**fields)
        db.add(user)

    await db.flush()

    # Initial import is deferred to consent acceptance (#571); only re-sync users
    # who have already accepted the privacy policy.
    if user.privacy_policy_accepted:
        background_tasks.add_task(sync_pool_background, user.id, force=True)
    background_tasks.add_task(backfill_posters_background)

    response = RedirectResponse(url=settings.BASE_URL)
    set_session_cookie(response, str(user.id), settings)
    _delete_cookie(response, provider.state_cookie, secure)
    _delete_cookie(response, provider.pkce_cookie, secure)
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
    return await _handle_oauth_callback(
        _TRAKT_PROVIDER, code, request, background_tasks, state, settings, db
    )


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
    return await _handle_oauth_callback(
        _SIMKL_PROVIDER, code, request, background_tasks, state, settings, db
    )


@router.post("/auth/logout")
@limiter.limit("10/minute")
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
    settings: Settings = Depends(get_settings),
):
    """Clear the session cookie and revoke all previously issued JWTs."""
    await db.execute(
        update(User)
        .where(User.id == uuid.UUID(user_id))
        .values(tokens_invalid_before=datetime.now(timezone.utc))
    )
    await db.commit()
    response = Response(status_code=204)
    delete_session_cookie(response, settings)
    return response

