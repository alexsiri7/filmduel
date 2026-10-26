"""Tests for backend.services.token_refresh — Trakt token-refresh gating and execution."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.config import Settings
from backend.services.token_refresh import ensure_fresh_token, trakt_token_needs_refresh


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


# ---------------------------------------------------------------------------
# trakt_token_needs_refresh
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "user,expected",
    [
        pytest.param(
            SimpleNamespace(
                trakt_token_expires_at=datetime.now(timezone.utc).replace(tzinfo=None)
                + timedelta(minutes=30),
                trakt_access_token="enc",
            ),
            True,
            id="naive-expiry-30min-future-needs-refresh",
        ),
        pytest.param(
            SimpleNamespace(
                trakt_token_expires_at=datetime.now(timezone.utc).replace(tzinfo=None)
                + timedelta(hours=2),
                trakt_access_token="enc",
            ),
            False,
            id="naive-expiry-2hr-future-does-not-need-refresh",
        ),
        pytest.param(
            SimpleNamespace(
                trakt_token_expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
                trakt_access_token="enc",
            ),
            True,
            id="aware-expiry-30min-future-needs-refresh",
        ),
        pytest.param(
            SimpleNamespace(
                trakt_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
                trakt_access_token="enc",
            ),
            False,
            id="aware-expiry-2hr-future-does-not-need-refresh",
        ),
        pytest.param(
            SimpleNamespace(
                trakt_token_expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
                trakt_access_token=None,
            ),
            False,
            id="no-encrypted-token-does-not-need-refresh",
        ),
        pytest.param(
            SimpleNamespace(
                trakt_token_expires_at=None,
                trakt_access_token="enc",
            ),
            False,
            id="no-expiry-does-not-need-refresh",
        ),
    ],
)
def test_trakt_token_needs_refresh(user, expected):
    # Arrange: user fixture provided via parametrize.
    # Act
    result = trakt_token_needs_refresh(user)
    # Assert
    assert result is expected


# ---------------------------------------------------------------------------
# ensure_fresh_token
# ---------------------------------------------------------------------------


def _make_user(expires_soon: bool, refresh_token: str = "refresh-tok") -> MagicMock:
    user = MagicMock()
    if expires_soon:
        user.trakt_token_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    else:
        user.trakt_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=2)
    user.trakt_access_token = "enc"
    user.trakt_refresh_token = refresh_token
    user.trakt_access_token = "old-access"
    return user


@pytest.mark.asyncio
async def test_ensure_fresh_token_returns_same_user_without_calling_trakt_when_not_needed(
    monkeypatch,
):
    """When the token doesn't need refreshing, ensure_fresh_token is a no-op."""
    # Arrange
    user = _make_user(expires_soon=False)
    mock_trakt_client_class = MagicMock()
    monkeypatch.setattr(
        "backend.services.token_refresh.TraktClient", mock_trakt_client_class
    )
    db = AsyncMock()

    # Act
    result = await ensure_fresh_token(user, db)

    # Assert
    mock_trakt_client_class.assert_not_called()
    db.flush.assert_not_awaited()
    assert result is user


@pytest.mark.asyncio
async def test_ensure_fresh_token_keeps_old_refresh_token_when_response_omits_one(
    monkeypatch,
):
    """When Trakt's refresh response has no refresh_token, the old one is kept
    and last_seen_at is stamped to the current time."""
    # Arrange
    monkeypatch.setattr("backend.services.token_refresh.get_settings", lambda: SETTINGS)
    mock_client = AsyncMock()
    mock_client.refresh_token.return_value = {
        "access_token": "new-access",
        "expires_in": 3600,
        # No refresh_token key
    }
    monkeypatch.setattr(
        "backend.services.token_refresh.TraktClient", lambda **kw: mock_client
    )
    user = _make_user(expires_soon=True, refresh_token="original-refresh-token")
    user.trakt_access_token = "old-access"
    db = AsyncMock()

    # Act
    before = datetime.now(timezone.utc)
    await ensure_fresh_token(user, db)
    after = datetime.now(timezone.utc)

    # Assert
    assert user.trakt_refresh_token == "original-refresh-token"
    assert user.trakt_access_token == "new-access"
    assert user.last_seen_at.tzinfo is not None
    assert before - timedelta(seconds=5) <= user.last_seen_at <= after + timedelta(seconds=5)
    db.flush.assert_awaited_once()
