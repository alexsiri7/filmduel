"""Tests for auth logic — JWT creation, verification, and user extraction."""

from __future__ import annotations

import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests!!")

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import jwt as pyjwt
import pytest
from fastapi import HTTPException

from backend.config import Settings
from backend.rate_limit import limiter
from backend.schemas import UserSettingsUpdate
from starlette.requests import Request as StarletteRequest

from backend.routers.auth import (
    COOKIE_NAME,
    JWT_ALGORITHM,
    JWT_EXPIRY_HOURS,
    REFRESH_INTERVAL,
    _TRAKT_TOKEN_DEFAULT_TTL_SECONDS,
    create_jwt,
    ensure_fresh_token,
    get_current_user_id,
    update_settings,
)


def _make_settings(**overrides) -> Settings:
    defaults = {
        "SECRET_KEY": "test-secret-key-for-unit-tests!!",
        "TRAKT_CLIENT_ID": "",
        "TRAKT_CLIENT_SECRET": "",
        "DATABASE_URL": "postgresql+asyncpg://localhost/test",
    }
    defaults.update(overrides)
    return Settings(**defaults)


SETTINGS = _make_settings()

# Epoch sentinel — tokens_invalid_before value for a user with no revocations.
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _make_db(invalid_before: datetime = _EPOCH) -> AsyncMock:
    """Mock AsyncSession whose scalar() returns invalid_before."""
    db = AsyncMock()
    db.scalar.return_value = invalid_before
    return db


def _make_request(cookies: dict | None = None) -> MagicMock:
    """Create a mock FastAPI Request with optional cookies."""
    request = MagicMock()
    request.cookies = cookies or {}
    return request


def _make_response() -> MagicMock:
    """Create a mock FastAPI Response; set_cookie is a no-op MagicMock."""
    return MagicMock()


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
            token,
            SETTINGS.SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
            issuer="filmduel",
            audience="filmduel",
        )
        assert payload["sub"] == user_id
        assert payload["iss"] == "filmduel"
        assert payload["aud"] == "filmduel"
        assert "jti" in payload

    def test_payload_has_exp_and_iat(self):
        token = create_jwt("user-1", SETTINGS)
        payload = pyjwt.decode(
            token,
            SETTINGS.SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
            issuer="filmduel",
            audience="filmduel",
        )
        assert "exp" in payload
        assert "iat" in payload

    def test_expiry_is_in_future(self):
        token = create_jwt("user-1", SETTINGS)
        payload = pyjwt.decode(
            token,
            SETTINGS.SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
            issuer="filmduel",
            audience="filmduel",
        )
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        now = datetime.now(timezone.utc)
        expected_min = now + timedelta(hours=JWT_EXPIRY_HOURS) - timedelta(minutes=5)
        assert exp > expected_min

    def test_different_users_different_tokens(self):
        t1 = create_jwt("user-1", SETTINGS)
        t2 = create_jwt("user-2", SETTINGS)
        assert t1 != t2


# ---------------------------------------------------------------------------
# get_current_user_id  (async — requires pytest-asyncio)
# ---------------------------------------------------------------------------


