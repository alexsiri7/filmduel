"""Tests for privacy policy consent enforcement on LLM-calling endpoints."""

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


def _make_user(*, privacy_policy_accepted: bool = False):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.privacy_policy_accepted = privacy_policy_accepted
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

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/suggestions")

        assert resp.status_code == 403
        assert "consent" in resp.json()["detail"].lower()

    def test_regenerate_suggestions_requires_consent(self):
        """POST /api/suggestions/regenerate returns 403 when user has not accepted privacy policy."""
        user = _make_user(privacy_policy_accepted=False)
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: AsyncMock()

        with TestClient(app, raise_server_exceptions=False) as client:
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
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/api/suggestions")

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

        # Mock enough DB results so we get past the pre-checks
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [
            MagicMock() for _ in range(16)
        ]
        mock_db.execute.return_value = mock_result

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch(
            "backend.routers.tournaments.get_filtered_ranked_films",
            new_callable=AsyncMock,
            return_value=[MagicMock() for _ in range(16)],
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.post(
                    "/api/tournaments",
                    json={
                        "ai_curated": True,
                        "bracket_size": 8,
                    },
                )

        assert resp.status_code == 403
        assert "consent" in resp.json()["detail"].lower()

    def test_create_non_ai_tournament_no_consent_required(self):
        """POST /api/tournaments with ai_curated=false does not require consent."""
        user = _make_user(privacy_policy_accepted=False)
        mock_db = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: mock_db

        mock_films = [MagicMock() for _ in range(8)]

        with patch(
            "backend.routers.tournaments.get_filtered_ranked_films",
            new_callable=AsyncMock,
            return_value=mock_films,
        ), patch(
            "backend.routers.tournaments.create_tournament_bracket",
            new_callable=AsyncMock,
        ):
            mock_db.commit = AsyncMock()
            mock_db.refresh = AsyncMock()
            mock_db.add = MagicMock()

            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.post(
                    "/api/tournaments",
                    json={
                        "ai_curated": False,
                        "bracket_size": 8,
                    },
                )

        # Should not be 403 — non-AI tournaments don't need consent
        assert resp.status_code != 403

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
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.post(f"/api/tournaments/{tournament_id}/regenerate")

        assert resp.status_code == 403
        assert "consent" in resp.json()["detail"].lower()
