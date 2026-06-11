"""Tests for SimklClient HTTP methods."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.services.simkl import SimklClient


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


class TestSimklClientAuthHeader:
    def test_auth_header_present_when_token_provided(self):
        """Constructor should add Bearer token when access_token is provided."""
        client = SimklClient(client_id="cid", access_token="my-token")
        assert client._headers["Authorization"] == "Bearer my-token"

    def test_no_auth_header_without_token(self):
        """Constructor should not add Authorization header without access_token."""
        client = SimklClient(client_id="cid")
        assert "Authorization" not in client._headers

    def test_api_key_header_always_set(self):
        """simkl-api-key header is always set from client_id."""
        client = SimklClient(client_id="my-key")
        assert client._headers["simkl-api-key"] == "my-key"


class TestSimklClientExchangeCode:
    @pytest.mark.asyncio
    async def test_exchange_code_posts_correct_payload(self):
        """exchange_code sends correct JSON body and returns token dict."""
        expected_tokens = {
            "access_token": "abc",
            "token_type": "Bearer",
        }
        mock_resp = _mock_response(expected_tokens)

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        client = SimklClient(client_id="test-client-id")
        with patch.object(client, "_client", return_value=mock_client):
            result = await client.exchange_code(
                "auth-code", "secret", "http://redirect"
            )

        assert result == expected_tokens
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "/oauth/token"
        body = call_args[1]["json"]
        assert body["code"] == "auth-code"
        assert body["client_id"] == "test-client-id"
        assert body["client_secret"] == "secret"
        assert body["redirect_uri"] == "http://redirect"
        assert body["grant_type"] == "authorization_code"

    @pytest.mark.asyncio
    async def test_exchange_code_includes_verifier_when_provided(self):
        """exchange_code includes code_verifier in body when provided (PKCE)."""
        mock_resp = _mock_response({"access_token": "tok"})

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        client = SimklClient(client_id="test-client-id")
        with patch.object(client, "_client", return_value=mock_client):
            await client.exchange_code(
                "auth-code", "secret", "http://redirect", code_verifier="verifier456"
            )

        body = mock_client.post.call_args[1]["json"]
        assert body["code_verifier"] == "verifier456"

    @pytest.mark.asyncio
    async def test_exchange_code_omits_verifier_when_none(self):
        """exchange_code omits code_verifier from body when not provided (non-PKCE)."""
        mock_resp = _mock_response({"access_token": "tok"})

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        client = SimklClient(client_id="test-client-id")
        with patch.object(client, "_client", return_value=mock_client):
            await client.exchange_code("auth-code", "secret", "http://redirect")

        body = mock_client.post.call_args[1]["json"]
        assert "code_verifier" not in body


class TestSimklClientRate:
    @pytest.mark.asyncio
    async def test_rate_sends_correct_payload(self):
        """rate() sends correct JSON body for a movie rating."""
        mock_resp = _mock_response({})

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        client = SimklClient(client_id="cid", access_token="tok")
        with patch.object(client, "_client", return_value=mock_client):
            await client.rate(simkl_id=12345, rating=8, media_type="movie")

        call_args = mock_client.post.call_args
        assert call_args[0][0] == "/sync/ratings"
        body = call_args[1]["json"]
        assert body == {"movies": [{"rating": 8, "ids": {"simkl": 12345}}]}

    @pytest.mark.asyncio
    async def test_rate_sends_correct_payload_for_show(self):
        """rate() uses the correct key for shows."""
        mock_resp = _mock_response({})

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        client = SimklClient(client_id="cid", access_token="tok")
        with patch.object(client, "_client", return_value=mock_client):
            await client.rate(simkl_id=99, rating=5, media_type="show")

        body = mock_client.post.call_args[1]["json"]
        assert "shows" in body
        assert body["shows"][0]["ids"]["simkl"] == 99


class TestSimklClientGetUserRatings:
    @pytest.mark.asyncio
    async def test_get_user_ratings_parses_correctly(self):
        """get_user_ratings returns list of {rating, simkl_id} dicts."""
        raw = [
            {"rating": 8, "movie": {"ids": {"simkl": 111}}},
            {"rating": 6, "movie": {"ids": {"simkl": 222}}},
        ]
        mock_resp = _mock_response(raw)

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        client = SimklClient(client_id="cid", access_token="tok")
        with patch.object(client, "_client", return_value=mock_client):
            result = await client.get_user_ratings(media_type="movie")

        assert result == [
            {"rating": 8, "simkl_id": 111},
            {"rating": 6, "simkl_id": 222},
        ]

    @pytest.mark.asyncio
    async def test_get_user_ratings_malformed_raises(self):
        """get_user_ratings raises KeyError on unexpected response shape."""
        raw = [{"rating": 8, "film": {}}]  # "movie" key missing
        mock_resp = _mock_response(raw)

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        client = SimklClient(client_id="cid", access_token="tok")
        with patch.object(client, "_client", return_value=mock_client):
            with pytest.raises(KeyError):
                await client.get_user_ratings(media_type="movie")


class TestSimklClientGetUserWatched:
    @pytest.mark.asyncio
    async def test_get_user_watched_unwraps_wrapper_format(self):
        """get_user_watched unwraps the SIMKL wrapper and returns inner movie dicts."""
        raw = {
            "movies": [
                {
                    "last_watched_at": "2024-01-01T00:00:00Z",
                    "movie": {"title": "Film A", "ids": {"simkl": 1}},
                },
                {
                    "last_watched_at": "2024-02-01T00:00:00Z",
                    "movie": {"title": "Film B", "ids": {"simkl": 2}},
                },
            ]
        }
        mock_resp = _mock_response(raw)

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        client = SimklClient(client_id="cid", access_token="tok")
        with patch.object(client, "_client", return_value=mock_client):
            result = await client.get_user_watched(media_type="movie")

        assert result == [
            {"title": "Film A", "ids": {"simkl": 1}},
            {"title": "Film B", "ids": {"simkl": 2}},
        ]

    @pytest.mark.asyncio
    async def test_get_user_watched_skips_entries_without_media_key(self):
        """Entries missing the media_type key are skipped gracefully."""
        raw = {
            "movies": [
                {"last_watched_at": "2024-01-01T00:00:00Z"},  # no "movie" key
                {
                    "last_watched_at": "2024-02-01T00:00:00Z",
                    "movie": {"title": "Film B", "ids": {"simkl": 2}},
                },
            ]
        }
        mock_resp = _mock_response(raw)

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        client = SimklClient(client_id="cid", access_token="tok")
        with patch.object(client, "_client", return_value=mock_client):
            result = await client.get_user_watched(media_type="movie")

        assert result == [{"title": "Film B", "ids": {"simkl": 2}}]

    @pytest.mark.asyncio
    async def test_get_user_watched_empty_list(self):
        """get_user_watched returns empty list when no movies in response."""
        mock_resp = _mock_response({"movies": []})

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        client = SimklClient(client_id="cid", access_token="tok")
        with patch.object(client, "_client", return_value=mock_client):
            result = await client.get_user_watched(media_type="movie")

        assert result == []

    @pytest.mark.asyncio
    async def test_get_user_watched_calls_correct_endpoint(self):
        """get_user_watched calls /sync/all-items/movies/watched."""
        mock_resp = _mock_response({"movies": []})

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        client = SimklClient(client_id="cid", access_token="tok")
        with patch.object(client, "_client", return_value=mock_client):
            await client.get_user_watched(media_type="movie")

        call_args = mock_client.get.call_args
        assert call_args[0][0] == "/sync/all-items/movies/watched"
