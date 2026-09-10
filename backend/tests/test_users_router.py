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
from backend.db_models import User
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


# ---------------------------------------------------------------------------
# FD-057: GET /api/me response contract
# ---------------------------------------------------------------------------


PROFILE_FIELDS = {
    "id",
    "trakt_username",
    "simkl_username",
    "created_at",
    "sync_ratings_to_trakt",
    "sync_ratings_to_simkl",
    "use_ai_features",
    "privacy_policy_accepted",
    "privacy_policy_version",
}

TOKEN_SENTINELS = (
    "trakt-access-sentinel",
    "trakt-refresh-sentinel",
    "simkl-access-sentinel",
    "simkl-refresh-sentinel",
)

EXPIRY_SENTINEL_YEAR = "2033"


def _user_row_with_tokens() -> User:
    """A user row carrying every OAuth secret the schema can hold.

    Assigns the encrypted columns rather than the EncryptedToken descriptors so
    the sentinels reach the response untransformed if anything ever leaks them.
    """
    expires_at = datetime(int(EXPIRY_SENTINEL_YEAR), 6, 1, tzinfo=timezone.utc)
    return User(
        id=uuid.uuid4(),
        trakt_user_id="trakt-user-42",
        trakt_username="ripley",
        trakt_access_token_enc="trakt-access-sentinel",
        trakt_refresh_token_enc="trakt-refresh-sentinel",
        trakt_token_expires_at=expires_at,
        simkl_user_id="simkl-user-42",
        simkl_username="ripley_simkl",
        simkl_access_token_enc="simkl-access-sentinel",
        simkl_refresh_token_enc="simkl-refresh-sentinel",
        simkl_token_expires_at=expires_at,
        created_at=datetime(2026, 3, 4, tzinfo=timezone.utc),
        sync_ratings_to_trakt=True,
        sync_ratings_to_simkl=True,
        use_ai_features=False,
        privacy_policy_accepted=True,
        privacy_policy_version="2.1",
    )


class TestProfileResponseContract:
    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_response_keys_are_pinned_to_the_full_allow_list(self):
        """Equality, not a token deny-list: a new UserResponse field fails here."""
        app.dependency_overrides[get_current_user] = _user_row_with_tokens

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/me")

        assert resp.status_code == 200
        assert set(resp.json()) == PROFILE_FIELDS

    def test_response_carries_the_profile_values(self):
        """Guards the allow-list assertion against passing on an empty profile."""
        user = _user_row_with_tokens()
        app.dependency_overrides[get_current_user] = lambda: user

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/me")

        body = resp.json()
        assert body["id"] == str(user.id)
        assert body["trakt_username"] == "ripley"
        assert body["simkl_username"] == "ripley_simkl"
        assert body["sync_ratings_to_trakt"] is True
        assert body["sync_ratings_to_simkl"] is True
        assert body["use_ai_features"] is False
        assert body["privacy_policy_accepted"] is True
        assert body["privacy_policy_version"] == "2.1"

    def test_no_token_or_expiry_value_reaches_the_body(self):
        """Catches a leak re-keyed under a name the allow-list would not flag."""
        app.dependency_overrides[get_current_user] = _user_row_with_tokens

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/me")

        assert resp.status_code == 200
        for sentinel in TOKEN_SENTINELS:
            assert sentinel not in resp.text
        assert EXPIRY_SENTINEL_YEAR not in resp.text
