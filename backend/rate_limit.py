"""Rate limiting configuration using slowapi."""

from __future__ import annotations

import ipaddress
import logging
import os
import uuid

import jwt
from fastapi import HTTPException
from limits import parse
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from backend.config import Settings, get_settings
from backend.utils.cookies import COOKIE_NAME, cookie_name

logger = logging.getLogger(__name__)


def _client_ip(request: Request) -> str:
    """Client address for anonymous rate-limit buckets.

    On Railway, uvicorn runs with ``--forwarded-allow-ips='*'``, which makes
    ``request.client`` the leftmost, client-controlled X-Forwarded-For entry.
    Railway's edge overwrites X-Real-IP with the connecting address, so that
    header is used there instead. Off Railway, X-Real-IP is client-controlled
    and ignored.
    """
    if os.environ.get("RAILWAY_ENVIRONMENT"):
        real_ip = request.headers.get("x-real-ip", "").strip()
        try:
            return str(ipaddress.ip_address(real_ip))
        except ValueError:
            logger.warning(
                "Missing or invalid X-Real-IP on Railway; rate limiting falls back "
                "to the spoofable request.client address"
            )
    return get_remote_address(request)


def _rate_limit_key(request: Request) -> str:
    """Per-user key when authenticated, falling back to ``_client_ip``.

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
    return f"ip:{_client_ip(request)}"


# Bounded socket timeouts are load-bearing: without them an unreachable Redis
# host stalls the first request for minutes (OS TCP timeout × client retries)
# before slowapi falls back to in-memory counters.
_REDIS_STORAGE_OPTIONS = {"socket_connect_timeout": 1, "socket_timeout": 1}


class _FallbackLoggingLimiter(Limiter):
    """Limiter that reports the switch to in-memory counters on our own logger.

    slowapi logs that switch on its "slowapi" logger, but also attaches a no-op
    handler to it, so the warning never reaches the process output.
    """

    def _check_request_limit(self, *args, **kwargs) -> None:
        storage_was_dead = self._storage_dead
        try:
            super()._check_request_limit(*args, **kwargs)
        finally:
            if self._storage_dead and not storage_was_dead:
                logger.warning(
                    "rate_limit_storage_fallback: rate limit storage unreachable; "
                    "falling back to per-process in-memory counters"
                )


def _build_limiter(settings: Settings) -> Limiter:
    """Build the app limiter; Redis-backed when RATE_LIMIT_STORAGE_URI is set.

    in_memory_fallback_enabled keeps rate-limited routes (including /health)
    serving during a Redis outage by degrading to per-process counters; slowapi
    re-checks the backend with exponential backoff and recovers automatically.
    """
    if not settings.RATE_LIMIT_STORAGE_URI:
        return Limiter(key_func=_rate_limit_key)
    return _FallbackLoggingLimiter(
        key_func=_rate_limit_key,
        storage_uri=settings.RATE_LIMIT_STORAGE_URI,
        storage_options=dict(_REDIS_STORAGE_OPTIONS),
        in_memory_fallback_enabled=True,
    )


limiter = _build_limiter(get_settings())


# One budget for every LLM curation call (tournament create + regenerate),
# spent per attempt so failed curations count too (SEC-10, #782).
AI_CURATION_DAILY_LIMIT = parse("50/day")


def count_ai_curation_attempt(request: Request) -> None:
    """Spend one unit of the caller's daily AI curation budget; 429 when spent.

    Fails open when the limiter storage is unreachable, matching the route
    limits' in-memory fallback: the 10/minute route limit still applies.
    """
    try:
        allowed = limiter.limiter.hit(
            AI_CURATION_DAILY_LIMIT, _rate_limit_key(request), "ai_curation"
        )
    except Exception:
        logger.warning("AI curation cap storage unavailable; attempt not counted")
        return
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Daily AI curation limit reached. Please try again later.",
        )


# An LLM reply with no usable pick writes no Suggestion row, so GET would
# otherwise ask the LLM again on every request (SEC-11, #783).
EMPTY_SUGGESTIONS_COOLDOWN = parse("1/hour")


def record_empty_suggestions(user_id: uuid.UUID, media_type: str) -> None:
    """Remember that the LLM just produced no usable suggestion for this user."""
    try:
        limiter.limiter.hit(
            EMPTY_SUGGESTIONS_COOLDOWN, f"user:{user_id}", "suggestions_empty", media_type
        )
    except Exception:
        logger.warning("Suggestions cooldown storage unavailable; empty attempt not recorded")


def empty_suggestions_recent(user_id: uuid.UUID, media_type: str) -> bool:
    """True when an empty LLM attempt was recorded within the cooldown. Fails open."""
    try:
        return not limiter.limiter.test(
            EMPTY_SUGGESTIONS_COOLDOWN, f"user:{user_id}", "suggestions_empty", media_type
        )
    except Exception:
        logger.warning("Suggestions cooldown storage unavailable; not enforced")
        return False
