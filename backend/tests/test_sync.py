"""Tests for backend.services.sync — retry logic and ELO-to-rating mapping."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.services.sync import _rate_with_retry, sync_post_duel


# ── _rate_with_retry ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rate_with_retry_success():
    """Happy path: rate_movie called once, no retry needed."""
    client = MagicMock()
    client.rate_movie = AsyncMock()

    await _rate_with_retry(client, trakt_id=12345, rating=7)

    client.rate_movie.assert_awaited_once_with(12345, 7)


@pytest.mark.asyncio
async def test_rate_with_retry_retries_on_5xx():
    """On a 5xx response, the call is retried exactly once."""
    client = MagicMock()
    response_5xx = MagicMock()
    response_5xx.status_code = 503
    error_5xx = httpx.HTTPStatusError("503", request=MagicMock(), response=response_5xx)

    client.rate_movie = AsyncMock(side_effect=[error_5xx, None])

    await _rate_with_retry(client, trakt_id=99, rating=8)

    assert client.rate_movie.await_count == 2


@pytest.mark.asyncio
async def test_rate_with_retry_retry_fails_silently():
    """If the retry also fails, the error is swallowed (not raised)."""
    client = MagicMock()
    response_5xx = MagicMock()
    response_5xx.status_code = 500
    error_5xx = httpx.HTTPStatusError("500", request=MagicMock(), response=response_5xx)

    client.rate_movie = AsyncMock(side_effect=[error_5xx, RuntimeError("still down")])

    # Should not raise
    await _rate_with_retry(client, trakt_id=42, rating=5)

    assert client.rate_movie.await_count == 2


@pytest.mark.asyncio
async def test_rate_with_retry_no_retry_on_4xx():
    """On a 4xx error, no retry is attempted."""
    client = MagicMock()
    response_4xx = MagicMock()
    response_4xx.status_code = 422
    error_4xx = httpx.HTTPStatusError("422", request=MagicMock(), response=response_4xx)

    client.rate_movie = AsyncMock(side_effect=error_4xx)

    await _rate_with_retry(client, trakt_id=7, rating=3)

    # Called only once — no retry on 4xx
    client.rate_movie.assert_awaited_once_with(7, 3)


@pytest.mark.asyncio
async def test_rate_with_retry_swallows_unexpected_errors():
    """Non-HTTP exceptions are swallowed without raising."""
    client = MagicMock()
    client.rate_movie = AsyncMock(side_effect=ConnectionError("network down"))

    await _rate_with_retry(client, trakt_id=1, rating=6)

    client.rate_movie.assert_awaited_once()


# ── sync_post_duel ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_post_duel_calls_rate_for_all_movies():
    """sync_post_duel pushes ratings for all (trakt_id, elo) pairs."""
    with patch("backend.services.sync.TraktClient") as MockClient:
        instance = MockClient.return_value
        instance.rate_movie = AsyncMock()

        await sync_post_duel(
            access_token="tok",
            movie_ratings=[(111, 1000), (222, 1200)],
        )

        assert instance.rate_movie.await_count == 2
        trakt_ids_called = {c.args[0] for c in instance.rate_movie.await_args_list}
        assert trakt_ids_called == {111, 222}


@pytest.mark.asyncio
async def test_sync_post_duel_uses_elo_to_trakt_rating():
    """Ratings passed to rate_movie are computed by elo_to_trakt_rating."""
    from backend.services.elo import elo_to_trakt_rating

    with patch("backend.services.sync.TraktClient") as MockClient:
        instance = MockClient.return_value
        instance.rate_movie = AsyncMock()

        elo_a, elo_b = 800, 1400
        await sync_post_duel(
            access_token="tok",
            movie_ratings=[(1, elo_a), (2, elo_b)],
        )

        calls = {c.args[0]: c.args[1] for c in instance.rate_movie.await_args_list}
        assert calls[1] == elo_to_trakt_rating(elo_a)
        assert calls[2] == elo_to_trakt_rating(elo_b)
