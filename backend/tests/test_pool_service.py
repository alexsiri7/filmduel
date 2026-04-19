"""Tests for populate_movie_pool core flow."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.pool import SYNC_COOLDOWN, populate_movie_pool


def _make_user(last_seen_at=None):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.trakt_user_id = "testuser"
    user.trakt_username = "testuser"
    user.trakt_access_token = "fake-token"
    user.last_seen_at = last_seen_at
    return user


class TestPopulateMoviePool:
    @pytest.mark.asyncio
    async def test_fetches_and_upserts_from_trakt(self):
        """populate_movie_pool calls Trakt APIs and upserts films."""
        user = _make_user(last_seen_at=None)
        db = AsyncMock()

        fake_popular = [
            {
                "ids": {"trakt": 1, "imdb": "tt001", "tmdb": 100},
                "title": "Pop Film",
                "year": 2024,
                "genres": ["Drama"],
                "rating": 7.5,
            }
        ]
        fake_watched = [
            {
                "ids": {"trakt": 2, "imdb": "tt002", "tmdb": 200},
                "title": "Watched Film",
                "year": 2023,
                "genres": ["Action"],
            }
        ]

        trakt_mock = AsyncMock()
        trakt_mock.get_popular.return_value = fake_popular
        trakt_mock.get_trending.return_value = []
        trakt_mock.get_recommendations.return_value = []
        trakt_mock.get_user_watched.return_value = fake_watched
        trakt_mock.get_user_ratings.return_value = []
        # The unified methods accept media_type param; AsyncMock handles that automatically

        # Mock the DB execute for movie upserts and UUID lookups
        movie_uuid_1 = uuid.uuid4()
        movie_uuid_2 = uuid.uuid4()

        exec_count = 0

        async def fake_execute(stmt):
            nonlocal exec_count
            exec_count += 1
            result = MagicMock()
            # After upserts, the UUID lookup returns movie UUIDs
            result.all.return_value = [
                MagicMock(id=movie_uuid_1, trakt_id=1),
                MagicMock(id=movie_uuid_2, trakt_id=2),
            ]
            result.rowcount = 1
            return result

        db.execute = fake_execute

        with (
            patch("backend.services.pool.TraktClient", return_value=trakt_mock),
            patch("backend.services.pool.get_settings") as mock_settings,
        ):
            mock_settings.return_value = MagicMock(TRAKT_CLIENT_ID="fake")
            await populate_movie_pool(user, db)

        # Each method is called twice: once for movie, once for show
        assert trakt_mock.get_popular.await_count == 2
        assert trakt_mock.get_user_watched.await_count == 2
        # last_seen_at should be updated
        assert user.last_seen_at is not None

    @pytest.mark.asyncio
    async def test_cooldown_skips_sync(self):
        """Should skip sync when last_seen_at is within cooldown."""
        recent_time = datetime.now(timezone.utc) - timedelta(minutes=30)
        user = _make_user(last_seen_at=recent_time)
        db = AsyncMock()

        await populate_movie_pool(user, db)

        # No DB execute calls since we skipped
        db.execute.assert_not_awaited()
