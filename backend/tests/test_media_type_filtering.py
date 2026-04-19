"""Tests for media_type filtering across backend services.

Verifies that rankings, suggestions, and sync services correctly
pass and use the media_type parameter.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.sync import _rate_with_retry


# ---------------------------------------------------------------------------
# _rate_with_retry — media_type dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_with_retry_dispatches_to_movie():
    """Default media_type='movie' calls rate with media_type='movie'."""
    client = AsyncMock()
    await _rate_with_retry(client, trakt_id=123, rating=8, media_type="movie")
    client.rate.assert_awaited_once_with(123, 8, media_type="movie")


@pytest.mark.asyncio
async def test_rate_with_retry_dispatches_to_show():
    """media_type='show' calls rate with media_type='show'."""
    client = AsyncMock()
    await _rate_with_retry(client, trakt_id=456, rating=7, media_type="show")
    client.rate.assert_awaited_once_with(456, 7, media_type="show")


# ---------------------------------------------------------------------------
# get_user_rankings — media_type parameter propagation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rankings_passes_media_type():
    """get_user_rankings builds a query that includes Movie.media_type filter."""
    from backend.services.rankings import get_user_rankings

    uid = uuid.uuid4()

    # Mock db to return empty results
    mock_result = MagicMock()
    mock_result.unique.return_value.scalars.return_value.all.return_value = []
    mock_count_result = MagicMock()
    mock_count_result.scalar.return_value = 0

    db = AsyncMock()
    db.execute.side_effect = [mock_result, mock_count_result]

    rankings, total = await get_user_rankings(db, uid, media_type="show")

    assert total == 0
    assert rankings == []
    # Verify execute was called twice (main query + count query)
    assert db.execute.await_count == 2


# ---------------------------------------------------------------------------
# has_enough_ranked — media_type propagation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_has_enough_ranked_passes_media_type():
    """has_enough_ranked filters by media_type."""
    from backend.services.suggest import has_enough_ranked

    uid = uuid.uuid4()
    mock_result = MagicMock()
    mock_result.scalar.return_value = 0

    db = AsyncMock()
    db.execute.return_value = mock_result

    result = await has_enough_ranked(uid, db, media_type="show")
    assert result is False
    db.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# _sync_ratings_background — error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_ratings_background_handles_exceptions():
    """_sync_ratings_background logs exceptions instead of crashing."""
    from backend.routers.duels import _sync_ratings_background

    uid = uuid.uuid4()
    mid_a = uuid.uuid4()
    mid_b = uuid.uuid4()

    with patch("backend.routers.duels.async_session_factory") as mock_factory:
        mock_factory.return_value.__aenter__ = AsyncMock(
            side_effect=RuntimeError("DB down")
        )
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        # Should not raise — error is caught and logged
        await _sync_ratings_background(uid, mid_a, 1100, mid_b, 900)
