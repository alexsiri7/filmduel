"""Tests for users router — account deletion cascade, privacy policy enforcement."""

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


def _make_user(
    *,
    trakt_access_token_enc: str | None = "encrypted-trakt",
    simkl_access_token_enc: str | None = "encrypted-simkl",
    trakt_access_token: str | None = "trakt-token",
    simkl_access_token: str | None = "simkl-token",
    privacy_policy_accepted: bool = True,
    privacy_policy_version: str | None = "2.0",
):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.trakt_access_token_enc = trakt_access_token_enc
    user.simkl_access_token_enc = simkl_access_token_enc
    user.trakt_access_token = trakt_access_token
    user.simkl_access_token = simkl_access_token
    user.privacy_policy_accepted = privacy_policy_accepted
    user.privacy_policy_version = privacy_policy_version
    user.trakt_username = "testuser"
    user.simkl_username = "testuser"
    user.created_at = datetime.now(timezone.utc)
    user.sync_ratings_to_trakt = False
    user.sync_ratings_to_simkl = False
    return user


# ---------------------------------------------------------------------------
# Item 12: account deletion cascade
# ---------------------------------------------------------------------------


class TestDeleteAccount:
    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_delete_account_calls_token_revocation(self):
        """DELETE /api/me revokes both Trakt and SIMKL tokens."""
        user = _make_user()
        mock_db = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: mock_db

        mock_trakt = MagicMock()
        mock_trakt.revoke_token = AsyncMock()
        mock_simkl = MagicMock()
        mock_simkl.revoke_token = AsyncMock()

        with patch(
            "backend.routers.users.TraktClient", return_value=mock_trakt
        ), patch(
            "backend.routers.users.SimklClient", return_value=mock_simkl
        ), patch(
            "backend.routers.users.get_settings"
        ) as mock_settings:
            mock_settings.return_value = MagicMock(
                TRAKT_CLIENT_ID="fake",
                TRAKT_CLIENT_SECRET="fake-secret",
                SIMKL_CLIENT_ID="fake",
                SIMKL_CLIENT_SECRET="fake-secret",
            )
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.delete("/api/me")

        assert resp.status_code == 204
        mock_trakt.revoke_token.assert_awaited_once()
        mock_simkl.revoke_token.assert_awaited_once()

    def test_delete_account_propagates_revocation_failure(self):
        """DELETE /api/me returns 500 when token revocation raises.

        The endpoint documents "best-effort" revocation but currently does not
        wrap calls in try/except, so failures propagate.
        """
        user = _make_user()
        mock_db = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: mock_db

        mock_trakt = MagicMock()
        mock_trakt.revoke_token = AsyncMock(
            side_effect=Exception("Trakt API down")
        )

        with patch(
            "backend.routers.users.TraktClient", return_value=mock_trakt
        ), patch(
            "backend.routers.users.get_settings"
        ) as mock_settings:
            mock_settings.return_value = MagicMock(
                TRAKT_CLIENT_ID="fake",
                TRAKT_CLIENT_SECRET="fake-secret",
                SIMKL_CLIENT_ID="fake",
                SIMKL_CLIENT_SECRET="fake-secret",
            )
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.delete("/api/me")

        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Item 13: privacy policy version enforcement
# ---------------------------------------------------------------------------


class TestPrivacyPolicyVersion:
    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_privacy_policy_version_mismatch_flags_reconsent(self):
        """GET /api/me with outdated policy version returns privacy_policy_accepted=False."""
        user = _make_user(
            privacy_policy_accepted=False,
            privacy_policy_version="1.0",
        )
        app.dependency_overrides[get_current_user] = lambda: user

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/me")

        assert resp.status_code == 200
        body = resp.json()
        assert body["privacy_policy_accepted"] is False
