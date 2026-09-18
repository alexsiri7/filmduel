"""Unit tests for rate_limit._rate_limit_key and _build_limiter."""

from __future__ import annotations

import os
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("TOKEN_ENC_KEY", "test-secret-key-for-unit-tests-32b")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests!!")

import jwt
from fastapi import FastAPI
from fastapi.testclient import TestClient
from limits.storage import MemoryStorage, RedisStorage
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.requests import Request

from backend.rate_limit import _build_limiter, _rate_limit_key


def _make_request(cookie_value=None, client_ip="1.2.3.4"):
    request = MagicMock()
    request.cookies = {"filmduel_session": cookie_value} if cookie_value else {}
    request.client.host = client_ip
    return request


def _make_valid_token(sub: str, secret: str = "test-secret") -> str:
    return jwt.encode(
        {"sub": sub, "exp": time.time() + 3600}, secret, algorithm="HS256"
    )


def test_rate_limit_key_authenticated_user_returns_user_key():
    """Valid JWT cookie should return user:{sub} key."""
    token = _make_valid_token("user-123")
    request = _make_request(cookie_value=token)
    with patch("backend.rate_limit.get_settings") as mock_settings:
        mock_settings.return_value.SECRET_KEY = "test-secret"
        key = _rate_limit_key(request)
    assert key == "user:user-123"


def test_rate_limit_key_invalid_jwt_falls_back_to_ip():
    """Malformed JWT cookie should fall back to IP-based key."""
    request = _make_request(cookie_value="not-a-jwt", client_ip="10.0.0.1")
    with patch("backend.rate_limit.get_settings") as mock_settings:
        mock_settings.return_value.SECRET_KEY = "test-secret"
        key = _rate_limit_key(request)
    assert key == "ip:10.0.0.1"


def test_rate_limit_key_no_cookie_falls_back_to_ip():
    """Missing session cookie should use IP-based key."""
    request = _make_request(cookie_value=None, client_ip="192.168.1.1")
    key = _rate_limit_key(request)
    assert key == "ip:192.168.1.1"


def test_rate_limit_key_jwt_missing_sub_falls_back_to_ip():
    """JWT without 'sub' claim should fall back to IP."""
    token = jwt.encode({"data": "no-sub"}, "test-secret", algorithm="HS256")
    request = _make_request(cookie_value=token, client_ip="5.5.5.5")
    with patch("backend.rate_limit.get_settings") as mock_settings:
        mock_settings.return_value.SECRET_KEY = "test-secret"
        key = _rate_limit_key(request)
    assert key == "ip:5.5.5.5"


def test_rate_limit_key_expired_jwt_falls_back_to_ip():
    """Expired JWT should fall back to IP-based key."""
    token = jwt.encode(
        {"sub": "user-abc", "exp": time.time() - 3600},
        "test-secret",
        algorithm="HS256",
    )
    request = _make_request(cookie_value=token, client_ip="7.7.7.7")
    with patch("backend.rate_limit.get_settings") as mock_settings:
        mock_settings.return_value.SECRET_KEY = "test-secret"
        key = _rate_limit_key(request)
    assert key == "ip:7.7.7.7"


# Port 1 has nothing listening, so connection refused is immediate and no Redis
# container is needed; RedisStorage construction itself does no network I/O.
_DEAD_REDIS_URI = "redis://127.0.0.1:1/0"


def test_build_limiter_defaults_to_memory_storage():
    lim = _build_limiter(SimpleNamespace(RATE_LIMIT_STORAGE_URI=""))
    assert isinstance(lim._storage, MemoryStorage)
    assert lim._in_memory_fallback_enabled is False


def test_build_limiter_uses_redis_storage_with_fallback_and_timeouts():
    lim = _build_limiter(SimpleNamespace(RATE_LIMIT_STORAGE_URI=_DEAD_REDIS_URI))
    assert isinstance(lim._storage, RedisStorage)
    assert lim._in_memory_fallback_enabled is True
    assert lim._storage_options == {"socket_connect_timeout": 1, "socket_timeout": 1}


def test_build_limiter_falls_back_to_memory_when_redis_unreachable():
    """An unreachable Redis must degrade to per-process limiting, not 500s."""
    lim = _build_limiter(SimpleNamespace(RATE_LIMIT_STORAGE_URI=_DEAD_REDIS_URI))
    app = FastAPI()
    app.state.limiter = lim
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.get("/limited")
    @lim.limit("2/minute")
    async def limited(request: Request):
        return {"ok": True}

    client = TestClient(app, raise_server_exceptions=False)
    statuses = [client.get("/limited").status_code for _ in range(3)]

    assert statuses == [200, 200, 429]
    assert lim._storage_dead is True
