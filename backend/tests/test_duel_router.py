"""Tests for the duel submission endpoint."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.db import get_db
from backend.routers.auth import get_current_user
from backend.schemas import DuelOutcome, DuelResult
from backend.services.duel import ProcessDuelResult


def _make_user():
    user = MagicMock()
    user.id = uuid.uuid4()
    user.trakt_username = "testuser"
    return user


def _make_db():
    return AsyncMock()


FAKE_USER = _make_user()


def _override_user():
    return FAKE_USER


def _override_db():
    return _make_db()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSubmitDuel:
    def setup_method(self):
        app.dependency_overrides[get_current_user] = _override_user
        app.dependency_overrides[get_db] = _override_db

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_valid_submission_returns_200(self):
        """Valid duel submission returns 200 with ELO deltas."""
        mid_a = str(uuid.uuid4())
        mid_b = str(uuid.uuid4())

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

        with patch("backend.routers.duels.process_duel", new_callable=AsyncMock) as mock_pd:
            mock_pd.return_value = fake_result
            client = TestClient(app)
            response = client.post(
                "/api/duels",
                json={
                    "movie_a_id": mid_a,
                    "movie_b_id": mid_b,
                    "outcome": "a_wins",
                    "mode": "discovery",
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["movie_a_elo_delta"] == 15
        assert body["movie_b_elo_delta"] == -15
        assert body["next_action"] == "duel"

    def test_self_duel_returns_400(self):
        """Dueling a movie against itself should return 400."""
        same_id = str(uuid.uuid4())
        client = TestClient(app)
        response = client.post(
            "/api/duels",
            json={
                "movie_a_id": same_id,
                "movie_b_id": same_id,
                "outcome": "a_wins",
                "mode": "discovery",
            },
        )
        assert response.status_code == 400
        assert "itself" in response.json()["detail"].lower()

    def test_invalid_payload_returns_422(self):
        """A request with a missing required field should still return 422."""
        client = TestClient(app)
        response = client.post(
            "/api/duels",
            json={
                "movie_a_id": str(uuid.uuid4()),
                # movie_b_id intentionally omitted
                "outcome": "a_wins",
                "mode": "discovery",
            },
        )
        assert response.status_code == 422
        body = response.json()
        assert "detail" in body

    def test_missing_auth_returns_401(self):
        """Request without authentication should return 401."""
        app.dependency_overrides.clear()
        client = TestClient(app)
        response = client.post(
            "/api/duels",
            json={
                "movie_a_id": str(uuid.uuid4()),
                "movie_b_id": str(uuid.uuid4()),
                "outcome": "a_wins",
            },
        )
        # Without auth override, should fail with 401
        assert response.status_code == 401
