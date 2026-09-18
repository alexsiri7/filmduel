"""Rate limiting configuration using slowapi."""

from __future__ import annotations

import jwt
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from backend.config import Settings, get_settings
from backend.utils.cookies import COOKIE_NAME, cookie_name


def _rate_limit_key(request: Request) -> str:
    """Per-user key when authenticated, falling back to client IP.

    The cookie carries an HS256 JWT; we decode it without re-validating
    issuer/audience (those are checked by get_current_user_id on the
    downstream dependency). If decode fails we fall back to IP — the
    underlying request will be rejected with 401 by the route handler anyway.
    Keying on user ID prevents a single user from cycling IPs to bypass limits.
    The cookie is looked up under the same ``__Host-`` rule the issuer applies.
    """
    settings = get_settings()
    token = request.cookies.get(cookie_name(COOKIE_NAME, settings.cookie_secure))
    if token:
        try:
            payload = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=["HS256"],
                options={"verify_aud": False, "verify_iss": False},
            )
            sub = payload.get("sub")
            if sub:
                return f"user:{sub}"
        except jwt.PyJWTError:
            pass
    return f"ip:{get_remote_address(request)}"


# Bounded socket timeouts are load-bearing: without them an unreachable Redis
# host stalls the first request for minutes (OS TCP timeout × client retries)
# before slowapi falls back to in-memory counters.
_REDIS_STORAGE_OPTIONS = {"socket_connect_timeout": 1, "socket_timeout": 1}


def _build_limiter(settings: Settings) -> Limiter:
    """Build the app limiter; Redis-backed when RATE_LIMIT_STORAGE_URI is set.

    in_memory_fallback_enabled keeps rate-limited routes (including /health)
    serving during a Redis outage by degrading to per-process counters; slowapi
    re-checks the backend with exponential backoff and recovers automatically.
    """
    if not settings.RATE_LIMIT_STORAGE_URI:
        return Limiter(key_func=_rate_limit_key)
    return Limiter(
        key_func=_rate_limit_key,
        storage_uri=settings.RATE_LIMIT_STORAGE_URI,
        storage_options=dict(_REDIS_STORAGE_OPTIONS),
        in_memory_fallback_enabled=True,
    )


limiter = _build_limiter(get_settings())
