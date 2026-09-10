"""Tests for POST /api/me/consent (GDPR consent endpoint)."""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("TOKEN_ENC_KEY", "test-secret-key-for-unit-tests-32b")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests!!")

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.db import get_db
from backend.rate_limit import limiter
from backend.routers.auth import get_current_user
from backend.routers.users import CURRENT_PRIVACY_POLICY_VERSION


@pytest.fixture(autouse=True)
def _clear_dependency_overrides():
    """Ensure dependency overrides are cleaned up even if a test raises."""
    limiter.enabled = False
    yield
    app.dependency_overrides.clear()
    limiter.enabled = True


def _make_user():
    user = MagicMock()
    user.id = uuid.uuid4()
    user.trakt_username = "test_user"
    user.simkl_username = None
    user.created_at = "2024-01-01T00:00:00"
    user.sync_ratings_to_trakt = False
    user.sync_ratings_to_simkl = False
    user.use_ai_features = False
    user.privacy_policy_accepted = False
    user.privacy_policy_version = None
    user.privacy_policy_accepted_at = None
    return user


# ---------------------------------------------------------------------------
# POST /api/me/consent — correct version
# ---------------------------------------------------------------------------


def test_accept_consent_correct_version():
    """POST with the current policy version succeeds and sets accepted=True."""
    fake_user = _make_user()
    mock_db = AsyncMock()

    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_db] = lambda: mock_db

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.post(
            "/api/me/consent",
            json={"version": CURRENT_PRIVACY_POLICY_VERSION},
        )

    assert resp.status_code == 200
    assert resp.json()["privacy_policy_accepted"] is True


# ---------------------------------------------------------------------------
# POST /api/me/consent — wrong version
# ---------------------------------------------------------------------------


def test_accept_consent_wrong_version_400():
    """POST with an unrecognized policy version returns 400."""
    fake_user = _make_user()
    mock_db = AsyncMock()

    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_db] = lambda: mock_db

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.post(
            "/api/me/consent",
            json={"version": "0.0"},
        )

    assert resp.status_code == 400
    assert "Unrecognized" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/me/consent — idempotent
# ---------------------------------------------------------------------------


def test_accept_consent_idempotent():
    """Accepting consent twice with the correct version both return 200."""
    fake_user = _make_user()
    mock_db = AsyncMock()

    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_db] = lambda: mock_db

    with TestClient(app, raise_server_exceptions=False) as client:
        resp1 = client.post(
            "/api/me/consent",
            json={"version": CURRENT_PRIVACY_POLICY_VERSION},
        )
        resp2 = client.post(
            "/api/me/consent",
            json={"version": CURRENT_PRIVACY_POLICY_VERSION},
        )

    assert resp1.status_code == 200
    assert resp2.status_code == 200


# ---------------------------------------------------------------------------
# Frontend parity (FD-008)
# ---------------------------------------------------------------------------


def test_frontend_pins_the_same_policy_version():
    """The frontend copy of the version must match this one.

    A bump that lands only here leaves the frontend prompting for a version the
    endpoint rejects; a bump that lands only there re-prompts every user forever.
    """
    constants = Path(__file__).resolve().parents[2] / "frontend" / "src" / "constants.js"
    match = re.search(
        r'export const CURRENT_PRIVACY_POLICY_VERSION = "([^"]+)";',
        constants.read_text(),
    )

    assert match, f"CURRENT_PRIVACY_POLICY_VERSION not found in {constants}"
    assert match.group(1) == CURRENT_PRIVACY_POLICY_VERSION
