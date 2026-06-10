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
from backend.schemas import ConsentAccept, UserSettingsUpdate
from starlette.requests import Request as StarletteRequest

from backend.routers.auth import (
    COOKIE_NAME,
    JWT_ALGORITHM,
    JWT_EXPIRY_HOURS,
    OAUTH_SIMKL_STATE_COOKIE,
    REFRESH_INTERVAL,
    SESSION_MAX_LIFETIME,
    _TRAKT_TOKEN_DEFAULT_TTL_SECONDS,
    create_jwt,
    ensure_fresh_token,
    get_current_user_id,
    simkl_callback,
)
from backend.routers.users import (
    CURRENT_PRIVACY_POLICY_VERSION,
    accept_consent,
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


def _make_jwt_payload(**overrides) -> dict:
    """Build a JWT payload dict with test defaults; use overrides for per-test variations."""
    now = datetime.now(timezone.utc)
    base = {
        "sub": "550e8400-e29b-41d4-a716-446655440000",
        "jti": "x",
        "iss": "filmduel",
        "aud": "filmduel",
        "exp": now + timedelta(hours=1),
        "iat": now - timedelta(hours=1),
    }
    base.update(overrides)
    return base


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

    def test_orig_iat_defaults_to_iat_when_not_provided(self):
        """When orig_iat is omitted, payload orig_iat should equal iat."""
        token = create_jwt("user-1", SETTINGS)
        payload = pyjwt.decode(
            token,
            SETTINGS.SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
            issuer="filmduel",
            audience="filmduel",
        )
        assert "orig_iat" in payload
        assert abs(payload["orig_iat"] - payload["iat"]) < 2

    def test_orig_iat_is_preserved_when_provided(self):
        """When orig_iat is passed, the payload carries that exact timestamp."""
        orig = datetime.now(timezone.utc) - timedelta(days=10)
        token = create_jwt("user-1", SETTINGS, orig_iat=orig)
        payload = pyjwt.decode(
            token,
            SETTINGS.SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
            issuer="filmduel",
            audience="filmduel",
        )
        assert abs(payload["orig_iat"] - orig.timestamp()) < 2


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
        response.delete_cookie.assert_called_once_with(COOKIE_NAME)

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
        response.delete_cookie.assert_called_once_with(COOKIE_NAME)

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
        response.delete_cookie.assert_called_once_with(COOKIE_NAME)

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
        response.delete_cookie.assert_called_once_with(COOKIE_NAME)

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
        response.delete_cookie.assert_called_once_with(COOKIE_NAME)

    @pytest.mark.asyncio
    async def test_hard_cap_rejects_session_older_than_30_days(self, monkeypatch):
        """A session older than SESSION_MAX_DAYS must be rejected even if JWT is fresh."""
        monkeypatch.setattr("backend.routers.auth.get_settings", lambda: SETTINGS)
        orig = datetime.now(timezone.utc) - SESSION_MAX_LIFETIME - timedelta(hours=1)
        payload = _make_jwt_payload(orig_iat=orig.timestamp())
        token = pyjwt.encode(payload, SETTINGS.SECRET_KEY, algorithm=JWT_ALGORITHM)
        request = _make_request({COOKIE_NAME: token})
        response = _make_response()
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_id(request, response, _make_db())
        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail.lower()
        response.delete_cookie.assert_called_once_with(COOKIE_NAME)

    @pytest.mark.asyncio
    async def test_refresh_preserves_orig_iat(self, monkeypatch):
        """Refreshed token must carry forward the original orig_iat."""
        monkeypatch.setattr("backend.routers.auth.get_settings", lambda: SETTINGS)
        orig = datetime.now(timezone.utc) - timedelta(days=5)
        old_iat = datetime.now(timezone.utc) - REFRESH_INTERVAL - timedelta(hours=1)
        payload = _make_jwt_payload(iat=old_iat, orig_iat=orig.timestamp())
        token = pyjwt.encode(payload, SETTINGS.SECRET_KEY, algorithm=JWT_ALGORITHM)
        request = _make_request({COOKIE_NAME: token})
        response = _make_response()
        await get_current_user_id(request, response, _make_db())
        response.set_cookie.assert_called_once()
        # Decode the newly issued token and verify orig_iat was preserved
        new_token = response.set_cookie.call_args.args[1]
        new_payload = pyjwt.decode(
            new_token,
            SETTINGS.SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
            audience="filmduel",
            issuer="filmduel",
        )
        assert abs(new_payload["orig_iat"] - orig.timestamp()) < 2

    @pytest.mark.asyncio
    async def test_legacy_token_without_orig_iat_accepted(self, monkeypatch):
        """Tokens missing orig_iat (issued before the fix) should still work."""
        monkeypatch.setattr("backend.routers.auth.get_settings", lambda: SETTINGS)
        payload = _make_jwt_payload()  # no orig_iat — simulates a pre-fix token
        token = pyjwt.encode(payload, SETTINGS.SECRET_KEY, algorithm=JWT_ALGORITHM)
        request = _make_request({COOKIE_NAME: token})
        response = _make_response()
        result = await get_current_user_id(request, response, _make_db())
        assert result == "550e8400-e29b-41d4-a716-446655440000"

    @pytest.mark.asyncio
    async def test_legacy_token_refresh_sets_orig_iat_to_iat(self, monkeypatch):
        """Refreshing a legacy token should set orig_iat = iat in the new token."""
        monkeypatch.setattr("backend.routers.auth.get_settings", lambda: SETTINGS)
        old_iat = datetime.now(timezone.utc) - REFRESH_INTERVAL - timedelta(hours=1)
        payload = _make_jwt_payload(iat=old_iat)  # no orig_iat — simulates a pre-fix token
        token = pyjwt.encode(payload, SETTINGS.SECRET_KEY, algorithm=JWT_ALGORITHM)
        request = _make_request({COOKIE_NAME: token})
        response = _make_response()
        await get_current_user_id(request, response, _make_db())
        response.set_cookie.assert_called_once()
        new_token = response.set_cookie.call_args.args[1]
        new_payload = pyjwt.decode(
            new_token,
            SETTINGS.SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
            audience="filmduel",
            issuer="filmduel",
        )
        # orig_iat in the refreshed token should equal the legacy token's iat
        assert abs(new_payload["orig_iat"] - old_iat.timestamp()) < 2

    @pytest.mark.asyncio
    async def test_cookie_max_age_capped_near_session_limit(self, monkeypatch):
        """Cookie max_age must be capped to remaining session lifetime, not full JWT expiry."""
        monkeypatch.setattr("backend.routers.auth.get_settings", lambda: SETTINGS)
        # Session started 29d 23h ago — 1h left before hard cap
        orig = datetime.now(timezone.utc) - SESSION_MAX_LIFETIME + timedelta(hours=1)
        old_iat = datetime.now(timezone.utc) - REFRESH_INTERVAL - timedelta(hours=1)
        payload = _make_jwt_payload(iat=old_iat, orig_iat=orig.timestamp())
        token = pyjwt.encode(payload, SETTINGS.SECRET_KEY, algorithm=JWT_ALGORITHM)
        request = _make_request({COOKIE_NAME: token})
        response = _make_response()
        await get_current_user_id(request, response, _make_db())
        response.set_cookie.assert_called_once()
        kwargs = response.set_cookie.call_args.kwargs
        max_age = kwargs.get("max_age")
        assert max_age is not None
        # Should be capped to ~1h (3600s), not the full JWT_EXPIRY_HOURS * 3600
        assert max_age <= 3600 + 30  # 30s tolerance for test execution time
        assert max_age > 0  # not yet expired

    @pytest.mark.asyncio
    async def test_refreshes_old_token_max_age_is_full_jwt_expiry(self, monkeypatch):
        """Refresh of a recent session uses the full JWT expiry as max_age."""
        monkeypatch.setattr("backend.routers.auth.get_settings", lambda: SETTINGS)
        orig = datetime.now(timezone.utc) - timedelta(days=5)  # well within 30 days
        old_iat = datetime.now(timezone.utc) - REFRESH_INTERVAL - timedelta(hours=1)
        payload = _make_jwt_payload(iat=old_iat, orig_iat=orig.timestamp())
        token = pyjwt.encode(payload, SETTINGS.SECRET_KEY, algorithm=JWT_ALGORITHM)
        request = _make_request({COOKIE_NAME: token})
        response = _make_response()
        await get_current_user_id(request, response, _make_db())
        kwargs = response.set_cookie.call_args.kwargs
        assert kwargs["max_age"] == JWT_EXPIRY_HOURS * 3600

    @pytest.mark.asyncio
    async def test_refreshes_near_expiry_session_gets_reduced_max_age(
        self, monkeypatch
    ):
        """Refresh near the 30-day cap produces a reduced max_age, not the full JWT expiry."""
        monkeypatch.setattr("backend.routers.auth.get_settings", lambda: SETTINGS)
        # 29 days 20 hours old — only 4 hours of session lifetime remain
        orig = datetime.now(timezone.utc) - SESSION_MAX_LIFETIME + timedelta(hours=4)
        old_iat = datetime.now(timezone.utc) - REFRESH_INTERVAL - timedelta(hours=1)
        payload = _make_jwt_payload(iat=old_iat, orig_iat=orig.timestamp())
        token = pyjwt.encode(payload, SETTINGS.SECRET_KEY, algorithm=JWT_ALGORITHM)
        request = _make_request({COOKIE_NAME: token})
        response = _make_response()
        await get_current_user_id(request, response, _make_db())
        kwargs = response.set_cookie.call_args.kwargs
        # max_age should be capped to ~4 hours, well under the 72-hour JWT expiry
        assert kwargs["max_age"] < JWT_EXPIRY_HOURS * 3600
        assert kwargs["max_age"] > 0  # still some life left
        assert kwargs["max_age"] <= 4 * 3600 + 60  # within 4h + 1min tolerance

    @pytest.mark.asyncio
    async def test_malformed_orig_iat_raises_401(self, monkeypatch):
        """A token with a non-numeric orig_iat claim should raise 401, not 500."""
        monkeypatch.setattr("backend.routers.auth.get_settings", lambda: SETTINGS)
        payload = _make_jwt_payload(
            iat=datetime.now(timezone.utc),
            orig_iat="not-a-timestamp",  # malformed
        )
        token = pyjwt.encode(payload, SETTINGS.SECRET_KEY, algorithm=JWT_ALGORITHM)
        request = _make_request({COOKIE_NAME: token})
        response = _make_response()
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_id(request, response, _make_db())
        assert exc_info.value.status_code == 401
        assert "Invalid session" in exc_info.value.detail
        response.delete_cookie.assert_called_once_with(COOKIE_NAME)

    @pytest.mark.asyncio
    async def test_user_not_found_clears_cookie(self, monkeypatch):
        """When DB returns no user, cookie must be cleared."""
        monkeypatch.setattr("backend.routers.auth.get_settings", lambda: SETTINGS)
        user_id = "550e8400-e29b-41d4-a716-446655440000"
        token = create_jwt(user_id, SETTINGS)
        request = _make_request({COOKIE_NAME: token})
        response = _make_response()
        db = AsyncMock()
        db.scalar.return_value = None  # simulate missing user
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_id(request, response, db)
        assert exc_info.value.status_code == 401
        assert "not found" in exc_info.value.detail.lower()
        response.delete_cookie.assert_called_once_with(COOKIE_NAME)


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


def _make_starlette_request(cookies: dict | None = None) -> StarletteRequest:
    """Create a minimal real Starlette Request for rate-limited endpoints.

    cookies: optional dict of cookie name→value to include in the request.
    """
    cookie_header = "; ".join(f"{k}={v}" for k, v in (cookies or {}).items())
    headers = [(b"cookie", cookie_header.encode())] if cookie_header else []
    scope = {
        "type": "http",
        "method": "PATCH",
        "path": "/api/me/settings",
        "query_string": b"",
        "headers": headers,
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
        user.simkl_username = None
        user.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        user.sync_ratings_to_trakt = sync_ratings
        user.sync_ratings_to_simkl = False
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


# ---------------------------------------------------------------------------
# accept_consent
# ---------------------------------------------------------------------------


class TestAcceptConsent:
    def _make_user(self) -> MagicMock:
        user = MagicMock()
        user.id = "00000000-0000-0000-0000-000000000001"
        user.trakt_username = "testuser"
        user.simkl_username = None
        user.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        user.sync_ratings_to_trakt = False
        user.sync_ratings_to_simkl = False
        user.privacy_policy_accepted = False
        return user

    @pytest.mark.asyncio
    async def test_accept_consent_sets_fields_and_commits(self, monkeypatch):
        """Accepting consent sets accepted=True, records timestamp/version, commits."""
        monkeypatch.setattr(limiter, "enabled", False)
        user = self._make_user()
        db = AsyncMock()

        result = await accept_consent(
            body=ConsentAccept(version=CURRENT_PRIVACY_POLICY_VERSION),
            request=_make_starlette_request(),
            current_user=user,
            db=db,
        )

        assert user.privacy_policy_accepted is True
        assert user.privacy_policy_version == CURRENT_PRIVACY_POLICY_VERSION
        assert user.privacy_policy_accepted_at is not None
        db.commit.assert_awaited_once()
        assert result.privacy_policy_accepted is True

    @pytest.mark.asyncio
    async def test_accept_consent_returns_updated_user_response(self, monkeypatch):
        """Response includes privacy_policy_accepted=True after acceptance."""
        monkeypatch.setattr(limiter, "enabled", False)
        user = self._make_user()
        db = AsyncMock()

        result = await accept_consent(
            body=ConsentAccept(version=CURRENT_PRIVACY_POLICY_VERSION),
            request=_make_starlette_request(),
            current_user=user,
            db=db,
        )

        assert result.privacy_policy_accepted is True
        assert result.trakt_username == "testuser"

    @pytest.mark.asyncio
    async def test_accept_consent_rejects_wrong_version(self, monkeypatch):
        """Submitting a wrong policy version returns 400."""
        from fastapi import HTTPException as FastAPIHTTPException
        monkeypatch.setattr(limiter, "enabled", False)
        user = self._make_user()
        db = AsyncMock()

        with pytest.raises(FastAPIHTTPException) as exc_info:
            await accept_consent(
                body=ConsentAccept(version="99.0"),
                request=_make_starlette_request(),
                current_user=user,
                db=db,
            )

        assert exc_info.value.status_code == 400
        assert "99.0" in exc_info.value.detail
        db.commit.assert_not_awaited()


# ---------------------------------------------------------------------------
# TestSimklCallback
# ---------------------------------------------------------------------------


class TestSimklCallback:
    @pytest.mark.asyncio
    async def test_rejects_missing_state_cookie(self, monkeypatch):
        """Returns 400 when OAuth state cookie is absent."""
        monkeypatch.setattr(limiter, "enabled", False)
        request = _make_starlette_request(cookies={})  # no state cookie
        db = AsyncMock()
        with pytest.raises(HTTPException) as exc:
            await simkl_callback(
                code="code123",
                state="somestate",
                request=request,
                background_tasks=MagicMock(),
                settings=SETTINGS,
                db=db,
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_rejects_mismatched_state(self, monkeypatch):
        """Returns 400 when state param does not match cookie."""
        monkeypatch.setattr(limiter, "enabled", False)
        request = _make_starlette_request(cookies={OAUTH_SIMKL_STATE_COOKIE: "abc"})
        db = AsyncMock()
        with pytest.raises(HTTPException) as exc:
            await simkl_callback(
                code="code123",
                state="xyz",
                request=request,
                background_tasks=MagicMock(),
                settings=SETTINGS,
                db=db,
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_malformed_profile_dict_raises_502_and_redacts_pii(
        self, monkeypatch, caplog
    ):
        """502 is raised and log contains only dict keys, not values, when profile is malformed."""
        import logging

        monkeypatch.setattr(limiter, "enabled", False)

        mock_tokens = AsyncMock(return_value={"access_token": "tok"})
        mock_client = AsyncMock()
        mock_client.get_profile = AsyncMock(
            return_value={"secret_token": "PII_VALUE", "user": None}
        )

        monkeypatch.setattr("backend.routers.auth.SimklClient.exchange_code", mock_tokens)
        monkeypatch.setattr("backend.routers.auth.SimklClient", lambda **kw: mock_client)

        request = _make_starlette_request(cookies={OAUTH_SIMKL_STATE_COOKIE: "state123"})

        with caplog.at_level(logging.ERROR, logger="backend.routers.auth"):
            with pytest.raises(HTTPException) as exc_info:
                await simkl_callback(
                    code="code123",
                    state="state123",
                    request=request,
                    background_tasks=MagicMock(),
                    settings=SETTINGS,
                    db=AsyncMock(),
                )

        assert exc_info.value.status_code == 502
        assert "PII_VALUE" not in caplog.text  # value must NOT appear
        assert "secret_token" in caplog.text  # key is acceptable

    @pytest.mark.asyncio
    async def test_non_dict_profile_raises_502_and_logs_type_name(
        self, monkeypatch, caplog
    ):
        """502 is raised and log contains type name when profile is not a dict."""
        import logging

        monkeypatch.setattr(limiter, "enabled", False)

        mock_tokens = AsyncMock(return_value={"access_token": "tok"})
        mock_client = AsyncMock()
        mock_client.get_profile = AsyncMock(return_value=None)  # non-dict

        monkeypatch.setattr("backend.routers.auth.SimklClient.exchange_code", mock_tokens)
        monkeypatch.setattr("backend.routers.auth.SimklClient", lambda **kw: mock_client)

        request = _make_starlette_request(cookies={OAUTH_SIMKL_STATE_COOKIE: "state123"})

        with caplog.at_level(logging.ERROR, logger="backend.routers.auth"):
            with pytest.raises(HTTPException) as exc_info:
                await simkl_callback(
                    code="code123",
                    state="state123",
                    request=request,
                    background_tasks=MagicMock(),
                    settings=SETTINGS,
                    db=AsyncMock(),
                )

        assert exc_info.value.status_code == 502
        assert "NoneType" in caplog.text


# ---------------------------------------------------------------------------
# Additional update_settings SIMKL tests
# ---------------------------------------------------------------------------


class TestUpdateSettingsSimkl:
    def _make_user(self) -> MagicMock:
        user = MagicMock()
        user.id = "00000000-0000-0000-0000-000000000001"
        user.trakt_username = "testuser"
        user.simkl_username = None
        user.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        user.sync_ratings_to_trakt = False
        user.sync_ratings_to_simkl = False
        return user

    @pytest.mark.asyncio
    async def test_update_settings_enables_simkl_sync(self, monkeypatch):
        """Enables SIMKL sync: sets flag to True and returns updated response."""
        monkeypatch.setattr(limiter, "enabled", False)
        user = self._make_user()
        db = AsyncMock()
        result = await update_settings(
            body=UserSettingsUpdate(sync_ratings_to_simkl=True),
            request=_make_starlette_request(),
            current_user=user,
            db=db,
        )
        assert user.sync_ratings_to_simkl is True
        db.commit.assert_awaited_once()
        assert result.sync_ratings_to_simkl is True

    @pytest.mark.asyncio
    async def test_update_settings_dual_field_payload(self, monkeypatch):
        """Both trakt and simkl flags can be updated in one request."""
        monkeypatch.setattr(limiter, "enabled", False)
        user = self._make_user()
        db = AsyncMock()
        result = await update_settings(
            body=UserSettingsUpdate(sync_ratings_to_trakt=True, sync_ratings_to_simkl=True),
            request=_make_starlette_request(),
            current_user=user,
            db=db,
        )
        assert user.sync_ratings_to_trakt is True
        assert user.sync_ratings_to_simkl is True
        assert result.sync_ratings_to_trakt is True
        assert result.sync_ratings_to_simkl is True
