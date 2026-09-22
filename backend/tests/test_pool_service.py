"""Tests for populate_movie_pool core flow."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.sql import Select
from sqlalchemy.sql.dml import Insert, Update

from sqlalchemy import Column

from backend.services.pool import (
    populate_movie_pool,
    build_movie_upsert,
    _upsert_pool,
    _upsert_simkl_pool,
    _upsert_user_movie,
)


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


class TestBuildMovieUpsertSimkl:
    """Tests for build_movie_upsert with simkl_id parameter."""

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
        """build_movie_upsert with simkl_id sets simkl_id and trakt_id to the SIMKL numeric ID."""
        now = datetime.now(timezone.utc)
        movie_data = self._make_movie_data(simkl_id=42)
        stmt = build_movie_upsert(movie_data, now, media_type="movie", simkl_id=42)
        params = stmt.compile().params
        assert params["trakt_id"] == 42
        assert params["simkl_id"] == 42

    def test_imdb_id_propagated(self):
        """build_movie_upsert with simkl_id preserves imdb_id in values."""
        now = datetime.now(timezone.utc)
        movie_data = self._make_movie_data(imdb_id="tt9876543")
        stmt = build_movie_upsert(movie_data, now, media_type="movie", simkl_id=12345)
        params = stmt.compile().params
        assert params["imdb_id"] == "tt9876543"

    def test_missing_simkl_id_defaults_to_zero(self):
        """If simkl_id=0, trakt_id defaults to 0."""
        now = datetime.now(timezone.utc)
        movie_data = {"title": "No ID Film", "ids": {}}
        stmt = build_movie_upsert(movie_data, now, media_type="movie", simkl_id=0)
        params = stmt.compile().params
        assert params["trakt_id"] == 0
        assert params["simkl_id"] == 0

    def test_media_type_stored(self):
        """build_movie_upsert with simkl_id stores the correct media_type."""
        now = datetime.now(timezone.utc)
        movie_data = self._make_movie_data()
        stmt = build_movie_upsert(movie_data, now, media_type="show", simkl_id=12345)
        params = stmt.compile().params
        assert params["media_type"] == "show"


# ---------------------------------------------------------------------------
# _safe_fetch — silent failure handling
# ---------------------------------------------------------------------------


class TestSafeFetch:
    @pytest.mark.asyncio
    async def test_safe_fetch_returns_empty_on_api_exception(self):
        """_safe_fetch returns [] when the underlying coroutine raises."""
        from backend.services.pool import _safe_fetch

        async def failing_coro():
            raise RuntimeError("API timeout")

        result = await _safe_fetch(failing_coro)
        assert result == []

    @pytest.mark.asyncio
    async def test_safe_fetch_returns_data_on_success(self):
        """_safe_fetch returns the coroutine result on success."""
        from backend.services.pool import _safe_fetch

        async def succeeding_coro():
            return [{"id": 1}, {"id": 2}]

        result = await _safe_fetch(succeeding_coro)
        assert result == [{"id": 1}, {"id": 2}]

    @pytest.mark.asyncio
    async def test_partial_provider_failure_continues_other(self):
        """When Trakt fails, SIMKL data should still be populated."""
        user = _make_user(last_seen_at=None)
        # Remove SIMKL-related attrs to focus test on Trakt failure path
        user.simkl_access_token = None
        user.simkl_access_token_enc = None
        db = AsyncMock()

        exec_count = 0

        async def fake_execute(stmt):
            nonlocal exec_count
            exec_count += 1
            result = MagicMock()
            result.all.return_value = []
            result.rowcount = 0
            return result

        db.execute = fake_execute

        trakt_mock = AsyncMock()
        # Trakt popular fails
        trakt_mock.get_popular.side_effect = RuntimeError("Trakt down")
        trakt_mock.get_trending.side_effect = RuntimeError("Trakt down")
        trakt_mock.get_recommendations.side_effect = RuntimeError("Trakt down")
        # Watched and ratings work
        trakt_mock.get_user_watched.return_value = []
        trakt_mock.get_user_ratings.return_value = []

        with (
            patch("backend.services.pool.TraktClient", return_value=trakt_mock),
            patch("backend.services.pool.get_settings") as mock_settings,
        ):
            mock_settings.return_value = MagicMock(TRAKT_CLIENT_ID="fake")
            # Should not raise — _safe_fetch swallows the errors
            await populate_movie_pool(user, db)

        # last_seen_at should still be updated (sync completed)
        assert user.last_seen_at is not None


# ---------------------------------------------------------------------------
# _upsert_simkl_pool — cross-provider catalog dedup (FD-053)
# ---------------------------------------------------------------------------


class TestUpsertSimklPool:
    """Tests for _upsert_simkl_pool's imdb cross-reference against existing rows."""

    def _fake_db(self, existing_rows):
        """AsyncMock session recording every statement; SELECTs return existing_rows."""
        stmts = []

        async def fake_execute(stmt):
            stmts.append(stmt)
            result = MagicMock()
            result.all.return_value = existing_rows if isinstance(stmt, Select) else []
            return result

        db = AsyncMock()
        db.execute = fake_execute
        return db, stmts

    def _inserts_into(self, stmts, table_name):
        return [s for s in stmts if isinstance(s, Insert) and s.table.name == table_name]

    def _updates_of(self, stmts, table_name):
        return [s for s in stmts if isinstance(s, Update) and s.table.name == table_name]

    @pytest.mark.asyncio
    async def test_matches_existing_trakt_row_by_imdb_and_backfills_simkl_id(self):
        """A SIMKL title matching an existing row by imdb_id reuses that row instead of inserting."""
        existing_id = uuid.uuid4()
        existing = MagicMock(id=existing_id, trakt_id=555, imdb_id="tt0111161")
        db, stmts = self._fake_db([existing])

        pool = {
            900: {
                "ids": {"simkl": 900, "imdb": "tt0111161", "tmdb": 278},
                "title": "Shawshank",
            }
        }

        await _upsert_simkl_pool(
            db, _make_user(), pool, set(), {}, "movie", datetime.now(timezone.utc)
        )

        assert self._inserts_into(stmts, "movies") == []

        updates = self._updates_of(stmts, "movies")
        assert len(updates) == 1
        params = updates[0].compile().params
        assert params["simkl_id"] == 900
        assert params["id_1"] == existing_id

        user_movie_inserts = self._inserts_into(stmts, "user_movies")
        assert len(user_movie_inserts) == 1
        assert user_movie_inserts[0].compile().params["movie_id"] == existing_id

    @pytest.mark.asyncio
    async def test_unmatched_simkl_title_inserts_with_simkl_id_in_both_columns(self):
        """A SIMKL title with no imdb match is inserted with the SIMKL id in trakt_id and simkl_id."""
        db, stmts = self._fake_db([])

        pool = {
            901: {
                "ids": {"simkl": 901, "imdb": "tt9999999", "tmdb": 1},
                "title": "New",
            }
        }

        await _upsert_simkl_pool(
            db, _make_user(), pool, set(), {}, "movie", datetime.now(timezone.utc)
        )

        assert self._updates_of(stmts, "movies") == []

        inserts = self._inserts_into(stmts, "movies")
        assert len(inserts) == 1
        params = inserts[0].compile().params
        assert params["trakt_id"] == 901
        assert params["simkl_id"] == 901
        assert params["imdb_id"] == "tt9999999"


