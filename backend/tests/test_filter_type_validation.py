"""Integration tests for filter_type query parameter validation on pool-count endpoint.

SEC-12 regression guard: ensures invalid filter_type values are rejected at the
HTTP boundary with 422, and valid values pass through without a validation error.
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests!!")

from fastapi.testclient import TestClient

from backend.db import get_db
from backend.main import app
from backend.routers.auth import get_current_user

client = TestClient(app)


def _fake_user() -> MagicMock:
    u = MagicMock()
    u.id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    return u


def _fake_db() -> AsyncMock:
    return AsyncMock()


class TestGetPoolCountFilterTypeValidation:
    def setup_method(self):
        app.dependency_overrides[get_current_user] = lambda: _fake_user()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_invalid_filter_type_returns_422(self):
        resp = client.get("/api/tournaments/pool-count?filter_type=invalid_value")
        assert resp.status_code == 422

    def test_invalid_filter_type_year_returns_422(self):
        resp = client.get("/api/tournaments/pool-count?filter_type=year")
        assert resp.status_code == 422

    def test_invalid_filter_type_rating_returns_422(self):
        resp = client.get("/api/tournaments/pool-count?filter_type=rating")
        assert resp.status_code == 422

    def test_valid_filter_type_genre_accepted(self):
        app.dependency_overrides[get_db] = _fake_db
        with patch(
            "backend.routers.tournaments.get_filtered_ranked_films",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get("/api/tournaments/pool-count?filter_type=genre")
        assert resp.status_code != 422

    def test_valid_filter_type_decade_accepted(self):
        app.dependency_overrides[get_db] = _fake_db
        with patch(
            "backend.routers.tournaments.get_filtered_ranked_films",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get("/api/tournaments/pool-count?filter_type=decade")
        assert resp.status_code != 422

    def test_no_filter_type_accepted(self):
        app.dependency_overrides[get_db] = _fake_db
        with patch(
            "backend.routers.tournaments.get_filtered_ranked_films",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get("/api/tournaments/pool-count")
        assert resp.status_code != 422
