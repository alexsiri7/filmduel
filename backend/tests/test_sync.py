"""Tests for backend.services.sync — ELO-to-Trakt sync logic."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.sync import _rate_with_retry


# ---------------------------------------------------------------------------
# _rate_with_retry — tests retry-on-5xx and swallow behaviour
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rate_with_retry_success():
    """Happy path: rate_movie is called once and returns."""
    client = MagicMock()
    client.rate_movie = AsyncMock()

    await _rate_with_retry(client, trakt_id=101, rating=7)

    client.rate_movie.assert_awaited_once_with(101, 7)


@pytest.mark.asyncio
async def test_rate_with_retry_retries_on_5xx():
    """A 5xx triggers one retry; success on retry is silent."""
    import httpx

    client = MagicMock()
    err_response = MagicMock()
    err_response.status_code = 503
    server_error = httpx.HTTPStatusError(
        "service unavailable", request=MagicMock(), response=err_response
    )
    client.rate_movie = AsyncMock(side_effect=[server_error, None])

    await _rate_with_retry(client, trakt_id=202, rating=5)

    assert client.rate_movie.await_count == 2


@pytest.mark.asyncio
async def test_rate_with_retry_swallows_5xx_on_second_attempt():
    """If both attempts fail with 5xx, the error is swallowed."""
    import httpx

    client = MagicMock()
    err_response = MagicMock()
    err_response.status_code = 500
    server_error = httpx.HTTPStatusError(
        "internal server error", request=MagicMock(), response=err_response
    )
    client.rate_movie = AsyncMock(side_effect=[server_error, server_error])

    # Must not raise
    await _rate_with_retry(client, trakt_id=303, rating=3)
    assert client.rate_movie.await_count == 2


@pytest.mark.asyncio
async def test_rate_with_retry_swallows_401():
    """A 401 (expired token) is logged and swallowed — not retried."""
    import httpx

    client = MagicMock()
    err_response = MagicMock()
    err_response.status_code = 401
    auth_error = httpx.HTTPStatusError(
        "unauthorized", request=MagicMock(), response=err_response
    )
    client.rate_movie = AsyncMock(side_effect=auth_error)

    await _rate_with_retry(client, trakt_id=404, rating=4)

    # Only one attempt — 401 is not retried
    client.rate_movie.assert_awaited_once_with(404, 4)


@pytest.mark.asyncio
async def test_sync_duel_ratings_calls_rate_movie():
    """sync_duel_ratings calls rate_movie for each duel movie."""
    from unittest.mock import AsyncMock, MagicMock, patch

    uid = str(uuid.uuid4())
    mid_a = str(uuid.uuid4())
    mid_b = str(uuid.uuid4())

    # Build mock session with the queries sync_duel_ratings executes:
    # 1. all ELOs for the user
    # 2. trakt_ids for the two movies
    # 3. ELOs for the two movies

    mock_session = AsyncMock()

    all_elos_result = MagicMock()
    all_elos_result.all.return_value = [(1000,), (1200,), (1400,)]

    trakt_map_result = MagicMock()
    trakt_row_a = MagicMock()
    trakt_row_a.id = uuid.UUID(mid_a)
    trakt_row_a.trakt_id = 111
    trakt_row_b = MagicMock()
    trakt_row_b.id = uuid.UUID(mid_b)
    trakt_row_b.trakt_id = 222
    trakt_map_result.all.return_value = [trakt_row_a, trakt_row_b]

    elo_map_result = MagicMock()
    elo_row_a = MagicMock()
    elo_row_a.movie_id = uuid.UUID(mid_a)
    elo_row_a.elo = 1200
    elo_row_b = MagicMock()
    elo_row_b.movie_id = uuid.UUID(mid_b)
    elo_row_b.elo = 1400
    elo_map_result.all.return_value = [elo_row_a, elo_row_b]

    mock_session.execute = AsyncMock(
        side_effect=[all_elos_result, trakt_map_result, elo_map_result]
    )

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("backend.services.sync.async_session_factory", return_value=mock_ctx),
        patch("backend.services.sync.TraktClient") as MockClient,
    ):
        instance = MockClient.return_value
        instance.rate_movie = AsyncMock()

        from backend.services.sync import sync_duel_ratings
        await sync_duel_ratings(uid, "token-xyz", mid_a, mid_b)

    assert instance.rate_movie.await_count == 2
    called_ids = {call.args[0] for call in instance.rate_movie.call_args_list}
    assert called_ids == {111, 222}


@pytest.mark.asyncio
async def test_sync_duel_ratings_no_elos_exits_early():
    """sync_duel_ratings exits immediately when user has no ELO history."""
    uid = str(uuid.uuid4())
    mid_a = str(uuid.uuid4())
    mid_b = str(uuid.uuid4())

    mock_session = AsyncMock()
    empty_result = MagicMock()
    empty_result.all.return_value = []
    mock_session.execute = AsyncMock(return_value=empty_result)

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("backend.services.sync.async_session_factory", return_value=mock_ctx),
        patch("backend.services.sync.TraktClient") as MockClient,
    ):
        from backend.services.sync import sync_duel_ratings
        await sync_duel_ratings(uid, "token-xyz", mid_a, mid_b)

    MockClient.assert_not_called()