# ---------------------------------------------------------------------------
# _upsert_user_movie — conflict resolution must never clobber good data
#
# There is no real database fixture anywhere in this test suite (every test
# here mocks AsyncSession.execute and inspects the compiled statement); a
# live Postgres is not available in CI either. So "behavior" is verified at
# the same boundary as the rest of the file: the exact SQL contract sent to
# Postgres. _upsert_user_movie decides in Python (not in the ON CONFLICT
# clause) whether to preserve or overwrite each column, so inspecting the
# compiled statement's on-conflict SET clause is a faithful proxy for what a
# real conflicting row would end up with.
# ---------------------------------------------------------------------------


class TestUpsertUserMovie:
    def _fake_db(self):
        captured = []

        async def fake_execute(stmt):
            captured.append(stmt)
            return None

        db = AsyncMock()
        db.execute = fake_execute
        return db, captured

    def _conflict_set_map(self, stmt):
        """The ON CONFLICT DO UPDATE SET clause as {column_name: value_or_column}."""
        return dict(stmt._post_values_clause.update_values_to_set)

    @pytest.mark.asyncio
    async def test_none_seen_and_rating_preserve_existing_row_on_conflict(self):
        """Re-upserting with seen=None, rating=None must not clobber a previously seeded row."""
        db, captured = self._fake_db()
        now = datetime.now(timezone.utc)
        user_id, movie_id = uuid.uuid4(), uuid.uuid4()

        await _upsert_user_movie(db, user_id, movie_id, True, 8, now)
        await _upsert_user_movie(db, user_id, movie_id, None, None, now)

        seeded = captured[0].compile().params
        assert seeded["seen"] is True
        assert seeded["seeded_elo"] is not None
        assert seeded["trakt_rating"] == 8

        set_map = self._conflict_set_map(captured[1])
        # A Column reference (e.g. `seen = user_movies.seen`) means "keep whatever is
        # already there" — the opposite would silently overwrite good data with NULL.
        assert isinstance(set_map["seen"], Column)
        assert isinstance(set_map["seeded_elo"], Column)
        assert isinstance(set_map["trakt_rating"], Column)
        assert set_map["updated_at"] == now

    @pytest.mark.asyncio
    async def test_seen_and_rating_provided_populate_a_previously_blank_row(self):
        """Re-upserting with seen=True, rating=7 fills in a row that started with no data."""
        db, captured = self._fake_db()
        now = datetime.now(timezone.utc)
        user_id, movie_id = uuid.uuid4(), uuid.uuid4()

        await _upsert_user_movie(db, user_id, movie_id, None, None, now)
        await _upsert_user_movie(db, user_id, movie_id, True, 7, now)

        blank = captured[0].compile().params
        assert blank["seen"] is None
        assert blank["seeded_elo"] is None
        assert blank["trakt_rating"] is None

        set_map = self._conflict_set_map(captured[1])
        assert set_map["seen"] is True
        assert set_map["seeded_elo"] is not None
        assert set_map["trakt_rating"] == 7


