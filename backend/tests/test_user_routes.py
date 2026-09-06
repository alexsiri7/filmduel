"""Tests for DELETE /api/me (account deletion)."""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("TOKEN_ENC_KEY", "test-secret-key-for-unit-tests-32b")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests!!")

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.db import get_db
from backend.rate_limit import limiter
from backend.routers.auth import COOKIE_NAME, get_current_user


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


# ---------------------------------------------------------------------------
# DELETE /api/me — session cookie cleared
# ---------------------------------------------------------------------------


def test_delete_account_clears_cookie():
    """DELETE /api/me returns 204 and clears the session cookie."""
    fake_user = _make_user()
    mock_db = AsyncMock()

    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_db] = lambda: mock_db

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.delete("/api/me")

    assert resp.status_code == 204
    # Cookie deletion: set-cookie header with max-age=0 or empty value
    set_cookie = resp.headers.get("set-cookie", "")
    assert COOKIE_NAME in set_cookie


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

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.delete("/api/me")

    assert resp.status_code == 204
    mock_trakt_cls.assert_not_called()
    mock_simkl_cls.assert_not_called()