class TestGetCurrentUserId:
    @pytest.mark.asyncio
    async def test_extracts_user_id(self, monkeypatch):
        """Valid token should return the user ID."""
        monkeypatch.setattr("backend.routers.auth.get_settings", lambda: SETTINGS)
        user_id = "550e8400-e29b-41d4-a716-446655440000"
        token = create_jwt(user_id, SETTINGS)
        request = _make_request({COOKIE_NAME: token})
        response = _make_response()
        result = await get_current_user_id(request, response, _make_db())
        assert result == user_id

    @pytest.mark.asyncio
    async def test_does_not_refresh_fresh_token(self, monkeypatch):
        """A token younger than REFRESH_INTERVAL must not trigger a Set-Cookie."""
        monkeypatch.setattr("backend.routers.auth.get_settings", lambda: SETTINGS)
        token = create_jwt("550e8400-e29b-41d4-a716-446655440000", SETTINGS)
        request = _make_request({COOKIE_NAME: token})
        response = _make_response()
        await get_current_user_id(request, response, _make_db())
        response.set_cookie.assert_not_called()

    @pytest.mark.asyncio
    async def test_refreshes_old_token(self, monkeypatch):
        """A token older than REFRESH_INTERVAL should trigger a new Set-Cookie."""
        monkeypatch.setattr("backend.routers.auth.get_settings", lambda: SETTINGS)
        old_iat = datetime.now(timezone.utc) - REFRESH_INTERVAL - timedelta(hours=1)
        payload = {
            "sub": "550e8400-e29b-41d4-a716-446655440000",
            "jti": "x",
            "iss": "filmduel",
            "aud": "filmduel",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            "iat": old_iat,
        }
        token = pyjwt.encode(payload, SETTINGS.SECRET_KEY, algorithm=JWT_ALGORITHM)
        request = _make_request({COOKIE_NAME: token})
        response = _make_response()
        await get_current_user_id(request, response, _make_db())
        response.set_cookie.assert_called_once()
        kwargs = response.set_cookie.call_args.kwargs
        assert kwargs.get("httponly") is True
        assert kwargs.get("secure") is SETTINGS.is_https
        assert kwargs.get("samesite") == "lax"

    @pytest.mark.asyncio
    async def test_refreshes_old_token_https_sets_secure_cookie(self, monkeypatch):
        """Cookie refresh sets secure=True when BASE_URL is HTTPS."""
        https_settings = _make_settings(BASE_URL="https://filmduel.example.com")
        monkeypatch.setattr("backend.routers.auth.get_settings", lambda: https_settings)
        old_iat = datetime.now(timezone.utc) - REFRESH_INTERVAL - timedelta(hours=1)
        payload = {
            "sub": "550e8400-e29b-41d4-a716-446655440000",
            "jti": "x",
            "iss": "filmduel",
            "aud": "filmduel",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            "iat": old_iat,
        }
        token = pyjwt.encode(
            payload, https_settings.SECRET_KEY, algorithm=JWT_ALGORITHM
        )
        request = _make_request({COOKIE_NAME: token})
        response = _make_response()
        await get_current_user_id(request, response, _make_db())
        kwargs = response.set_cookie.call_args.kwargs
        assert kwargs.get("secure") is True

    @pytest.mark.asyncio
    async def test_no_cookie_raises_401(self, monkeypatch):
        """Missing cookie should raise 401."""
        monkeypatch.setattr("backend.routers.auth.get_settings", lambda: SETTINGS)
        request = _make_request({})
        response = _make_response()
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_id(request, response, _make_db())
        assert exc_info.value.status_code == 401
        assert "Not authenticated" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_expired_token_raises_401(self, monkeypatch):
        """Expired JWT should raise 401 with 'Session expired'."""
        monkeypatch.setattr("backend.routers.auth.get_settings", lambda: SETTINGS)
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
            await get_current_user_id(request, response, _make_db())
        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_invalid_token_raises_401(self, monkeypatch):
        """Garbage token should raise 401."""
        monkeypatch.setattr("backend.routers.auth.get_settings", lambda: SETTINGS)
        request = _make_request({COOKIE_NAME: "not-a-valid-jwt"})
        response = _make_response()
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_id(request, response, _make_db())
        assert exc_info.value.status_code == 401
        assert "Invalid session" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_wrong_secret_raises_401(self, monkeypatch):
        """Token signed with wrong secret should raise 401."""
        monkeypatch.setattr("backend.routers.auth.get_settings", lambda: SETTINGS)
        wrong_settings = _make_settings(SECRET_KEY="wrong-secret-key-for-unit-test!!")
        token = create_jwt("550e8400-e29b-41d4-a716-446655440000", wrong_settings)
        request = _make_request({COOKIE_NAME: token})
        response = _make_response()
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_id(request, response, _make_db())
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_token_missing_sub_raises_401(self, monkeypatch):
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
            await get_current_user_id(request, response, _make_db())
        assert exc_info.value.status_code == 401
        assert "missing subject" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_revoked_token_raises_401(self, monkeypatch):
        """Token issued before tokens_invalid_before must be rejected."""
        monkeypatch.setattr("backend.routers.auth.get_settings", lambda: SETTINGS)
        token = create_jwt("550e8400-e29b-41d4-a716-446655440000", SETTINGS)
        # DB reports that tokens issued before a future timestamp are invalid.
        future_revocation = datetime.now(timezone.utc) + timedelta(seconds=5)
        request = _make_request({COOKIE_NAME: token})
        response = _make_response()
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_id(request, response, _make_db(future_revocation))
        assert exc_info.value.status_code == 401
        assert "revoked" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# ensure_fresh_token — default TTL fallback
