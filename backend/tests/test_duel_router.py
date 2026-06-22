"""Tests for the duel submission endpoint."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from backend.main import app
from backend.db import get_db
from backend.routers.auth import get_current_user
from backend.schemas import DuelOutcome, DuelResult
from backend.services.duel import ProcessDuelResult
from backend.utils.tokens import encode_pair_token


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
        token = encode_pair_token(mid_a, mid_b)

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
            "backend.routers.duels.process_duel", new_callable=AsyncMock
        ) as mock_pd:
            mock_pd.return_value = fake_result
            client = TestClient(app)
            response = client.post(
                "/api/duels",
                json={
                    "movie_a_id": mid_a,
                    "movie_b_id": mid_b,
                    "outcome": "a_wins",
                    "mode": "discovery",
                    "pair_token": token,
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
                "pair_token": "irrelevant",
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
                "pair_token": "irrelevant",
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
                "pair_token": "irrelevant",
            },
        )
        # Without auth override, should fail with 401
        assert response.status_code == 401

    def test_invalid_pair_token_returns_400(self):
        """A duel with an invalid/garbage pair token should return 400."""
        mid_a = str(uuid.uuid4())
        mid_b = str(uuid.uuid4())
        client = TestClient(app)
        response = client.post(
            "/api/duels",
            json={
                "movie_a_id": mid_a,
                "movie_b_id": mid_b,
                "outcome": "a_wins",
                "mode": "discovery",
                "pair_token": "invalid_token",
            },
        )
        assert response.status_code == 400
        assert "pair token" in response.json()["detail"].lower()

    def test_mismatched_pair_token_returns_400(self):
        """A valid token for different movies should be rejected."""
        mid_a = str(uuid.uuid4())
        mid_b = str(uuid.uuid4())
        # Token is for a completely different pair
        other_a = str(uuid.uuid4())
        other_b = str(uuid.uuid4())
        token = encode_pair_token(other_a, other_b)

        client = TestClient(app)
        response = client.post(
            "/api/duels",
            json={
                "movie_a_id": mid_a,
                "movie_b_id": mid_b,
                "outcome": "a_wins",
                "mode": "discovery",
                "pair_token": token,
            },
        )
        assert response.status_code == 400
        assert "pair token" in response.json()["detail"].lower()

    def test_missing_pair_token_returns_422(self):
        """Missing pair_token should fail schema validation."""
        client = TestClient(app)
        response = client.post(
            "/api/duels",
            json={
                "movie_a_id": str(uuid.uuid4()),
                "movie_b_id": str(uuid.uuid4()),
                "outcome": "a_wins",
                "mode": "discovery",
                # no pair_token
            },
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Purge old duel records
# ---------------------------------------------------------------------------


class TestPurgeDuels:
    def _delete(self, client, purged_ids=None):
        user = _make_user()
        user.is_admin = True
        db = _make_db()
        purged_ids = purged_ids or []
        db.execute = AsyncMock(
            return_value=MagicMock(
                fetchall=MagicMock(return_value=[(pid,) for pid in purged_ids])
            )
        )
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: db
        try:
            return client.delete("/api/duels/admin/purge-old-records")
        finally:
            app.dependency_overrides.clear()

    def test_returns_purged_count(self):
        purged = [uuid.uuid4(), uuid.uuid4()]
        client = TestClient(app)
        response = self._delete(client, purged_ids=purged)
        assert response.status_code == 200
        assert response.json() == {"purged": 2}

    def test_returns_zero_when_nothing_to_purge(self):
        client = TestClient(app)
        response = self._delete(client, purged_ids=[])
        assert response.status_code == 200
        assert response.json() == {"purged": 0}

    def test_non_admin_returns_403(self):
        user = _make_user()
        user.is_admin = False
        db = _make_db()
        client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: db
        try:
            response = client.delete("/api/duels/admin/purge-old-records")
        finally:
            app.dependency_overrides.clear()
        assert response.status_code == 403
        assert "admin" in response.json()["detail"].lower()

    def test_unauthenticated_returns_401(self):
        client = TestClient(app)
        # No dependency overrides — auth stack runs normally
        response = client.delete("/api/duels/admin/purge-old-records")
        assert response.status_code == 401
