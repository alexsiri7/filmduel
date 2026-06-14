"""Tests for suggestions router — consent, not_enough_films, regenerate limits, 503."""

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


def _make_user(*, privacy_policy_accepted: bool = True):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.privacy_policy_accepted = privacy_policy_accepted
    return user


# ---------------------------------------------------------------------------
# Items 5: consent gate & not_enough_films
# ---------------------------------------------------------------------------


class TestGetSuggestions:
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

    def test_get_suggestions_not_enough_films(self):
        """GET /api/suggestions returns status='not_enough_films' with empty list."""
        user = _make_user(privacy_policy_accepted=True)
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: AsyncMock()

        with patch(
            "backend.routers.suggestions.has_enough_ranked",
            new_callable=AsyncMock,
            return_value=False,
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/api/suggestions")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "not_enough_films"
        assert body["suggestions"] == []


# ---------------------------------------------------------------------------
# Item 6: regenerate daily limit & 503
# ---------------------------------------------------------------------------


class TestRegenerateSuggestions:
    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_regenerate_enforces_daily_limit(self):
        """POST /api/suggestions/regenerate returns 429 when daily limit reached."""
        user = _make_user(privacy_policy_accepted=True)
        mock_db = AsyncMock()

        # Mock has_enough_ranked to return True
        # Mock the regen count query to return 3 (at limit)
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 3
        mock_db.execute.return_value = mock_count_result

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch(
            "backend.routers.suggestions.has_enough_ranked",
            new_callable=AsyncMock,
            return_value=True,
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.post("/api/suggestions/regenerate")

        assert resp.status_code == 429
        assert "3 times per day" in resp.json()["detail"]

    def test_regenerate_503_without_llm_key(self):
        """POST /api/suggestions/regenerate returns 503 when LLM key not configured."""
        user = _make_user(privacy_policy_accepted=True)
        mock_db = AsyncMock()

        # Mock regen count below limit
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0
        mock_db.execute.return_value = mock_count_result

        # Mock _get_active_suggestions to return empty (no existing to dismiss)
        # Mock _create_suggestions to raise ValueError (LLM key missing)

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch(
            "backend.routers.suggestions.has_enough_ranked",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "backend.routers.suggestions._get_active_suggestions",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "backend.routers.suggestions._create_suggestions",
            new_callable=AsyncMock,
            side_effect=ValueError("LLM_API_KEY not configured"),
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.post("/api/suggestions/regenerate")

        assert resp.status_code == 503
