"""Tests for sync service — _rate_with_retry_simkl."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from backend.services.sync import _rate_with_retry_simkl


def _make_simkl_client(side_effects=None):
    """Build a mock SimklClient whose rate() method uses the given side_effects."""
    client = AsyncMock()
    if side_effects is not None:
        client.rate.side_effect = side_effects
    return client


def _http_error(status_code: int) -> httpx.HTTPStatusError:
    """Create an HTTPStatusError with the given status code."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    return httpx.HTTPStatusError("error", request=MagicMock(), response=resp)


class TestRateWithRetrySimkl:
    @pytest.mark.asyncio
    async def test_succeeds_on_first_attempt(self):
        """When rate() succeeds immediately, it is only called once."""
        client = _make_simkl_client()
        await _rate_with_retry_simkl(client, simkl_id=123, rating=8, media_type="movie")
        client.rate.assert_awaited_once_with(123, 8, media_type="movie")

    @pytest.mark.asyncio
    async def test_retries_once_on_5xx(self):
        """On a 5xx error, rate() is retried exactly once."""
        client = _make_simkl_client(
            side_effects=[_http_error(503), None]  # fail then succeed
        )
        await _rate_with_retry_simkl(client, simkl_id=456, rating=7, media_type="movie")
        assert client.rate.await_count == 2

    @pytest.mark.asyncio
    async def test_does_not_retry_on_4xx(self):
        """On a 4xx error, rate() is NOT retried — only called once."""
        client = _make_simkl_client(
            side_effects=[_http_error(422)]
        )
        await _rate_with_retry_simkl(client, simkl_id=789, rating=5, media_type="movie")
        # Should return after first attempt without retrying
        assert client.rate.await_count == 1

    @pytest.mark.asyncio
    async def test_two_consecutive_5xx_stops_after_second(self):
        """If both attempts fail with 5xx, function returns without raising."""
        client = _make_simkl_client(
            side_effects=[_http_error(500), _http_error(500)]
        )
        # Should not raise — errors are logged and swallowed
        await _rate_with_retry_simkl(client, simkl_id=1, rating=3, media_type="movie")
        assert client.rate.await_count == 2

    @pytest.mark.asyncio
    async def test_unexpected_exception_is_swallowed(self):
        """Unexpected non-HTTP exceptions are caught and do not propagate."""
        client = _make_simkl_client(
            side_effects=[RuntimeError("unexpected")]
        )
        await _rate_with_retry_simkl(client, simkl_id=99, rating=6, media_type="movie")
        assert client.rate.await_count == 1

    @pytest.mark.asyncio
    async def test_passes_media_type_to_client(self):
        """media_type kwarg is forwarded to the underlying client.rate() call."""
        client = _make_simkl_client()
        await _rate_with_retry_simkl(client, simkl_id=10, rating=9, media_type="show")
        client.rate.assert_awaited_once_with(10, 9, media_type="show")
