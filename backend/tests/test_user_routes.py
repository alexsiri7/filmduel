"""Tests for DELETE /api/me (account deletion)."""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("TOKEN_ENC_KEY", "test-secret-key-for-unit-tests-32b")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests!!")

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import app
from backend.tests import SPA_HEADERS
from backend.db import get_db
from backend.rate_limit import limiter
from backend.routers.auth import COOKIE_NAME, get_current_user
from backend.utils.cookies import cookie_name


@pytest.fixture(autouse=True)
def _clear_dependency_overrides():
    """Ensure dependency overrides are cleaned up even if a test raises."""
    limiter.enabled = False
    yield
    app.dependency_overrides.clear()
    limiter.enabled = True


def _make_user(*, trakt_token=None, simkl_token=None):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.trakt_access_token_enc = trakt_token
    user.simkl_access_token_enc = simkl_token
    return user


def _make_settings(**overrides) -> Settings:
    defaults = {
        "SECRET_KEY": "test-secret-key-for-unit-tests!!",
        "TRAKT_CLIENT_ID": "",
        "TRAKT_CLIENT_SECRET": "",
        "DATABASE_URL": "postgresql+asyncpg://localhost/test",
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _assert_session_cookie_cleared(set_cookie: str, secure: bool) -> None:
    """The Set-Cookie header must expire the session cookie.

    In Secure mode the name is __Host-prefixed and the expiry must itself
    carry Secure, or the browser discards it and the cookie survives.
    """
    assert set_cookie.startswith(f'{cookie_name(COOKIE_NAME, secure)}=""')
    assert "Max-Age=0" in set_cookie
    assert ("Secure" in set_cookie) is secure


def _delete_account(settings: Settings):
    fake_user = _make_user()
    mock_db = AsyncMock()

    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("backend.routers.users.get_settings", return_value=settings):
        with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
            resp = client.delete("/api/me")

    assert resp.status_code == 204
    return resp.headers["set-cookie"]


# ---------------------------------------------------------------------------
# DELETE /api/me — session cookie cleared
# ---------------------------------------------------------------------------


def test_delete_account_clears_cookie():
    """DELETE /api/me returns 204 and clears the bare-named session cookie without Secure."""
    set_cookie = _delete_account(_make_settings())
    _assert_session_cookie_cleared(set_cookie, secure=False)


def test_delete_account_clears_prefixed_cookie_with_secure():
    """With Secure cookies, DELETE /api/me expires __Host-filmduel_session and keeps Secure."""
    set_cookie = _delete_account(_make_settings(BASE_URL="https://filmduel.example.com"))
    _assert_session_cookie_cleared(set_cookie, secure=True)


# ---------------------------------------------------------------------------
# DELETE /api/me — no linked providers succeeds
# ---------------------------------------------------------------------------


@patch("backend.routers.users.TraktClient")
@patch("backend.routers.users.SimklClient")
def test_delete_account_no_providers_succeeds(mock_simkl_cls, mock_trakt_cls):
    """User with no linked providers can delete account without revocation errors."""
    fake_user = _make_user(trakt_token=None, simkl_token=None)
    mock_db = AsyncMock()

    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_db] = lambda: mock_db

    with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
        resp = client.delete("/api/me")

    assert resp.status_code == 204
    mock_trakt_cls.assert_not_called()
    mock_simkl_cls.assert_not_called()
