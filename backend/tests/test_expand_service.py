"""Tests for expand_pool service — pool expansion with Trakt/TMDB sources."""

from __future__ import annotations

import functools
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.services.expand import _expand_from_similar, _expand_pool_inner

TMDB_READ_ACCESS_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiJ0ZXN0In0.sig"


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

        async def fake_execute(stmt):
            result = MagicMock()
            stmt_str = str(stmt)
            if "pool_expansion" in stmt_str.lower():
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
            patch(
                "backend.services.expand.async_session_factory",
                return_value=_mock_session_factory(db),
            ),
            patch("backend.services.expand.TraktClient", return_value=trakt_mock),
            patch("backend.services.expand.get_settings") as mock_settings,
            patch("backend.services.expand.backfill_posters", new_callable=AsyncMock),
        ):
            mock_settings.return_value = MagicMock(
                TRAKT_CLIENT_ID="fake", TMDB_API_KEY=""
            )
            result = await _expand_pool_inner(user_id, "movie")

        assert result == 1
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
            patch(
                "backend.services.expand.async_session_factory",
                return_value=_mock_session_factory(db),
            ),
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
            patch(
                "backend.services.expand.async_session_factory",
                return_value=_mock_session_factory(db),
            ),
            patch("backend.services.expand.get_settings") as mock_settings,
        ):
            mock_settings.return_value = MagicMock(TRAKT_CLIENT_ID="fake")
            result = await _expand_pool_inner(uuid.uuid4(), "movie")

        assert result == 0


class TestExpandFromSimilar:
    @pytest.mark.asyncio
    async def test_calls_real_fetch_similar_films_with_tmdb_id_only(self):
        """Source B must reach TMDB through the real fetch_similar_films.

        Only the HTTP transport is mocked, so this exercises the call site's
        arity against the real one-argument signature; a reintroduced second
        parameter raises TypeError here instead of being swallowed by
        expand_pool's catch-all.
        """
        user_id = uuid.uuid4()
        settings = MagicMock(TMDB_API_KEY=TMDB_READ_ACCESS_TOKEN)
        now = datetime.now(timezone.utc)

        top_row = MagicMock()
        top_row.movie_id = uuid.uuid4()
        top_row.tmdb_id = 42
        top_result = MagicMock()
        top_result.all.return_value = [top_row]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=top_result)
        db.add = MagicMock()

        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": 5,
                            "title": "Rec",
                            "release_date": "2020-01-01",
                            "overview": "o",
                            "genre_ids": [28],
                        }
                    ]
                },
            )

        transport = httpx.MockTransport(handler)
        upsert = AsyncMock(return_value=True)

        with (
            patch("backend.services.tmdb.get_settings", return_value=settings),
            patch(
                "httpx.AsyncClient",
                functools.partial(httpx.AsyncClient, transport=transport),
            ),
            patch("backend.services.expand._upsert_film_from_tmdb", upsert),
            patch("backend.services.expand.asyncio.sleep", new_callable=AsyncMock),
        ):
            added = await _expand_from_similar(db, user_id, settings, set(), now)

        assert added == 1
        assert len(requests) == 1
        assert (
            str(requests[0].url)
            == "https://api.themoviedb.org/3/movie/42/recommendations"
        )
        upsert.assert_awaited_once()
        film = upsert.await_args.args[2]
        assert film["tmdb_id"] == 5
        assert film["genres"] == ["action"]
