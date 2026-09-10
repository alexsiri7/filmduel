"""Tests for tournaments router — daily cap, consent, listing, ownership isolation."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("TOKEN_ENC_KEY", "test-secret-key-for-unit-tests-32b")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests!!")

from backend.routers.tournaments import _active_progress

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
    t.media_type = overrides.get("media_type", "movie")
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


def _mock_bracket_match(round_num: int, position: int):
    """Create a mock TournamentMatch carrying the fields the bracket schema reads."""
    m = MagicMock()
    m.id = uuid.uuid4()
    m.round = round_num
    m.position = position
    m.movie_a = _mock_movie(f"Film r{round_num}p{position}a", round_num * 10 + position)
    m.movie_b = _mock_movie(
        f"Film r{round_num}p{position}b", round_num * 10 + position + 5
    )
    m.winner_movie_id = None
    m.is_bye = False
    m.played_at = None
    return m


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
        user_b = _make_user()
        tournament_id = uuid.uuid4()

        mock_db = AsyncMock()
        # The query filters by user_id, so when requesting another user's
        # tournament the DB returns None (no matching row).
        mock_result = MagicMock()
        mock_result.unique.return_value.scalars.return_value.first.return_value = None
        mock_db.execute.return_value = mock_result

        # Request as user_b (tournament belongs to someone else)
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

        mock_match = _mock_bracket_match(1, 0)

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

    def test_get_tournament_orders_matches_by_round_and_position(self):
        """Bracket matches come back sorted by (round, position) (FD-056)."""
        user = _make_user()
        tournament_id = uuid.uuid4()

        shuffled = [
            _mock_bracket_match(2, 1),
            _mock_bracket_match(1, 2),
            _mock_bracket_match(2, 0),
            _mock_bracket_match(1, 0),
        ]
        mock_tournament = _make_tournament(
            user.id, id=tournament_id, matches=shuffled
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
        ordering = [(m["round"], m["position"]) for m in resp.json()["matches"]]
        assert ordering == [(1, 0), (1, 2), (2, 0), (2, 1)]


# ---------------------------------------------------------------------------
# list_tournaments — scoping, ordering, cap, progress (FD-056)
# ---------------------------------------------------------------------------


class TestListTournaments:
    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    @staticmethod
    def _get_list(user, tournaments):
        """Call GET /api/tournaments with a mocked DB; return (response, statement)."""
        mock_result = MagicMock()
        mock_result.unique.return_value.scalars.return_value.all.return_value = (
            tournaments
        )
        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: mock_db

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/tournaments")

        return resp, mock_db.execute.call_args[0][0]

    def test_list_query_is_scoped_to_the_current_user(self):
        """The WHERE clause binds the requesting user's id, so no foreign row is fetched."""
        user = _make_user()
        resp, stmt = self._get_list(user, [_make_tournament(user.id)])

        assert resp.status_code == 200
        assert "WHERE tournaments.user_id = " in str(stmt)
        assert user.id in stmt.compile().params.values()

    def test_list_query_orders_newest_first_and_caps_at_100(self):
        """Ordering and the safety cap are in the SQL, not applied after fetching."""
        user = _make_user()
        resp, stmt = self._get_list(user, [])

        assert resp.status_code == 200
        assert "ORDER BY tournaments.created_at DESC" in str(stmt)
        assert 100 in stmt.compile().params.values()

    def test_list_preserves_query_row_order(self):
        """Rows reach the client in the order the query returned them."""
        user = _make_user()
        rows = [
            _make_tournament(user.id, name="Newest"),
            _make_tournament(user.id, name="Middle"),
            _make_tournament(user.id, name="Oldest"),
        ]
        resp, _ = self._get_list(user, rows)

        assert resp.status_code == 200
        assert [t["name"] for t in resp.json()] == ["Newest", "Middle", "Oldest"]

    def test_list_progress_reflects_tournament_status(self):
        """Terminal statuses get fixed labels; an active one gets a round tally."""
        user = _make_user()
        played = _mock_match(1, winner_id="w1")
        unplayed = _mock_match(1)
        rows = [
            _make_tournament(user.id, name="Done", status="completed"),
            _make_tournament(user.id, name="Gone", status="abandoned"),
            _make_tournament(
                user.id, name="Live", status="active", matches=[played, unplayed]
            ),
        ]
        resp, _ = self._get_list(user, rows)

        assert resp.status_code == 200
        progress = {t["name"]: t["progress"] for t in resp.json()}
        assert progress["Done"] == "Completed"
        assert progress["Gone"] == "Abandoned"
        assert progress["Live"] == "Round 1 \u2014 1/2 matches played"


