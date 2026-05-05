"""Rate limiting configuration using slowapi."""

from __future__ import annotations

import jwt
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from backend.config import get_settings


def _rate_limit_key(request: Request) -> str:
    """Per-user key when authenticated, falling back to client IP.

    The cookie carries an HS256 JWT; we decode it without re-validating
    issuer/audience (those are checked by get_current_user_id on the
    downstream dependency). If decode fails we fall back to IP — the
    underlying request will be rejected with 401 by the route handler anyway.
    Keying on user ID prevents a single user from cycling IPs to bypass limits.
    """
    token = request.cookies.get("filmduel_session")
    if token:
        try:
            settings = get_settings()
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


limiter = Limiter(key_func=_rate_limit_key)