# ---------------------------------------------------------------------------
# _upsert_pool — unmapped trakt_ids must not fail the whole batch
# ---------------------------------------------------------------------------


class TestUpsertPoolUnmappedTraktId:
    @pytest.mark.asyncio
    async def test_unmapped_trakt_id_is_skipped_without_raising(self):
        """A trakt_id with no matching movies row (e.g. excluded by a media_type mismatch
        in the WHERE clause) is skipped instead of raising, and the rest of the batch
        still completes."""
        mapped_movie_id = uuid.uuid4()
        stmts = []

        async def fake_execute(stmt):
            stmts.append(stmt)
            result = MagicMock()
            if isinstance(stmt, Select):
                # Only trakt_id 1 resolves to a movies row; trakt_id 2 has no match.
                row = MagicMock()
                row.trakt_id = 1
                row.id = mapped_movie_id
                result.all.return_value = [row]
            return result

        db = AsyncMock()
        db.execute = fake_execute

        pool = {
            1: {"ids": {"trakt": 1}, "title": "Seen Film"},
            2: {"ids": {"trakt": 2}, "title": "Unseen Film"},
        }

        await _upsert_pool(
            db,
            _make_user(),
            pool,
            seen_trakt_ids={1},
            ratings_by_trakt_id={},
            media_type="movie",
            now=datetime.now(timezone.utc),
        )

        user_movie_inserts = [
            s for s in stmts if isinstance(s, Insert) and s.table.name == "user_movies"
        ]
        assert len(user_movie_inserts) == 1
        params = user_movie_inserts[0].compile().params
        assert params["movie_id"] == mapped_movie_id
        assert params["seen"] is True

    @pytest.mark.asyncio
    async def test_unmapped_unseen_trakt_id_is_skipped_without_raising(self):
        """Same as above but for an unseen trakt_id, to cover both seen-flag branches."""
        mapped_movie_id = uuid.uuid4()
        stmts = []

        async def fake_execute(stmt):
            stmts.append(stmt)
            result = MagicMock()
            if isinstance(stmt, Select):
                row = MagicMock()
                row.trakt_id = 2
                row.id = mapped_movie_id
                result.all.return_value = [row]
            return result

        db = AsyncMock()
        db.execute = fake_execute

        pool = {
            1: {"ids": {"trakt": 1}, "title": "Unmapped Film"},
            2: {"ids": {"trakt": 2}, "title": "Mapped Unseen Film"},
        }

        await _upsert_pool(
            db,
            _make_user(),
            pool,
            seen_trakt_ids=set(),
            ratings_by_trakt_id={},
            media_type="movie",
            now=datetime.now(timezone.utc),
        )

        user_movie_inserts = [
            s for s in stmts if isinstance(s, Insert) and s.table.name == "user_movies"
        ]
        assert len(user_movie_inserts) == 1
        params = user_movie_inserts[0].compile().params
        assert params["movie_id"] == mapped_movie_id
        assert params["seen"] is None


