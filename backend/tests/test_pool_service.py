"""Tests for populate_movie_pool core flow."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.pool import populate_movie_pool, build_simkl_movie_upsert


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


class TestBuildSimklMovieUpsert:
    """Tests for the build_simkl_movie_upsert helper."""

    def _make_movie_data(self, simkl_id=12345, imdb_id="tt0000001", tmdb_id=999):
        return {
            "title": "Test Film",
            "year": 2024,
            "ids": {
                "simkl": simkl_id,
                "imdb": imdb_id,
                "tmdb": tmdb_id,
            },
            "genres": ["Drama"],
            "overview": "A test film.",
            "runtime": 120,
        }

    def test_stores_simkl_id_in_both_columns(self):
        """build_simkl_movie_upsert sets simkl_id and trakt_id to the SIMKL numeric ID."""
        now = datetime.now(timezone.utc)
        movie_data = self._make_movie_data(simkl_id=42)
        stmt = build_simkl_movie_upsert(movie_data, now, media_type="movie")
        # The statement's compiled values should contain both trakt_id and simkl_id
        params = stmt.compile().params
        assert params["trakt_id"] == 42
        assert params["simkl_id"] == 42

    def test_imdb_id_propagated(self):
        """build_simkl_movie_upsert preserves imdb_id in values."""
        now = datetime.now(timezone.utc)
        movie_data = self._make_movie_data(imdb_id="tt9876543")
        stmt = build_simkl_movie_upsert(movie_data, now, media_type="movie")
        params = stmt.compile().params
        assert params["imdb_id"] == "tt9876543"

    def test_missing_simkl_id_defaults_to_zero(self):
        """If SIMKL ID is absent from ids, trakt_id defaults to 0."""
        now = datetime.now(timezone.utc)
        movie_data = {"title": "No ID Film", "ids": {}}
        stmt = build_simkl_movie_upsert(movie_data, now, media_type="movie")
        params = stmt.compile().params
        assert params["trakt_id"] == 0
        assert params["simkl_id"] == 0

    def test_media_type_stored(self):
        """build_simkl_movie_upsert stores the correct media_type."""
        now = datetime.now(timezone.utc)
        movie_data = self._make_movie_data()
        stmt = build_simkl_movie_upsert(movie_data, now, media_type="show")
        params = stmt.compile().params
        assert params["media_type"] == "show"
