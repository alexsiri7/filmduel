"""Tests for TraktClient.refresh_token and auth.ensure_fresh_token."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.trakt import TraktClient


# ---------------------------------------------------------------------------
# TraktClient.refresh_token
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_token_returns_new_tokens():
    """refresh_token POSTs to the token endpoint and returns parsed JSON."""
    fake_response = {
        "access_token": "new-access",
        "refresh_token": "new-refresh",
        "expires_in": 7776000,
    }

    mock_response = MagicMock()
    mock_response.json.return_value = fake_response
    mock_response.raise_for_status = MagicMock()

    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=mock_response)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.services.trakt.httpx.AsyncClient", return_value=mock_http):
        client = TraktClient(access_token="old-access")
        result = await client.refresh_token("old-refresh")

    assert result["access_token"] == "new-access"
    assert result["refresh_token"] == "new-refresh"

    posted = mock_http.post.call_args.kwargs.get("json") or mock_http.post.call_args.args[1]
    assert posted["grant_type"] == "refresh_token"
    assert posted["refresh_token"] == "old-refresh"


@pytest.mark.asyncio
async def test_refresh_token_raises_on_http_error():
    """refresh_token propagates HTTP errors from the token endpoint."""
    import httpx

    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "unauthorized", request=MagicMock(), response=mock_response
    )

    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=mock_response)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.services.trakt.httpx.AsyncClient", return_value=mock_http):
        client = TraktClient()
        with pytest.raises(httpx.HTTPStatusError):
            await client.refresh_token("bad-refresh-token")


# ---------------------------------------------------------------------------
# ensure_fresh_token (auth router helper)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ensure_fresh_token_refreshes_near_expiry():
    """ensure_fresh_token performs a token refresh when expiry is within 1 hour."""
    from backend.routers.auth import ensure_fresh_token

    user = MagicMock()
    user.trakt_access_token = "old-access"
    user.trakt_refresh_token = "old-refresh"
    user.trakt_token_expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)

    db = AsyncMock()
    db.flush = AsyncMock()

    new_tokens = {
        "access_token": "fresh-access",
        "refresh_token": "fresh-refresh",
        "expires_in": 7776000,
    }

    with patch("backend.routers.auth.TraktClient") as MockClient:
        instance = MockClient.return_value
        instance.refresh_token = AsyncMock(return_value=new_tokens)

        result = await ensure_fresh_token(user, db)

    assert result.trakt_access_token == "fresh-access"
    assert result.trakt_refresh_token == "fresh-refresh"
    db.flush.assert_awaited_once()
    instance.refresh_token.assert_awaited_once_with("old-refresh")


@pytest.mark.asyncio
async def test_ensure_fresh_token_skips_refresh_when_valid():
    """ensure_fresh_token returns existing user when token is not near expiry."""
    from backend.routers.auth import ensure_fresh_token

    user = MagicMock()
    user.trakt_access_token = "valid-access"
    user.trakt_refresh_token = "valid-refresh"
    user.trakt_token_expires_at = datetime.now(timezone.utc) + timedelta(days=30)

    db = AsyncMock()

    with patch("backend.routers.auth.TraktClient") as MockClient:
        result = await ensure_fresh_token(user, db)

    assert result is user
    MockClient.assert_not_called()
    db.flush.assert_not_awaited()