# ---------------------------------------------------------------------------
# populate_movie_pool — partial provider failure, SIMKL-down direction
# (mirrors TestSafeFetch.test_partial_provider_failure_continues_other, which
# only covers the Trakt-down direction)
# ---------------------------------------------------------------------------


class TestPartialProviderFailureSimklDown:
    @pytest.mark.asyncio
    async def test_simkl_failure_still_populates_trakt_movies(self):
        """When SIMKL fails, Trakt-sourced movies should still be upserted."""
        user = _make_user(last_seen_at=None)
        user.simkl_user_id = "simkluser"
        user.simkl_access_token = "fake-simkl-token"
        db = AsyncMock()

        stmts = []

        async def fake_execute(stmt):
            stmts.append(stmt)
            result = MagicMock()
            result.all.return_value = []
            result.rowcount = 0
            return result

        db.execute = fake_execute

        trakt_mock = AsyncMock()
        trakt_mock.get_popular.return_value = [
            {"ids": {"trakt": 1, "imdb": "tt001"}, "title": "Trakt Film", "year": 2024}
        ]
        trakt_mock.get_trending.return_value = []
        trakt_mock.get_recommendations.return_value = []
        trakt_mock.get_user_watched.return_value = []
        trakt_mock.get_user_ratings.return_value = []

        simkl_mock = AsyncMock()
        simkl_mock.get_popular.side_effect = RuntimeError("SIMKL down")
        simkl_mock.get_trending.side_effect = RuntimeError("SIMKL down")
        simkl_mock.get_user_watched.side_effect = RuntimeError("SIMKL down")
        simkl_mock.get_user_ratings.side_effect = RuntimeError("SIMKL down")

        with (
            patch("backend.services.pool.TraktClient", return_value=trakt_mock),
            patch("backend.services.pool.SimklClient", return_value=simkl_mock),
            patch("backend.services.pool.get_settings") as mock_settings,
        ):
            mock_settings.return_value = MagicMock(TRAKT_CLIENT_ID="fake", SIMKL_CLIENT_ID="fake")
            # Should not raise — _safe_fetch swallows the SIMKL errors
            await populate_movie_pool(user, db)

        movie_inserts = [s for s in stmts if isinstance(s, Insert) and s.table.name == "movies"]
        assert any(i.compile().params.get("trakt_id") == 1 for i in movie_inserts)
        assert user.last_seen_at is not None