# ---------------------------------------------------------------------------
# _active_progress unit tests
# ---------------------------------------------------------------------------


def _mock_match(round_num: int, winner_id=None):
    """Create a lightweight mock TournamentMatch."""
    m = MagicMock()
    m.round = round_num
    m.winner_movie_id = winner_id
    return m


class TestActiveProgress:
    def test_round_1_partially_played(self):
        matches = [
            _mock_match(1, winner_id="w1"),
            _mock_match(1, winner_id=None),
            _mock_match(1, winner_id=None),
        ]
        assert _active_progress(matches) == "Round 1 \u2014 1/3 matches played"

    def test_round_1_complete_round_2_in_progress(self):
        matches = [
            _mock_match(1, winner_id="w1"),
            _mock_match(1, winner_id="w2"),
            _mock_match(2, winner_id=None),
        ]
        assert _active_progress(matches) == "Round 2 \u2014 0/1 matches played"

    def test_no_matches_played(self):
        matches = [
            _mock_match(1, winner_id=None),
            _mock_match(1, winner_id=None),
        ]
        assert _active_progress(matches) == "Round 1 \u2014 0/2 matches played"

    def test_empty_matches_list(self):
        assert _active_progress([]) == "Round 1 \u2014 0/0 matches played"

    def test_all_rounds_complete(self):
        matches = [
            _mock_match(1, winner_id="w1"),
            _mock_match(2, winner_id="w2"),
        ]
        result = _active_progress(matches)
        assert "Round 2" in result


# ---------------------------------------------------------------------------
# FD-041: regeneration must reuse the tournament's original candidate pool
# ---------------------------------------------------------------------------


class TestRegenerateCandidatePool:
    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_regenerate_reuses_the_tournaments_media_type(self):
        """Regenerating a show tournament must not draw candidates from the movie pool."""
        user = _make_user()
        tournament_id = uuid.uuid4()
        tournament = _make_tournament(
            user.id,
            id=tournament_id,
            media_type="show",
            is_ai_curated=True,
            matches=[],
        )
        tournament.llm_response = {"_regen_count": 0, "_theme_hint": ""}

        films = [MagicMock() for _ in range(8)]
        llm_result = {
            "name": "Regenerated",
            "tagline": "new",
            "theme_description": "new desc",
        }

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: AsyncMock()

        with patch(
            "backend.routers.tournaments._load_tournament",
            new_callable=AsyncMock,
            return_value=tournament,
        ), patch(
            "backend.routers.tournaments.get_filtered_ranked_films",
            new_callable=AsyncMock,
            return_value=films,
        ) as mock_pool, patch(
            "backend.routers.tournaments.curate_and_select_films",
            new_callable=AsyncMock,
            return_value=(films, llm_result),
        ), patch(
            "backend.routers.tournaments.create_tournament_bracket",
            new_callable=AsyncMock,
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.post(f"/api/tournaments/{tournament_id}/regenerate")

        assert resp.status_code == 200
        assert mock_pool.call_args.kwargs["media_type"] == "show"

    def test_create_persists_media_type_on_the_tournament_row(self):
        """The media_type a tournament was created over is stored for regeneration."""
        user = _make_user()
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 0
        mock_db.execute.return_value = mock_count_result

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch(
            "backend.routers.tournaments.get_filtered_ranked_films",
            new_callable=AsyncMock,
            return_value=[MagicMock() for _ in range(8)],
        ), patch(
            "backend.routers.tournaments.create_tournament_bracket",
            new_callable=AsyncMock,
        ), patch(
            "backend.routers.tournaments._load_tournament",
            new_callable=AsyncMock,
            return_value=_make_tournament(user.id, media_type="show"),
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.post(
                    "/api/tournaments",
                    json={
                        "name": "Test",
                        "bracket_size": 8,
                        "ai_curated": False,
                        "media_type": "show",
                    },
                )

        assert resp.status_code == 200
        assert mock_db.add.call_args[0][0].media_type == "show"
