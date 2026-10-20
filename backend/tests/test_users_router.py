"""Tests for users router — account deletion cascade, privacy policy enforcement."""

from __future__ import annotations

import base64
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("TOKEN_ENC_KEY", "test-secret-key-for-unit-tests-32b")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests!!")

import httpx
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.config import get_settings

# conftest already built the cached Settings (via backend.rate_limit) before the
# TOKEN_ENC_KEY default above was set; rebuild so it is picked up.
get_settings.cache_clear()

from backend.services.token_crypto import _fernet, encrypt_token  # noqa: E402

_fernet.cache_clear()

from backend.main import app
from backend.tests import SPA_HEADERS
from backend.db import get_db
from backend.db_models import User
from backend.rate_limit import limiter
from backend.routers.auth import CURRENT_PRIVACY_POLICY_VERSION, get_current_user
from backend.services.data_export import FEEDBACK_SCREENSHOT_PATH
from backend.routers.users import (
    _effective_pool_import_status,
    _record_pool_import_outcome,
    _run_pool_import,
)


def _make_user(
    *,
    trakt_access_token_enc: str | None = "encrypted-trakt",
    simkl_access_token_enc: str | None = "encrypted-simkl",
    trakt_access_token: str | None = "trakt-token",
    simkl_access_token: str | None = "simkl-token",
    privacy_policy_accepted: bool = True,
    privacy_policy_version: str | None = CURRENT_PRIVACY_POLICY_VERSION,
):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.trakt_access_token_enc = trakt_access_token_enc
    user.simkl_access_token_enc = simkl_access_token_enc
    user.trakt_access_token = trakt_access_token
    user.simkl_access_token = simkl_access_token
    user.privacy_policy_accepted = privacy_policy_accepted
    user.privacy_policy_version = privacy_policy_version
    user.pool_import_status = None
    user.pool_import_started_at = None
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
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
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
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
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
            privacy_policy_accepted=True,
            privacy_policy_version="1.0",
        )
        app.dependency_overrides[get_current_user] = lambda: user

        with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
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
    "pool_import_status",
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

        with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
            resp = client.get("/api/me")

        assert resp.status_code == 200
        assert set(resp.json()) == PROFILE_FIELDS

    def test_response_carries_the_profile_values(self):
        """Guards the allow-list assertion against passing on an empty profile."""
        user = _user_row_with_tokens()
        app.dependency_overrides[get_current_user] = lambda: user

        with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
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

        with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
            resp = client.get("/api/me")

        assert resp.status_code == 200
        for sentinel in TOKEN_SENTINELS:
            assert sentinel not in resp.text
        assert EXPIRY_SENTINEL_YEAR not in resp.text


# ---------------------------------------------------------------------------
# GET /api/me/export — GDPR Art. 15 / 20
# ---------------------------------------------------------------------------


class TestExportMyData:
    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_export_requires_auth(self):
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/me/export")
        assert resp.status_code == 401

    def test_export_returns_json_attachment(self):
        user = _make_user()
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: AsyncMock()
        payload = {"format_version": 1, "profile": {"id": "x"}}

        with patch(
            "backend.routers.users.export_user_data", new=AsyncMock(return_value=payload)
        ) as mock_export:
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/api/me/export")

        assert resp.status_code == 200
        assert "application/json" in resp.headers["content-type"]
        disposition = resp.headers["content-disposition"]
        assert "attachment" in disposition
        assert "filmduel_data_export.json" in disposition
        assert resp.json() == payload
        mock_export.assert_awaited_once()
        assert mock_export.await_args.args[1] is user

    def test_export_does_not_require_consent(self):
        """Right of access is independent of consent — the route must not use require_consent."""
        user = _make_user(privacy_policy_accepted=False, privacy_policy_version=None)
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: AsyncMock()

        with patch(
            "backend.routers.users.export_user_data",
            new=AsyncMock(return_value={"format_version": 1}),
        ) as mock_export:
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/api/me/export")

        assert resp.status_code == 200
        mock_export.assert_awaited_once()


# ---------------------------------------------------------------------------
# Owner access to and erasure of their own feedback reports (#791)
# ---------------------------------------------------------------------------


def _where_sql(stmt) -> str:
    return str(stmt.whereclause.compile(compile_kwargs={"literal_binds": True}))


def _assert_owner_scoped(stmt, report_id, user):
    where = _where_sql(stmt)
    assert f"feedback_reports.id = '{report_id.hex}'" in where
    assert f"feedback_reports.user_id = '{user.id.hex}'" in where


class _OwnerFeedbackRoutes:
    @pytest.fixture(autouse=True)
    def _isolate(self):
        app.dependency_overrides.clear()
        limiter.reset()
        yield
        app.dependency_overrides.clear()
        limiter.reset()

    def _client(self, user, db):
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: db
        return TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False)

    def _db(self, *, rows=None, one=None, rowcount=1):
        result = MagicMock()
        result.all.return_value = rows or []
        result.one_or_none.return_value = one
        result.rowcount = rowcount
        db = AsyncMock()
        db.execute.return_value = result
        return db