# ---------------------------------------------------------------------------


class TestEnsureFreshToken:
    def _make_user(self, expires_soon: bool = True) -> MagicMock:
        user = MagicMock()
        if expires_soon:
            user.trakt_token_expires_at = datetime.now(timezone.utc) - timedelta(
                hours=1
            )
        else:
            user.trakt_token_expires_at = datetime.now(timezone.utc) + timedelta(
                hours=2
            )
        user.trakt_refresh_token = "refresh-tok"
        user.trakt_access_token = "old-access"
        return user

    @pytest.mark.asyncio
    async def test_uses_default_ttl_when_expires_in_missing(self, monkeypatch):
        """When Trakt omits expires_in, token expiry uses the default TTL."""
        monkeypatch.setattr("backend.routers.auth.get_settings", lambda: SETTINGS)
        mock_client = AsyncMock()
        mock_client.refresh_token.return_value = {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            # No expires_in key
        }
        monkeypatch.setattr(
            "backend.routers.auth.TraktClient", lambda **kw: mock_client
        )
        user = self._make_user(expires_soon=True)
        db = AsyncMock()

        now = datetime.now(timezone.utc)
        await ensure_fresh_token(user, db)

        expected = now + timedelta(seconds=_TRAKT_TOKEN_DEFAULT_TTL_SECONDS)
        actual = user.trakt_token_expires_at
        assert abs((actual - expected).total_seconds()) < 5

    @pytest.mark.asyncio
    async def test_uses_provided_expires_in(self, monkeypatch):
        """When Trakt provides expires_in, that value is used."""
        monkeypatch.setattr("backend.routers.auth.get_settings", lambda: SETTINGS)
        mock_client = AsyncMock()
        mock_client.refresh_token.return_value = {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        }
        monkeypatch.setattr(
            "backend.routers.auth.TraktClient", lambda **kw: mock_client
        )
        user = self._make_user(expires_soon=True)
        db = AsyncMock()

        now = datetime.now(timezone.utc)
        await ensure_fresh_token(user, db)

        expected = now + timedelta(seconds=3600)
        actual = user.trakt_token_expires_at
        assert abs((actual - expected).total_seconds()) < 5


# ---------------------------------------------------------------------------
# update_settings
# ---------------------------------------------------------------------------


def _make_starlette_request() -> StarletteRequest:
    """Create a minimal real Starlette Request for rate-limited endpoints."""
    scope = {
        "type": "http",
        "method": "PATCH",
        "path": "/api/me/settings",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "app": MagicMock(),
    }
    scope["app"].state.limiter.enabled = False
    return StarletteRequest(scope)


class TestUpdateSettings:
    def _make_user(self, sync_ratings: bool = False) -> MagicMock:
        user = MagicMock()
        user.id = "00000000-0000-0000-0000-000000000001"
        user.trakt_username = "testuser"
        user.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        user.sync_ratings_to_trakt = sync_ratings
        return user

    @pytest.mark.asyncio
    async def test_update_settings_enables_sync(self, monkeypatch):
        """Enables sync: sets flag to True, commits, and returns updated response."""
        monkeypatch.setattr(limiter, "enabled", False)

        user = self._make_user(sync_ratings=False)
        db = AsyncMock()

        result = await update_settings(
            body=UserSettingsUpdate(sync_ratings_to_trakt=True),
            request=_make_starlette_request(),
            current_user=user,
            db=db,
        )

        assert user.sync_ratings_to_trakt is True
        db.commit.assert_awaited_once()
        db.refresh.assert_not_awaited()
        assert result.sync_ratings_to_trakt is True

    @pytest.mark.asyncio
    async def test_update_settings_disables_sync(self, monkeypatch):
        """Disables sync: sets flag to False and returns updated response."""
        monkeypatch.setattr(limiter, "enabled", False)

        user = self._make_user(sync_ratings=True)
        db = AsyncMock()

        result = await update_settings(
            body=UserSettingsUpdate(sync_ratings_to_trakt=False),
            request=_make_starlette_request(),
            current_user=user,
            db=db,
        )

        assert user.sync_ratings_to_trakt is False
        assert result.sync_ratings_to_trakt is False
