"""Tests for expand_pool service — pool expansion with Trakt/TMDB sources."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.expand import EXPANSION_COOLDOWN, _expand_pool_inner


def _mock_session_factory(db):
    """Create a context manager that yields the given db mock."""
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=db)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _make_user(user_id=None):
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.trakt_access_token = "fake-token"
    user.trakt_user_id = "testuser"
    return user


class TestExpandPoolInner:
    @pytest.mark.asyncio
    async def test_happy_path_calls_recommendations_source(self):
        """expand_pool should call Trakt recommendations and upsert films."""
        user_id = uuid.uuid4()
        user = _make_user(user_id)
        db = AsyncMock()

        # Mock recent expansions query (empty = no cooldowns)
        recent_result = MagicMock()
        recent_result.all.return_value = []

        # Mock Movie lookup after upsert
        movie_uuid = uuid.uuid4()
        movie_lookup = MagicMock()
        movie_lookup.scalar_one_or_none.return_value = movie_uuid

        # Mock user_movie insert
        insert_result = MagicMock()
        insert_result.rowcount = 1

        call_idx = 0

        async def fake_execute(stmt):
            nonlocal call_idx
            call_idx += 1
            result = MagicMock()
            stmt_str = str(stmt)
            if "pool_expansion" in stmt_str.lower() or call_idx == 1:
                result.all.return_value = []
                return result
            if "movie" in stmt_str.lower() and "select" in stmt_str.lower():
                result.scalar_one_or_none.return_value = movie_uuid
                return result
            result.rowcount = 1
            return result

        db.execute = fake_execute
        db.get = AsyncMock(return_value=user)

        fake_recs = [
            {"ids": {"trakt": 101, "imdb": "tt001"}, "title": "Rec Film", "year": 2024}
        ]
        trakt_mock = AsyncMock()
        trakt_mock.get_recommendations.return_value = fake_recs

        with (
            patch("backend.services.expand.async_session_factory", return_value=_mock_session_factory(db)),
            patch("backend.services.expand.TraktClient", return_value=trakt_mock),
            patch("backend.services.expand.get_settings") as mock_settings,
            patch("backend.services.expand.backfill_posters", new_callable=AsyncMock),
        ):
            mock_settings.return_value = MagicMock(
                TRAKT_CLIENT_ID="fake", TMDB_API_KEY=""
            )
            result = await _expand_pool_inner(user_id, "movie")

        assert result >= 0
        trakt_mock.get_recommendations.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cooldown_skips_source(self):
        """Source with recent expansion within cooldown should be skipped."""
        user_id = uuid.uuid4()
        user = _make_user(user_id)
        db = AsyncMock()

        # Return recent expansion that covers all sources
        recent_result = MagicMock()
        recent_row = MagicMock()
        recent_row.source = "trakt_recommendations"
        recent_row.source_key = "movie_default"
        recent_result.all.return_value = [recent_row]

        call_idx = 0

        async def fake_execute(stmt):
            nonlocal call_idx
            call_idx += 1
            result = MagicMock()
            if call_idx == 1:
                result.all.return_value = [recent_row]
                return result
            result.all.return_value = []
            result.scalar_one_or_none.return_value = None
            result.rowcount = 0
            return result

        db.execute = fake_execute
        db.get = AsyncMock(return_value=user)

        trakt_mock = AsyncMock()
        trakt_mock.get_recommendations.return_value = []

        with (
            patch("backend.services.expand.async_session_factory", return_value=_mock_session_factory(db)),
            patch("backend.services.expand.TraktClient", return_value=trakt_mock),
            patch("backend.services.expand.get_settings") as mock_settings,
            patch("backend.services.expand.backfill_posters", new_callable=AsyncMock),
        ):
            mock_settings.return_value = MagicMock(
                TRAKT_CLIENT_ID="fake", TMDB_API_KEY=""
            )
            await _expand_pool_inner(user_id, "movie")

        # Recommendations should NOT be called (cooldown active)
        trakt_mock.get_recommendations.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_zero_when_user_not_found(self):
        """Should return 0 when user doesn't exist."""
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)

        with (
            patch("backend.services.expand.async_session_factory", return_value=_mock_session_factory(db)),
            patch("backend.services.expand.get_settings") as mock_settings,
        ):
            mock_settings.return_value = MagicMock(TRAKT_CLIENT_ID="fake")
            result = await _expand_pool_inner(uuid.uuid4(), "movie")

        assert result == 0