class TestListMyFeedback(_OwnerFeedbackRoutes):
    def test_lists_only_own_metadata_without_ciphertext(self):
        user = _make_user()
        row = MagicMock(
            id=uuid.uuid4(), title="Bug", description="Broke",
            created_at=datetime.now(timezone.utc), purge_after=None,
            has_screenshot=True,
        )
        db = self._db(rows=[row])
        with patch("backend.routers.feedback.decrypt_token") as mock_decrypt:
            with self._client(user, db) as client:
                resp = client.get("/api/me/feedback")

        assert resp.status_code == 200
        assert resp.json()[0]["id"] == str(row.id)
        assert resp.json()[0]["has_screenshot"] is True
        assert "user_id" not in resp.json()[0]
        mock_decrypt.assert_not_called()
        stmt = db.execute.call_args.args[0]
        names = [c.name for c in stmt.selected_columns]
        assert "screenshot_data_enc" not in names
        assert f"feedback_reports.user_id = '{user.id.hex}'" in _where_sql(stmt)

    def test_works_without_current_consent(self):
        user = _make_user(privacy_policy_accepted=False, privacy_policy_version=None)
        with self._client(user, self._db()) as client:
            assert client.get("/api/me/feedback").status_code == 200

    def test_rejects_page_over_100(self):
        with self._client(_make_user(), self._db()) as client:
            resp = client.get("/api/me/feedback", params={"limit": 101})
        assert resp.status_code == 422


class TestViewMyScreenshot(_OwnerFeedbackRoutes):
    PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16

    def _stored(self):
        return encrypt_token("data:image/png;base64," + base64.b64encode(self.PNG).decode())

    def _get(self, user, db, report_id):
        with self._client(user, db) as client:
            return client.get(f"/api/me/feedback/{report_id}/screenshot")

    def test_owner_gets_raw_image(self):
        user, report_id = _make_user(), uuid.uuid4()
        db = self._db(one=MagicMock(screenshot_data_enc=self._stored()))
        resp = self._get(user, db, report_id)

        assert resp.status_code == 200
        assert resp.content == self.PNG
        assert resp.headers["content-type"] == "image/png"
        assert resp.headers["cache-control"] == "no-store"
        _assert_owner_scoped(db.execute.call_args.args[0], report_id, user)

    def test_works_without_current_consent(self):
        user = _make_user(privacy_policy_accepted=False, privacy_policy_version=None)
        db = self._db(one=MagicMock(screenshot_data_enc=self._stored()))
        assert self._get(user, db, uuid.uuid4()).status_code == 200

    def test_export_link_reaches_this_route(self):
        report_id = uuid.uuid4()
        link = FEEDBACK_SCREENSHOT_PATH.format(report_id=report_id)
        with self._client(_make_user(), self._db(one=None)) as client:
            assert app.url_path_for("view_my_screenshot", report_id=report_id) == link
            assert client.get(link).json()["detail"] == "Report not found"

    def test_missing_or_foreign_report_is_not_found(self):
        resp = self._get(_make_user(), self._db(one=None), uuid.uuid4())
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Report not found"

    @pytest.mark.parametrize(
        "stored",
        [None, "not-a-valid-ciphertext", "data:image/png;base64,@@@"],
        ids=["no-screenshot", "corrupt-ciphertext", "corrupt-data-url"],
    )
    def test_unreadable_screenshot_is_not_found(self, stored):
        if stored and stored.startswith("data:"):
            stored = encrypt_token(stored)
        db = self._db(one=MagicMock(screenshot_data_enc=stored))
        resp = self._get(_make_user(), db, uuid.uuid4())
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Screenshot not found"


class TestDeleteMyFeedback(_OwnerFeedbackRoutes):
    def _db(self, *, age):
        db = AsyncMock()
        db.scalar.return_value = (
            None if age is None else datetime.now(timezone.utc) - age
        )
        return db

    def _delete(self, user, db, report_id):
        with self._client(user, db) as client:
            return client.delete(f"/api/me/feedback/{report_id}")

    def test_owner_deletes_report_older_than_cap_window(self):
        user, report_id = _make_user(), uuid.uuid4()
        db = self._db(age=timedelta(hours=25))
        resp = self._delete(user, db, report_id)

        assert resp.status_code == 204
        _assert_owner_scoped(db.scalar.call_args.args[0], report_id, user)
        stmt = db.execute.call_args.args[0]
        assert isinstance(stmt, sa.Delete)
        _assert_owner_scoped(stmt, report_id, user)

    def test_report_inside_cap_window_is_kept(self):
        """Deleting a recent report would free a slot under MAX_FEEDBACK_PER_DAY."""
        db = self._db(age=timedelta(hours=23))
        resp = self._delete(_make_user(), db, uuid.uuid4())

        assert resp.status_code == 409
        db.execute.assert_not_called()

    def test_works_without_current_consent(self):
        user = _make_user(privacy_policy_accepted=False, privacy_policy_version=None)
        db = self._db(age=timedelta(hours=25))
        assert self._delete(user, db, uuid.uuid4()).status_code == 204

    def test_missing_or_foreign_report_is_not_found(self):
        db = self._db(age=None)
        resp = self._delete(_make_user(), db, uuid.uuid4())
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Report not found"
        db.execute.assert_not_called()


