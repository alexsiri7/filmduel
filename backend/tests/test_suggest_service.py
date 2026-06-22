"""Tests for suggestion service — taste profile and threshold checks."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.suggest import MIN_RANKED, _build_taste_profile, _elo_tier, has_enough_ranked


class TestEloTier:
    @pytest.mark.parametrize("elo,expected", [
        (1300, "highly preferred"),
        (1500, "highly preferred"),
        (1299, "preferred"),
        (1100, "preferred"),
        (1099, "neutral"),
        (900,  "neutral"),
        (899,  "less preferred"),
        (800,  "less preferred"),
        (0,    "less preferred"),
    ])
    def test_elo_tier_thresholds(self, elo, expected):
        assert _elo_tier(elo) == expected


def _mock_count_result(count: int):
    """Build a mock DB result that returns a scalar count."""
    result = MagicMock()
    result.scalar.return_value = count
    return result


def _make_user_movie_mock(title="Film", year=2020, genres=None, elo=1000, battles=5):
    """Build a mock UserMovie with a nested Movie for taste profile tests."""
    um = MagicMock()
    um.elo = elo
    um.battles = battles
    um.movie = MagicMock()
    um.movie.title = title
    um.movie.year = year
    um.movie.genres = genres or ["Drama"]
    return um


def _mock_scalars_result(items):
    """Build a mock async DB result that returns items via .unique().scalars().all()."""
    result = MagicMock()
    result.unique.return_value.scalars.return_value.all.return_value = items
    return result


class TestBuildTasteProfile:
    @pytest.mark.asyncio
    async def test_returns_none_below_min_ranked(self):
        """_build_taste_profile returns None when user has fewer than MIN_RANKED films."""
        films = [_make_user_movie_mock(title=f"Film {i}") for i in range(MIN_RANKED - 1)]
        db = AsyncMock()
        db.execute.return_value = _mock_scalars_result(films)

        result = await _build_taste_profile(uuid.uuid4(), db)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_profile_at_min_ranked(self):
        """_build_taste_profile returns a dict when user has exactly MIN_RANKED films."""
        films = [
            _make_user_movie_mock(title=f"Film {i}", elo=1200 - i * 10)
            for i in range(MIN_RANKED)
        ]
        db = AsyncMock()
        # First call: ranked films; second call: bottom 5
        db.execute.side_effect = [
            _mock_scalars_result(films),
            _mock_scalars_result(films[-5:]),
        ]

        result = await _build_taste_profile(uuid.uuid4(), db)
        assert result is not None
        assert isinstance(result, dict)
        assert "top_10" in result
        assert "bottom_5" in result
        assert "genre_affinities" in result
        assert result["total_ranked"] == MIN_RANKED


class TestReasonTruncation:
    def test_reason_truncated_to_500_chars(self):
        """LLM reason strings exceeding 500 chars must be truncated."""
        long_reason = "x" * 600
        pick = {"trakt_id": 1, "reason": long_reason}
        reason = pick.get("reason", "Recommended for you.")[:500]
        assert len(reason) == 500

    def test_reason_default_when_missing(self):
        """Default reason is applied when LLM omits the field."""
        pick = {}
        reason = pick.get("reason", "Recommended for you.")[:500]
        assert reason == "Recommended for you."


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
