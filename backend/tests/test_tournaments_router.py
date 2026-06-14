"""Tests for tournaments router — daily cap, consent, ownership isolation."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("TOKEN_ENC_KEY", "test-secret-key-for-unit-tests-32b")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests!!")

from fastapi.testclient import TestClient

from backend.main import app
from backend.db import get_db
from backend.routers.auth import get_current_user


def _make_user(*, privacy_policy_accepted: bool = True):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.privacy_policy_accepted = privacy_policy_accepted
    return user


def _make_tournament(user_id, **overrides):
    """Build a mock Tournament with sensible defaults."""
    t = MagicMock()
    t.id = overrides.get("id", uuid.uuid4())
    t.user_id = user_id
    t.name = overrides.get("name", "Test Tournament")
    t.filter_type = overrides.get("filter_type", None)
    t.filter_value = overrides.get("filter_value", None)
    t.bracket_size = overrides.get("bracket_size", 8)
    t.status = overrides.get("status", "active")
    t.champion_movie_id = overrides.get("champion_movie_id", None)
    t.tagline = overrides.get("tagline", None)
    t.theme_description = overrides.get("theme_description", None)
    t.is_ai_curated = overrides.get("is_ai_curated", False)
    t.created_at = overrides.get("created_at", datetime.now(timezone.utc))
    t.completed_at = overrides.get("completed_at", None)
    t.matches = overrides.get("matches", [])
    return t


# ---------------------------------------------------------------------------
# Item 8: daily cap (security regression guard for commit #343)
# ---------------------------------------------------------------------------


class TestCreateTournamentDailyCap:
    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_create_tournament_enforces_daily_cap_at_100(self):
        """POST /api/tournaments returns 429 when 100 tournaments created in 24h."""
        user = _make_user(privacy_policy_accepted=False)
        mock_db = AsyncMock()

        # Mock count query to return 100 (at daily cap)
        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 100
        mock_db.execute.return_value = mock_count_result

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: mock_db

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/tournaments",
                json={"bracket_size": 8, "ai_curated": False},
            )

        assert resp.status_code == 429
        assert "Daily tournament creation limit" in resp.json()["detail"]

    def test_create_tournament_ai_curated_requires_consent(self):
        """POST /api/tournaments with ai_curated=True returns 403 without consent."""
        user = _make_user(privacy_policy_accepted=False)
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: AsyncMock()

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/tournaments",
                json={"bracket_size": 8, "ai_curated": True},
            )

        assert resp.status_code == 403
        assert "consent" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Item 9: ownership isolation
# ---------------------------------------------------------------------------


class TestTournamentOwnership:
    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_load_tournament_returns_404_for_other_user(self):
        """GET /api/tournaments/{id} returns 404 when tournament belongs to another user."""
        user_a = _make_user()
        user_b = _make_user()
        tournament_id = uuid.uuid4()

        mock_db = AsyncMock()
        # Mock the query to return a tournament owned by user_a
        mock_tournament = MagicMock()
        mock_tournament.id = tournament_id
        mock_tournament.user_id = user_a.id

        mock_result = MagicMock()
        mock_result.unique.return_value.scalars.return_value.first.return_value = (
            mock_tournament
        )
        mock_db.execute.return_value = mock_result

        # Request as user_b
        app.dependency_overrides[get_current_user] = lambda: user_b
        app.dependency_overrides[get_db] = lambda: mock_db

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(f"/api/tournaments/{tournament_id}")

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_get_tournament_returns_bracket_data(self):
        """GET /api/tournaments/{id} returns matches array in response."""
        user = _make_user()
        tournament_id = uuid.uuid4()

        def _mock_movie(title, trakt_id):
            m = MagicMock()
            m.id = uuid.uuid4()
            m.title = title
            m.year = 2020
            m.trakt_id = trakt_id
            m.imdb_id = f"tt{trakt_id:07d}"
            m.tmdb_id = trakt_id * 100
            m.poster_url = f"http://example.com/{trakt_id}.jpg"
            m.genres = ["Drama"]
            m.media_type = "movie"
            m.overview = None
            return m

        mock_match = MagicMock()
        mock_match.id = uuid.uuid4()
        mock_match.round = 1
        mock_match.position = 0
        mock_match.movie_a = _mock_movie("Film A", 1)
        mock_match.movie_b = _mock_movie("Film B", 2)
        mock_match.winner_movie_id = None
        mock_match.is_bye = False
        mock_match.played_at = None

        mock_tournament = _make_tournament(
            user.id, id=tournament_id, matches=[mock_match]
        )

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: AsyncMock()

        with patch(
            "backend.routers.tournaments._load_tournament",
            new_callable=AsyncMock,
            return_value=mock_tournament,
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get(f"/api/tournaments/{tournament_id}")

        assert resp.status_code == 200
        body = resp.json()
        assert "matches" in body
        assert len(body["matches"]) == 1
        assert body["matches"][0]["round"] == 1
