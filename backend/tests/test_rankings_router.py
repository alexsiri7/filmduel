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


def _make_user_movie(elo: int):
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

    def test_get_rankings_genre_filter_does_not_narrow_population(self):
        """A genre filter leaves the percentile population unfiltered."""
        user, resp, mock_elos = self._get_rankings("genre=Drama&media_type=show")

        assert resp.status_code == 200
        assert mock_elos.await_args.args[1:] == (user.id, "show")
        assert not mock_elos.await_args.kwargs
