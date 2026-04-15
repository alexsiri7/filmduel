"""Tests for suggestion service — taste profile and threshold checks."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.suggest import MIN_RANKED, has_enough_ranked


def _mock_count_result(count: int):
    """Build a mock DB result that returns a scalar count."""
    result = MagicMock()
    result.scalar.return_value = count
    return result


class TestHasEnoughRanked:
    @pytest.mark.asyncio
    async def test_returns_false_below_threshold(self):
        """User with < MIN_RANKED films should return False."""
        db = AsyncMock()
        db.execute.return_value = _mock_count_result(MIN_RANKED - 1)

        result = await has_enough_ranked(uuid.uuid4(), db, "movie")
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_at_threshold(self):
        """User with exactly MIN_RANKED films should return True."""
        db = AsyncMock()
        db.execute.return_value = _mock_count_result(MIN_RANKED)

        result = await has_enough_ranked(uuid.uuid4(), db, "movie")
        assert result is True
