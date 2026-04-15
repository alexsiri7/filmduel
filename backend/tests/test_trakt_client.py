"""Tests for TraktClient HTTP methods."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.services.trakt import TraktClient


def _mock_response(json_data, status_code=200):
    """Build a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


class TestTraktClientExchangeCode:
    @pytest.mark.asyncio
    async def test_exchange_code_posts_correct_payload(self):
        """exchange_code sends correct JSON body and returns token dict."""
        expected_tokens = {"access_token": "abc", "refresh_token": "def", "expires_in": 7776000}
        mock_resp = _mock_response(expected_tokens)

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        client = TraktClient(client_id="test-client-id")
        with patch.object(client, "_client", return_value=mock_client):
            result = await client.exchange_code("auth-code", "secret", "http://redirect")

        assert result == expected_tokens
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "/oauth/token"
        body = call_args[1]["json"]
        assert body["code"] == "auth-code"
        assert body["client_id"] == "test-client-id"
        assert body["client_secret"] == "secret"
        assert body["grant_type"] == "authorization_code"


class TestTraktClientPopular:
    @pytest.mark.asyncio
    async def test_get_popular_movies_url(self):
        """get_popular calls /movies/popular with correct params."""
        mock_resp = _mock_response([{"ids": {"trakt": 1}, "title": "Film"}])

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        client = TraktClient(client_id="test-id")
        with patch.object(client, "_client", return_value=mock_client):
            result = await client.get_popular(limit=50)

        assert result == [{"ids": {"trakt": 1}, "title": "Film"}]
        call_args = mock_client.get.call_args
        assert call_args[0][0] == "/movies/popular"
        assert call_args[1]["params"]["limit"] == 50

    @pytest.mark.asyncio
    async def test_get_popular_shows_url(self):
        """get_popular_shows calls /shows/popular."""
        mock_resp = _mock_response([{"ids": {"trakt": 2}, "title": "Show"}])

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        client = TraktClient(client_id="test-id")
        with patch.object(client, "_client", return_value=mock_client):
            result = await client.get_popular_shows(limit=50)

        assert result == [{"ids": {"trakt": 2}, "title": "Show"}]
        call_args = mock_client.get.call_args
        assert call_args[0][0] == "/shows/popular"


class TestTraktClientAuthHeader:
    def test_auth_header_present_when_token_provided(self):
        """Constructor should add Bearer token when access_token is provided."""
        client = TraktClient(client_id="cid", access_token="my-token")
        assert client._headers["Authorization"] == "Bearer my-token"

    def test_no_auth_header_without_token(self):
        """Constructor should not add Authorization header without access_token."""
        client = TraktClient(client_id="cid")
        assert "Authorization" not in client._headers


class TestTraktClientErrorPropagation:
    @pytest.mark.asyncio
    async def test_http_error_raises(self):
        """4xx/5xx responses should raise HTTPStatusError."""
        mock_resp = _mock_response({}, status_code=401)

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        client = TraktClient(client_id="test-id")
        with patch.object(client, "_client", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await client.get_popular()
