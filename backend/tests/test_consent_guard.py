"""Tests for privacy policy consent enforcement on LLM-calling and data-collecting endpoints."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("TOKEN_ENC_KEY", "test-secret-key-for-unit-tests-32b")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests!!")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from backend.config import get_settings

get_settings.cache_clear()

from backend.services.token_crypto import _fernet  # noqa: E402

_fernet.cache_clear()

from backend.main import app  # noqa: E402
from backend.tests import SPA_HEADERS  # noqa: E402
from backend.db import get_db  # noqa: E402
from backend.routers.auth import get_current_user  # noqa: E402
from backend.utils.tokens import encode_pair_token  # noqa: E402


def _make_user(*, privacy_policy_accepted: bool = False, use_ai_features: bool = True):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.privacy_policy_accepted = privacy_policy_accepted
    user.use_ai_features = use_ai_features
    return user


# ---------------------------------------------------------------------------
# Suggestions endpoints — consent guard
# ---------------------------------------------------------------------------


class TestSuggestionsConsentGuard:
    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_get_suggestions_requires_consent(self):
        """GET /api/suggestions returns 403 when user has not accepted privacy policy."""
        user = _make_user(privacy_policy_accepted=False)
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: AsyncMock()

        with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
            resp = client.get("/api/suggestions")

        assert resp.status_code == 403
        assert "consent" in resp.json()["detail"].lower()

    def test_regenerate_suggestions_requires_consent(self):
        """POST /api/suggestions/regenerate returns 403 when user has not accepted privacy policy."""
        user = _make_user(privacy_policy_accepted=False)
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: AsyncMock()

        with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
            resp = client.post("/api/suggestions/regenerate")

        assert resp.status_code == 403
        assert "consent" in resp.json()["detail"].lower()

    def test_get_suggestions_allowed_with_consent(self):
        """GET /api/suggestions proceeds past consent check when policy accepted."""
        user = _make_user(privacy_policy_accepted=True)
        mock_db = AsyncMock()
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch(
            "backend.routers.suggestions.has_enough_ranked",
            new_callable=AsyncMock,
            return_value=False,
        ):
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.get("/api/suggestions")

        # Should pass consent check and hit "not_enough_films" path
        assert resp.status_code == 200
        assert resp.json()["status"] == "not_enough_films"

    def test_regenerate_suggestions_allowed_with_consent(self):
        """POST /api/suggestions/regenerate proceeds past consent check when policy accepted."""
        user = _make_user(privacy_policy_accepted=True)
        mock_db = AsyncMock()
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch(
            "backend.routers.suggestions.has_enough_ranked",
            new_callable=AsyncMock,
            return_value=False,
        ):
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.post("/api/suggestions/regenerate")

        # Should pass consent check and hit "not_enough_films" path
        assert resp.status_code == 200
        assert resp.json()["status"] == "not_enough_films"


# ---------------------------------------------------------------------------
# Tournament endpoints — consent guard
# ---------------------------------------------------------------------------


class TestTournamentConsentGuard:
    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_create_ai_tournament_requires_consent(self):
        """POST /api/tournaments with ai_curated=true returns 403 when no consent."""
        user = _make_user(privacy_policy_accepted=False)
        mock_db = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: mock_db

        with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/tournaments",
                json={
                    "ai_curated": True,
                    "bracket_size": 8,
                },
            )

        assert resp.status_code == 403
        assert "consent" in resp.json()["detail"].lower()

    def test_create_ai_tournament_consent_fires_before_db(self):
        """Consent check must execute before DB query for AI tournament creation."""
        user = _make_user(privacy_policy_accepted=False)
        mock_db = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch(
            "backend.routers.tournaments.get_filtered_ranked_films",
            new_callable=AsyncMock,
            return_value=[MagicMock() for _ in range(16)],
        ) as mock_db_query:
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.post(
                    "/api/tournaments",
                    json={"ai_curated": True, "bracket_size": 8},
                )

        assert resp.status_code == 403
        assert "consent" in resp.json()["detail"].lower()
        mock_db_query.assert_not_called()

    def test_create_non_ai_tournament_no_consent_required(self):
        """POST /api/tournaments with ai_curated=false does not require consent."""
        user = _make_user(privacy_policy_accepted=False)
        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 0  # daily cap below limit
        mock_db.execute.return_value = mock_count_result

        mock_films = [MagicMock() for _ in range(8)]

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: mock_db

        mock_tournament = MagicMock()
        mock_tournament.id = uuid.uuid4()
        mock_tournament.matches = []
        mock_tournament.is_ai_curated = False
        mock_tournament.name = "Test"
        mock_tournament.filter_type = None
        mock_tournament.filter_value = None
        mock_tournament.bracket_size = 8
        mock_tournament.status = "active"
        mock_tournament.champion_movie_id = None
        mock_tournament.tagline = None
        mock_tournament.theme_description = None
        mock_tournament.created_at = datetime.now(timezone.utc)
        mock_tournament.completed_at = None

        with patch(
            "backend.routers.tournaments.get_filtered_ranked_films",
            new_callable=AsyncMock,
            return_value=mock_films,
        ), patch(
            "backend.routers.tournaments.create_tournament_bracket",
            new_callable=AsyncMock,
        ), patch(
            "backend.routers.tournaments._load_tournament",
            new_callable=AsyncMock,
            return_value=mock_tournament,
        ):
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.post(
                    "/api/tournaments",
                    json={
                        "ai_curated": False,
                        "bracket_size": 8,
                    },
                )

        # Non-AI tournaments must not be blocked by consent guard
        assert resp.status_code == 200

    def test_create_ai_tournament_allowed_with_consent(self):
        """POST /api/tournaments with ai_curated=true proceeds when consent given."""
        user = _make_user(privacy_policy_accepted=True)
        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 0  # daily cap below limit
        mock_db.execute.return_value = mock_count_result

        mock_films = [MagicMock() for _ in range(8)]
        mock_llm_result = {
            "name": "Test Tournament",
            "tagline": "t",
            "theme_description": "d",
        }

        tournament_id = uuid.uuid4()
        mock_tournament = MagicMock()
        mock_tournament.id = tournament_id
        mock_tournament.matches = []
        mock_tournament.is_ai_curated = True
        mock_tournament.name = "Test Tournament"
        mock_tournament.filter_type = None
        mock_tournament.filter_value = None
        mock_tournament.bracket_size = 8
        mock_tournament.status = "active"
        mock_tournament.champion_movie_id = None
        mock_tournament.tagline = "t"
        mock_tournament.theme_description = "d"
        mock_tournament.created_at = datetime.now(timezone.utc)
        mock_tournament.completed_at = None

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch(
            "backend.routers.tournaments.get_filtered_ranked_films",
            new_callable=AsyncMock,
            return_value=mock_films,
        ), patch(
            "backend.routers.tournaments.curate_and_select_films",
            new_callable=AsyncMock,
            return_value=(mock_films, mock_llm_result),
        ), patch(
            "backend.routers.tournaments.create_tournament_bracket",
            new_callable=AsyncMock,
        ), patch(
            "backend.routers.tournaments._load_tournament",
            new_callable=AsyncMock,
            return_value=mock_tournament,
        ):
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.post(
                    "/api/tournaments",
                    json={"ai_curated": True, "bracket_size": 8},
                )

        # Consenting user must not be blocked
        assert resp.status_code == 200

    def test_regenerate_tournament_requires_consent(self):
        """POST /api/tournaments/{id}/regenerate returns 403 when no consent."""
        user = _make_user(privacy_policy_accepted=False)
        mock_db = AsyncMock()

        tournament_id = uuid.uuid4()

        # Mock tournament object
        mock_tournament = MagicMock()
        mock_tournament.id = tournament_id
        mock_tournament.user_id = user.id
        mock_tournament.is_ai_curated = True
        mock_tournament.matches = []  # no played matches
        mock_tournament.llm_response = {"_regen_count": 0}
        mock_tournament.bracket_size = 8
        mock_tournament.filter_type = None
        mock_tournament.filter_value = None

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch(
            "backend.routers.tournaments._load_tournament",
            new_callable=AsyncMock,
            return_value=mock_tournament,
        ):
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.post(f"/api/tournaments/{tournament_id}/regenerate")

        assert resp.status_code == 403
        assert "consent" in resp.json()["detail"].lower()

    def test_regenerate_tournament_allowed_with_consent(self):
        """POST /api/tournaments/{id}/regenerate proceeds when consent given."""
        user = _make_user(privacy_policy_accepted=True)
        mock_db = AsyncMock()

        tournament_id = uuid.uuid4()

        mock_tournament = MagicMock()
        mock_tournament.id = tournament_id
        mock_tournament.user_id = user.id
        mock_tournament.is_ai_curated = True
        mock_tournament.matches = []
        mock_tournament.llm_response = {"_regen_count": 0, "_theme_hint": ""}
        mock_tournament.bracket_size = 8
        mock_tournament.filter_type = None
        mock_tournament.filter_value = None
        mock_tournament.name = "Test Tournament"
        mock_tournament.tagline = "t"
        mock_tournament.theme_description = "d"
        mock_tournament.status = "active"
        mock_tournament.champion_movie_id = None
        mock_tournament.created_at = datetime.now(timezone.utc)
        mock_tournament.completed_at = None

        # Set up db.execute to return a result whose scalar_one() returns mock_tournament
        mock_execute_result = MagicMock()
        mock_execute_result.scalar_one.return_value = mock_tournament
        mock_db.execute = AsyncMock(return_value=mock_execute_result)

        mock_films = [MagicMock() for _ in range(8)]
        mock_llm_result = {
            "name": "Regenerated Tournament",
            "tagline": "new",
            "theme_description": "new desc",
        }

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch(
            "backend.routers.tournaments._load_tournament",
            new_callable=AsyncMock,
            return_value=mock_tournament,
        ), patch(
            "backend.routers.tournaments.get_filtered_ranked_films",
            new_callable=AsyncMock,
            return_value=mock_films,
        ), patch(
            "backend.routers.tournaments.curate_and_select_films",
            new_callable=AsyncMock,
            return_value=(mock_films, mock_llm_result),
        ), patch(
            "backend.routers.tournaments.create_tournament_bracket",
            new_callable=AsyncMock,
        ):
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.post(f"/api/tournaments/{tournament_id}/regenerate")

        # Consenting user must not be blocked by the consent guard
        assert resp.status_code == 200

    def test_regenerate_tournament_curation_error_does_not_leak_details(self):
        """POST /api/tournaments/{id}/regenerate must not expose internal ValueError details."""
        user = _make_user(privacy_policy_accepted=True)
        mock_db = AsyncMock()

        tournament_id = uuid.uuid4()
        internal_uuid = str(uuid.uuid4())

        mock_tournament = MagicMock()
        mock_tournament.id = tournament_id
        mock_tournament.user_id = user.id
        mock_tournament.is_ai_curated = True
        mock_tournament.matches = []
        mock_tournament.llm_response = {"_regen_count": 0, "_theme_hint": ""}
        mock_tournament.bracket_size = 8
        mock_tournament.filter_type = None
        mock_tournament.filter_value = None

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch(
            "backend.routers.tournaments._load_tournament",
            new_callable=AsyncMock,
            return_value=mock_tournament,
        ), patch(
            "backend.routers.tournaments.get_filtered_ranked_films",
            new_callable=AsyncMock,
            return_value=[MagicMock() for _ in range(8)],
        ), patch(
            "backend.routers.tournaments.curate_and_select_films",
            new_callable=AsyncMock,
            side_effect=ValueError(f"AI selected films not in candidate pool: {{{internal_uuid}}}"),
        ):
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.post(f"/api/tournaments/{tournament_id}/regenerate")

        assert resp.status_code == 500
        assert internal_uuid not in resp.text
        assert "candidate pool" not in resp.text
        assert resp.json()["detail"] == "AI curation failed. Please try again."
        # Guard against regressions where execution continues past the ValueError
        # and db writes (delete matches, flush, update metadata) are silently triggered.
        # The only statement allowed to reach the session is the regen advisory lock.
        executed = [
            str(c.args[0].compile(dialect=postgresql.dialect()))
            for c in mock_db.execute.await_args_list
        ]
        assert executed, "expected the regeneration advisory lock to be acquired"
        assert all("pg_advisory_xact_lock" in sql for sql in executed), executed
        mock_db.flush.assert_not_called()

    def test_create_ai_tournament_curation_error_does_not_leak_details(self):
        """POST /api/tournaments must not expose internal ValueError details from AI curation."""
        user = _make_user(privacy_policy_accepted=True)
        mock_db = AsyncMock()
        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 0  # daily cap below limit
        mock_db.execute.return_value = mock_count_result

        internal_uuid = str(uuid.uuid4())

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch(
            "backend.routers.tournaments.get_filtered_ranked_films",
            new_callable=AsyncMock,
            return_value=[MagicMock() for _ in range(8)],
        ), patch(
            "backend.routers.tournaments.curate_and_select_films",
            new_callable=AsyncMock,
            side_effect=ValueError(f"AI selected films not in candidate pool: {{{internal_uuid}}}"),
        ):
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.post(
                    "/api/tournaments",
                    json={"name": "Test", "bracket_size": 8, "ai_curated": True},
                )

        assert resp.status_code == 500
        assert internal_uuid not in resp.text
        assert "candidate pool" not in resp.text
        assert resp.json()["detail"] == "AI curation failed. Please try again."


# ---------------------------------------------------------------------------
# AI consent guard — use_ai_features toggle
# ---------------------------------------------------------------------------


class TestAiConsentGuard:
    """require_ai_consent() blocks users who have disabled AI features.

    Privacy-policy-denied path is already covered by the existing consent
    suite above; these tests focus on the new use_ai_features toggle.
    """

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_suggestions_blocked_when_privacy_policy_not_accepted(self):
        """GET /api/suggestions returns 403 when privacy_policy_accepted=False (even if AI toggle is on)."""
        user = _make_user(privacy_policy_accepted=False, use_ai_features=True)
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: AsyncMock()

        with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
            resp = client.get("/api/suggestions")

        assert resp.status_code == 403
        assert "Privacy policy consent required" in resp.json()["detail"]

    def test_suggestions_blocked_when_ai_disabled(self):
        """GET /api/suggestions returns 403 when use_ai_features=False."""
        user = _make_user(privacy_policy_accepted=True, use_ai_features=False)
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: AsyncMock()

        with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
            resp = client.get("/api/suggestions")

        assert resp.status_code == 403
        assert "AI features are disabled" in resp.json()["detail"]

    def test_suggestions_allowed_when_ai_enabled(self):
        """GET /api/suggestions proceeds when use_ai_features=True."""
        user = _make_user(privacy_policy_accepted=True, use_ai_features=True)
        mock_db = AsyncMock()
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch(
            "backend.routers.suggestions.has_enough_ranked",
            new_callable=AsyncMock,
            return_value=False,
        ):
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.get("/api/suggestions")

        assert resp.status_code == 200
        assert resp.json()["status"] == "not_enough_films"

    def test_regenerate_suggestions_blocked_when_ai_disabled(self):
        """POST /api/suggestions/regenerate returns 403 when use_ai_features=False."""
        user = _make_user(privacy_policy_accepted=True, use_ai_features=False)
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: AsyncMock()

        with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
            resp = client.post("/api/suggestions/regenerate")

        assert resp.status_code == 403
        assert "AI features are disabled" in resp.json()["detail"]

    def test_create_ai_tournament_blocked_when_ai_disabled(self):
        """POST /api/tournaments with ai_curated=True returns 403 when use_ai_features=False."""
        user = _make_user(privacy_policy_accepted=True, use_ai_features=False)
        mock_db = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: mock_db

        with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/tournaments",
                json={"ai_curated": True, "bracket_size": 8},
            )

        assert resp.status_code == 403
        assert "AI features are disabled" in resp.json()["detail"]

    def test_regenerate_tournament_blocked_when_ai_disabled(self):
        """POST /api/tournaments/{id}/regenerate returns 403 when use_ai_features=False."""
        user = _make_user(privacy_policy_accepted=True, use_ai_features=False)
        mock_db = AsyncMock()

        tournament_id = uuid.uuid4()

        mock_tournament = MagicMock()
        mock_tournament.id = tournament_id
        mock_tournament.user_id = user.id
        mock_tournament.is_ai_curated = True
        mock_tournament.matches = []
        mock_tournament.llm_response = {"_regen_count": 0}
        mock_tournament.bracket_size = 8
        mock_tournament.filter_type = None
        mock_tournament.filter_value = None

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch(
            "backend.routers.tournaments._load_tournament",
            new_callable=AsyncMock,
            return_value=mock_tournament,
        ):
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.post(f"/api/tournaments/{tournament_id}/regenerate")

        assert resp.status_code == 403
        assert "AI features are disabled" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Data-collecting endpoints — consent guard (#571)
# ---------------------------------------------------------------------------


def _duel_payload(user) -> dict:
    mid_a, mid_b = str(uuid.uuid4()), str(uuid.uuid4())
    return {
        "movie_a_id": mid_a,
        "movie_b_id": mid_b,
        "outcome": "a_wins",
        "mode": "discovery",
        "pair_token": encode_pair_token(mid_a, mid_b, user_id=str(user.id)),
    }


class TestDataCollectionConsentGuard:
    """Sync, duels, swipes and tournament matches must not run before consent."""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _install(self, user, db=None):
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: db if db is not None else AsyncMock()

    # -- 403 without consent --------------------------------------------------

    def test_sync_requires_consent(self):
        user = _make_user(privacy_policy_accepted=False)
        self._install(user)

        with patch(
            "backend.routers.users._force_pool_sync", new_callable=AsyncMock
        ) as mock_sync:
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.post("/api/sync")

        assert resp.status_code == 403
        assert "consent" in resp.json()["detail"].lower()
        mock_sync.assert_not_awaited()

    def test_submit_duel_requires_consent(self):
        user = _make_user(privacy_policy_accepted=False)
        self._install(user)

        with patch(
            "backend.routers.duels.process_duel", new_callable=AsyncMock
        ) as mock_pd:
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.post("/api/duels", json=_duel_payload(user))

        assert resp.status_code == 403
        assert "consent" in resp.json()["detail"].lower()
        mock_pd.assert_not_awaited()

    def test_swipe_cards_requires_consent(self):
        user = _make_user(privacy_policy_accepted=False)
        self._install(user)

        with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
            resp = client.get("/api/swipe/cards")

        assert resp.status_code == 403
        assert "consent" in resp.json()["detail"].lower()

    def test_submit_swipe_results_requires_consent(self):
        user = _make_user(privacy_policy_accepted=False)
        self._install(user)

        with patch(
            "backend.routers.swipe.compute_next_action", new_callable=AsyncMock
        ) as mock_next:
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.post("/api/swipe/results", json={"results": []})

        assert resp.status_code == 403
        assert "consent" in resp.json()["detail"].lower()
        mock_next.assert_not_awaited()

    def test_submit_match_result_requires_consent(self):
        user = _make_user(privacy_policy_accepted=False)
        self._install(user)

        with patch(
            "backend.routers.tournaments._load_tournament", new_callable=AsyncMock
        ) as mock_load:
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.post(
                    f"/api/tournaments/{uuid.uuid4()}/matches/{uuid.uuid4()}",
                    json={"winner_movie_id": str(uuid.uuid4())},
                )

        assert resp.status_code == 403
        assert "consent" in resp.json()["detail"].lower()
        mock_load.assert_not_awaited()

    # -- pass-through with consent --------------------------------------------

    def test_sync_allowed_with_consent(self):
        user = _make_user(privacy_policy_accepted=True)
        mock_db = AsyncMock()
        mock_db.scalar.return_value = 0
        self._install(user, mock_db)

        with patch(
            "backend.routers.users._force_pool_sync",
            new_callable=AsyncMock,
            return_value=user,
        ) as mock_sync:
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.post("/api/sync")

        assert resp.status_code == 200
        mock_sync.assert_awaited_once()

    def test_submit_duel_allowed_with_consent(self):
        from backend.schemas import DuelOutcome, DuelResult
        from backend.services.duel import ProcessDuelResult

        user = _make_user(privacy_policy_accepted=True)
        self._install(user)
        fake_result = ProcessDuelResult(
            api_result=DuelResult(
                outcome=DuelOutcome.a_wins,
                movie_a_elo_delta=15,
                movie_b_elo_delta=-15,
                next_action="duel",
            ),
            new_elo_a=1015,
            new_elo_b=985,
        )

        with patch(
            "backend.routers.duels.process_duel",
            new_callable=AsyncMock,
            return_value=fake_result,
        ) as mock_pd:
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.post("/api/duels", json=_duel_payload(user))

        assert resp.status_code == 200
        mock_pd.assert_awaited_once()

    def test_swipe_cards_allowed_with_consent(self):
        user = _make_user(privacy_policy_accepted=True)
        self._install(user)

        with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
            resp = client.get("/api/swipe/cards")

        assert resp.status_code != 403

    def test_submit_swipe_results_allowed_with_consent(self):
        user = _make_user(privacy_policy_accepted=True)
        mock_db = AsyncMock()

        async def fake_execute(stmt, *args, **kwargs):
            sql = str(stmt.compile(dialect=postgresql.dialect())).lower()
            result = MagicMock()
            if "swipe_results" in sql:
                result.scalar_one.return_value = 0  # under the daily cap
            else:
                result.scalar.return_value = 100  # pool not low
            return result

        mock_db.execute = AsyncMock(side_effect=fake_execute)
        self._install(user, mock_db)

        with patch(
            "backend.routers.swipe.compute_next_action",
            new_callable=AsyncMock,
            return_value="duel",
        ) as mock_next:
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.post("/api/swipe/results", json={"results": []})

        assert resp.status_code == 200
        mock_next.assert_awaited_once()

    def test_submit_match_result_allowed_with_consent(self):
        user = _make_user(privacy_policy_accepted=True)
        self._install(user)
        tournament_id = uuid.uuid4()
        winner_id, loser_id = uuid.uuid4(), uuid.uuid4()

        tournament = MagicMock()
        tournament.id = tournament_id
        tournament.user_id = user.id
        tournament.bracket_size = 8
        tournament.matches = []
        tournament.is_ai_curated = False
        tournament.name = "Test"
        tournament.filter_type = None
        tournament.filter_value = None
        tournament.status = "active"
        tournament.champion_movie_id = None
        tournament.tagline = None
        tournament.theme_description = None
        tournament.created_at = datetime.now(timezone.utc)
        tournament.completed_at = None

        with patch(
            "backend.routers.tournaments._load_tournament",
            new_callable=AsyncMock,
            return_value=tournament,
        ), patch(
            "backend.routers.tournaments.validate_match",
            return_value=loser_id,
        ), patch(
            "backend.routers.tournaments.record_match_winner",
            new_callable=AsyncMock,
            return_value=(1210, 1090),
        ) as mock_record, patch(
            "backend.routers.tournaments.sync_ratings_background",
            new_callable=AsyncMock,
        ):
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.post(
                    f"/api/tournaments/{tournament_id}/matches/{uuid.uuid4()}",
                    json={"winner_movie_id": str(winner_id)},
                )

        assert resp.status_code == 200
        mock_record.assert_awaited_once()
