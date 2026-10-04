"""Tests for rankings router — auth, validation, CSV export."""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("TOKEN_ENC_KEY", "test-secret-key-for-unit-tests-32b")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests!!")

from fastapi.testclient import TestClient

from backend.main import app
from backend.db import get_db
from backend.routers.auth import get_current_user


def _make_user():
    user = MagicMock()
    user.id = uuid.uuid4()
    return user


def _make_user_movie(elo: float):
    um = MagicMock()
    um.elo = elo
    um.battles = 3
    um.movie = MagicMock(
        id=uuid.uuid4(),
        trakt_id=1,
        tmdb_id=1,
        imdb_id="tt0000001",
        title=f"Film {elo}",
        year=2000,
        poster_url=None,
        overview=None,
        genres=["Drama"],
        media_type="show",
    )
    return um


class TestRankingsRouter:
    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_get_rankings_requires_auth(self):
        """GET /api/rankings without auth returns 401."""
        # No dependency overrides — the real get_current_user will reject
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/rankings")

        assert resp.status_code == 401

    def test_get_rankings_invalid_decade_returns_400(self):
        """GET /api/rankings?decade=abc returns 400 for invalid decade."""
        user = _make_user()
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: AsyncMock()

        with patch(
            "backend.routers.rankings.get_user_rankings",
            new_callable=AsyncMock,
            side_effect=ValueError("Invalid decade format"),
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/api/rankings?decade=abc")

        assert resp.status_code == 400
        assert "decade" in resp.json()["detail"].lower()

    def test_get_rankings_out_of_range_decade_returns_400(self):
        """An integer-parsable but unbounded decade is rejected before the DB."""
        user = _make_user()
        app.dependency_overrides[get_current_user] = lambda: user
        db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: db

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/rankings?decade=99999999999s")

        assert resp.status_code == 400
        db.execute.assert_not_awaited()

    def test_get_rankings_non_positive_limit_returns_422(self):
        """limit below 1 is rejected by validation instead of reaching SQL LIMIT."""
        user = _make_user()
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: AsyncMock()

        with patch(
            "backend.routers.rankings.get_user_rankings", new_callable=AsyncMock
        ) as mock_rankings:
            with TestClient(app, raise_server_exceptions=False) as client:
                negative = client.get("/api/rankings?limit=-1")
                zero = client.get("/api/rankings?limit=0")

        assert negative.status_code == 422
        assert zero.status_code == 422
        mock_rankings.assert_not_awaited()

    def test_export_csv_headers(self):
        """GET /api/rankings/export/csv returns correct Content-Type and filename."""
        user = _make_user()
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: AsyncMock()

        csv_content = "Title,Year,Rating\nInception,2010,10\n"

        with patch(
            "backend.routers.rankings.export_rankings_csv",
            new_callable=AsyncMock,
            return_value=csv_content,
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/api/rankings/export/csv")

        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        assert "filmduel_rankings.csv" in resp.headers["content-disposition"]
        assert resp.text == csv_content

    def _get_rankings(self, query: str):
        user = _make_user()
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: AsyncMock()
        with (
            patch(
                "backend.routers.rankings.get_user_rankings",
                new_callable=AsyncMock,
                return_value=([_make_user_movie(1100), _make_user_movie(900)], 2),
            ),
            patch(
                "backend.routers.rankings.get_ranked_elos",
                new_callable=AsyncMock,
                return_value=[900, 1100],
            ) as mock_elos,
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get(f"/api/rankings?{query}")
        return user, resp, mock_elos

    def test_get_rankings_rates_by_percentile_of_media_type(self):
        """trakt_rating is each film's percentile within the user's ranked ELOs."""
        user, resp, mock_elos = self._get_rankings("media_type=show")

        assert resp.status_code == 200
        assert [r["trakt_rating"] for r in resp.json()["rankings"]] == [8, 3]
        mock_elos.assert_awaited_once()
        assert mock_elos.await_args.args[1:] == (user.id, "show")

    def test_get_rankings_rounds_elo_but_rates_the_unrounded_value(self):
        user = _make_user()
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: AsyncMock()
        with (
            patch(
                "backend.routers.rankings.get_user_rankings",
                new_callable=AsyncMock,
                return_value=([_make_user_movie(1016.6)], 1),
            ),
            patch(
                "backend.routers.rankings.get_ranked_elos",
                new_callable=AsyncMock,
                return_value=[1016.6, 1017.4],
            ),
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/api/rankings")

        assert resp.status_code == 200
        (ranked,) = resp.json()["rankings"]
        assert ranked["elo"] == 1017
        # Rating the rounded 1017 would place it between the two films: a 5.
        assert ranked["trakt_rating"] == 3

    def test_get_rankings_genre_filter_does_not_narrow_population(self):
        """A genre filter leaves the percentile population unfiltered."""
        user, resp, mock_elos = self._get_rankings("genre=Drama&media_type=show")

        assert resp.status_code == 200
        assert mock_elos.await_args.args[1:] == (user.id, "show")
        assert not mock_elos.await_args.kwargs

    def test_get_stats_rates_highest_and_lowest_by_percentile(self):
        """Stats rate the highest and lowest films against the media_type population."""
        user = _make_user()
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: AsyncMock()
        stats = {
            "total_duels": 5,
            "total_movies_ranked": 3,
            "unseen_count": 0,
            "average_elo": 1000.0,
            "highest_rated": _make_user_movie(1100),
            "lowest_rated": _make_user_movie(900),
        }
        with (
            patch(
                "backend.routers.rankings.get_user_stats",
                new_callable=AsyncMock,
                return_value=stats,
            ),
            patch(
                "backend.routers.rankings.get_ranked_elos",
                new_callable=AsyncMock,
                return_value=[900, 1000, 1100],
            ) as mock_elos,
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/api/rankings/stats?media_type=show")

        assert resp.status_code == 200
        body = resp.json()
        assert body["highest_rated"]["trakt_rating"] == 9
        assert body["lowest_rated"]["trakt_rating"] == 2
        mock_elos.assert_awaited_once()
        assert mock_elos.await_args.args[1:] == (user.id, "show")
