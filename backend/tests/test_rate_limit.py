"""Unit tests for rate_limit._rate_limit_key."""

from __future__ import annotations

import os
import time
from unittest.mock import MagicMock, patch

os.environ.setdefault("TOKEN_ENC_KEY", "test-secret-key-for-unit-tests-32b")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests!!")

import jwt

from backend.rate_limit import _rate_limit_key


def _make_request(cookie_value=None, client_ip="1.2.3.4"):
    request = MagicMock()
    request.cookies = {"filmduel_session": cookie_value} if cookie_value else {}
    request.client.host = client_ip
    return request


def _make_valid_token(sub: str, secret: str = "test-secret") -> str:
    return jwt.encode({"sub": sub, "exp": time.time() + 3600}, secret, algorithm="HS256")


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