# ---------------------------------------------------------------------------
# Background pool import (#653)
# ---------------------------------------------------------------------------


def _session_factory(session):
    @asynccontextmanager
    async def factory():
        yield session

    return factory


class TestRunPoolImport:
    STARTED_AT = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)

    @staticmethod
    def _recorded(session):
        (stmt,) = [c.args[0] for c in session.execute.await_args_list]
        return stmt.compile().params

    @pytest.mark.asyncio
    @pytest.mark.parametrize("complete, status", [(True, "complete"), (False, "failed")])
    async def test_records_outcome_of_the_sync(self, complete, status):
        user = _make_user()
        session = AsyncMock()
        session.get.return_value = user

        with (
            patch("backend.routers.users.async_session_factory", _session_factory(session)),
            patch(
                "backend.routers.users._force_pool_sync",
                new=AsyncMock(return_value=(user, complete)),
            ),
        ):
            await _run_pool_import(user.id, self.STARTED_AT)

        params = self._recorded(session)
        assert params["pool_import_status"] == status
        assert params["pool_import_started_at_1"] == self.STARTED_AT
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_marks_failed_when_the_sync_raises(self):
        user = _make_user()
        session = AsyncMock()
        session.get.return_value = user

        with (
            patch("backend.routers.users.async_session_factory", _session_factory(session)),
            patch(
                "backend.routers.users._force_pool_sync",
                new=AsyncMock(side_effect=httpx.ReadTimeout("slow")),
            ),
        ):
            await _run_pool_import(user.id, self.STARTED_AT)

        params = self._recorded(session)
        assert params["pool_import_status"] == "failed"
        assert params["pool_import_started_at_1"] == self.STARTED_AT
        session.commit.assert_awaited_once()


class TestRecordPoolImportOutcome:
    @pytest.fixture
    def users_session(self):
        engine = sa.create_engine("sqlite://")
        User.__table__.create(engine)
        with Session(engine) as session:
            yield session

    def test_superseded_run_does_not_overwrite_the_current_one(self, users_session):
        first_started = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
        retry_started = first_started + timedelta(minutes=21)
        user = User(
            trakt_username="u",
            pool_import_status="importing",
            pool_import_started_at=retry_started,
        )
        users_session.add(user)
        users_session.commit()

        users_session.execute(_record_pool_import_outcome(user.id, first_started, "failed"))
        users_session.refresh(user)
        assert user.pool_import_status == "importing"

        users_session.execute(_record_pool_import_outcome(user.id, retry_started, "complete"))
        users_session.refresh(user)
        assert user.pool_import_status == "complete"


class TestEffectivePoolImportStatus:
    def _user(self, status, started_ago):
        user = _make_user()
        user.pool_import_status = status
        user.pool_import_started_at = datetime.now(timezone.utc) - started_ago
        return user

    def test_fresh_import_is_importing(self):
        user = self._user("importing", timedelta(minutes=1))
        assert _effective_pool_import_status(user) == "importing"

    def test_stale_import_is_failed(self):
        user = self._user("importing", timedelta(minutes=21))
        assert _effective_pool_import_status(user) == "failed"

    def test_final_states_pass_through(self):
        for status in ("complete", "failed", None):
            user = self._user(status, timedelta(days=1))
            assert _effective_pool_import_status(user) == status


class TestRetryPoolImport:
    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _post(self, user, db):
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: db
        with patch(
            "backend.routers.users._run_pool_import", new_callable=AsyncMock
        ) as mock_job, patch("backend.routers.users.backfill_posters_background"):
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.post("/api/me/pool-import")
        return resp, mock_job

    def test_failed_import_is_restarted(self):
        user = _make_user()
        user.use_ai_features = True
        user.pool_import_status = "failed"
        user.pool_import_started_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db = AsyncMock()

        resp, mock_job = self._post(user, db)

        assert resp.status_code == 200
        assert resp.json()["pool_import_status"] == "importing"
        db.commit.assert_awaited_once()
        mock_job.assert_awaited_once_with(user.id, user.pool_import_started_at)

    def test_running_import_is_not_restarted(self):
        user = _make_user()
        user.use_ai_features = True
        user.pool_import_status = "importing"
        user.pool_import_started_at = datetime.now(timezone.utc)
        db = AsyncMock()

        resp, mock_job = self._post(user, db)

        assert resp.status_code == 200
        assert resp.json()["pool_import_status"] == "importing"
        db.commit.assert_not_awaited()
        mock_job.assert_not_awaited()
