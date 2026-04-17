"""Tests for auth logic — JWT creation, verification, and user extraction."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import jwt as pyjwt
import pytest
from fastapi import HTTPException

from backend.config import Settings
from backend.routers.auth import (
    COOKIE_NAME,
    JWT_ALGORITHM,
    JWT_EXPIRY_HOURS,
    create_jwt,
    get_current_user_id,
)


def _make_settings(**overrides) -> Settings:
    defaults = {
        "SECRET_KEY": "test-secret-key-for-unit-tests",
        "TRAKT_CLIENT_ID": "",
        "TRAKT_CLIENT_SECRET": "",
        "DATABASE_URL": "postgresql+asyncpg://localhost/test",
    }
    defaults.update(overrides)
    return Settings(**defaults)


SETTINGS = _make_settings()


# ---------------------------------------------------------------------------
# create_jwt
# ---------------------------------------------------------------------------


class TestCreateJWT:
    def test_returns_string(self):
        token = create_jwt("user-123", SETTINGS)
        assert isinstance(token, str)

    def test_round_trip_decode(self):
        user_id = "550e8400-e29b-41d4-a716-446655440000"
        token = create_jwt(user_id, SETTINGS)
        payload = pyjwt.decode(
            token, SETTINGS.SECRET_KEY, algorithms=[JWT_ALGORITHM],
            issuer="filmduel", audience="filmduel",
        )
        assert payload["sub"] == user_id
        assert payload["iss"] == "filmduel"
        assert payload["aud"] == "filmduel"
        assert "jti" in payload

    def test_payload_has_exp_and_iat(self):
        token = create_jwt("user-1", SETTINGS)
        payload = pyjwt.decode(
            token, SETTINGS.SECRET_KEY, algorithms=[JWT_ALGORITHM],
            issuer="filmduel", audience="filmduel",
        )
        assert "exp" in payload
        assert "iat" in payload

    def test_expiry_is_in_future(self):
        token = create_jwt("user-1", SETTINGS)
        payload = pyjwt.decode(
            token, SETTINGS.SECRET_KEY, algorithms=[JWT_ALGORITHM],
            issuer="filmduel", audience="filmduel",
        )
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        now = datetime.now(timezone.utc)
        # Should expire roughly JWT_EXPIRY_HOURS from now (allow 5 min tolerance)
        expected_min = now + timedelta(hours=JWT_EXPIRY_HOURS) - timedelta(minutes=5)
        assert exp > expected_min

    def test_different_users_different_tokens(self):
        t1 = create_jwt("user-1", SETTINGS)
        t2 = create_jwt("user-2", SETTINGS)
        assert t1 != t2


# ---------------------------------------------------------------------------
# get_current_user_id
# ---------------------------------------------------------------------------


def _make_request(cookies: dict | None = None) -> MagicMock:
    """Create a mock FastAPI Request with optional cookies."""
    request = MagicMock()
    request.cookies = cookies or {}
    return request


def _make_response() -> MagicMock:
    """Create a mock FastAPI Response; set_cookie is a no-op MagicMock."""
    return MagicMock()


class TestGetCurrentUserId:
    def test_extracts_user_id(self, monkeypatch):
        """Valid token should return the user ID."""
        monkeypatch.setattr("backend.routers.auth.get_settings", lambda: SETTINGS)
        user_id = "my-user-id-abc"
        token = create_jwt(user_id, SETTINGS)
        request = _make_request({COOKIE_NAME: token})
        response = _make_response()
        result = get_current_user_id(request, response)
        assert result == user_id

    def test_refreshes_cookie_on_success(self, monkeypatch):
        """On successful auth, a fresh session cookie should be set (sliding session)."""
        monkeypatch.setattr("backend.routers.auth.get_settings", lambda: SETTINGS)
        user_id = "my-user-id-abc"
        token = create_jwt(user_id, SETTINGS)
        request = _make_request({COOKIE_NAME: token})
        response = _make_response()
        get_current_user_id(request, response)
        response.set_cookie.assert_called_once()
        args = response.set_cookie.call_args.args
        kwargs = response.set_cookie.call_args.kwargs
        assert args[0] == COOKIE_NAME
        assert kwargs.get("httponly") is True
        assert kwargs.get("secure") is True
        assert kwargs.get("samesite") == "lax"
        assert kwargs.get("max_age") == JWT_EXPIRY_HOURS * 3600

    def test_no_cookie_raises_401(self, monkeypatch):
        """Missing cookie should raise 401."""
        monkeypatch.setattr("backend.routers.auth.get_settings", lambda: SETTINGS)
        request = _make_request({})
        response = _make_response()
        with pytest.raises(HTTPException) as exc_info:
            get_current_user_id(request, response)
        assert exc_info.value.status_code == 401
        assert "Not authenticated" in exc_info.value.detail
        response.set_cookie.assert_not_called()

    def test_expired_token_raises_401(self, monkeypatch):
        """Expired JWT should raise 401 with 'Session expired'."""
        monkeypatch.setattr("backend.routers.auth.get_settings", lambda: SETTINGS)
        # Create a token that expired an hour ago
        payload = {
            "sub": "user-1",
            "iss": "filmduel",
            "aud": "filmduel",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
            "iat": datetime.now(timezone.utc) - timedelta(hours=2),
        }
        token = pyjwt.encode(payload, SETTINGS.SECRET_KEY, algorithm=JWT_ALGORITHM)
        request = _make_request({COOKIE_NAME: token})
        response = _make_response()
        with pytest.raises(HTTPException) as exc_info:
            get_current_user_id(request, response)
        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail.lower()
        response.set_cookie.assert_not_called()

    def test_invalid_token_raises_401(self, monkeypatch):
        """Garbage token should raise 401."""
        monkeypatch.setattr("backend.routers.auth.get_settings", lambda: SETTINGS)
        request = _make_request({COOKIE_NAME: "not-a-valid-jwt"})
        response = _make_response()
        with pytest.raises(HTTPException) as exc_info:
            get_current_user_id(request, response)
        assert exc_info.value.status_code == 401
        assert "Invalid session" in exc_info.value.detail
        response.set_cookie.assert_not_called()

    def test_wrong_secret_raises_401(self, monkeypatch):
        """Token signed with wrong secret should raise 401."""
        monkeypatch.setattr("backend.routers.auth.get_settings", lambda: SETTINGS)
        wrong_settings = _make_settings(SECRET_KEY="wrong-secret")
        token = create_jwt("user-1", wrong_settings)
        request = _make_request({COOKIE_NAME: token})
        response = _make_response()
        with pytest.raises(HTTPException) as exc_info:
            get_current_user_id(request, response)
        assert exc_info.value.status_code == 401

    def test_token_missing_sub_raises_401(self, monkeypatch):
        """Token without 'sub' claim should raise 401."""
        monkeypatch.setattr("backend.routers.auth.get_settings", lambda: SETTINGS)
        payload = {
            "iss": "filmduel",
            "aud": "filmduel",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            "iat": datetime.now(timezone.utc),
            # no "sub"
        }
        token = pyjwt.encode(payload, SETTINGS.SECRET_KEY, algorithm=JWT_ALGORITHM)
        request = _make_request({COOKIE_NAME: token})
        response = _make_response()
        with pytest.raises(HTTPException) as exc_info:
            get_current_user_id(request, response)
        assert exc_info.value.status_code == 401
        assert "missing subject" in exc_info.value.detail.lower()
        response.set_cookie.assert_not_called()
