"""Tests for POST /api/feedback endpoint."""

from __future__ import annotations

import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests!!")
os.environ.setdefault("TOKEN_ENC_KEY", "dGVzdC1lbmMta2V5LWZvci11bml0LXRlc3RzITEhMTIzNA==")

import io
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.db import get_db
from backend.main import app
from backend.routers.auth import get_current_user


def _make_user():
    user = MagicMock()
    user.id = uuid.uuid4()
    return user


def _make_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


def _make_feedback_report(**kwargs):
    """Return a FeedbackReport-like object with valid id and created_at."""
    report = MagicMock()
    report.id = kwargs.get("id", uuid.uuid4())
    report.created_at = kwargs.get("created_at", datetime.now(timezone.utc))
    report.title = kwargs.get("title", "")
    report.description = kwargs.get("description", "")
    report.screenshot_data_enc = kwargs.get("screenshot_data_enc", None)
    report.purge_after = kwargs.get("purge_after", None)
    return report


@pytest.fixture
def client():
    return TestClient(app)


class TestSubmitFeedback:
    def _post(
        self,
        client,
        title="Bug",
        description="Details",
        screenshot=None,
        content_type="image/jpeg",
        user=None,
        db=None,
    ):
        user = user or _make_user()
        db = db or _make_db()

        # Capture what arguments FeedbackReport was called with
        created_reports = []

        def make_report(**kwargs):
            report = _make_feedback_report(**kwargs)
            created_reports.append(report)
            return report

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: db

        try:
            data = {"title": title, "description": description}
            files = {}
            if screenshot is not None:
                files = {"screenshot": ("screenshot.jpg", screenshot, content_type)}

            with patch(
                "backend.routers.feedback.FeedbackReport", side_effect=make_report
            ):
                response = client.post("/api/feedback", data=data, files=files)

            response._created_reports = created_reports
            response._db = db
            return response
        finally:
            app.dependency_overrides.clear()

    def test_returns_201_without_screenshot(self, client):
        response = self._post(client)
        assert response.status_code == 201

    def test_response_contains_id_and_created_at(self, client):
        response = self._post(client)
        body = response.json()
        assert "id" in body
        assert "created_at" in body

    def test_strips_whitespace_from_title_and_description(self, client):
        response = self._post(client, title="  Bug  ", description="  Details  ")
        report = response._created_reports[0]
        assert report.title == "Bug"
        assert report.description == "Details"

    def test_accepts_screenshot_within_size_limit(self, client):
        small_image = b"\xff\xd8\xff" + b"\x00" * 100  # valid JPEG magic bytes
        response = self._post(client, screenshot=io.BytesIO(small_image))
        assert response.status_code == 201

    def test_rejects_screenshot_over_5mb(self, client):
        oversized = b"x" * (5 * 1024 * 1024 + 1)
        response = self._post(client, screenshot=io.BytesIO(oversized))
        assert response.status_code == 413
        assert "5 MB" in response.json()["detail"]

    def test_rejects_non_image_content_type(self, client):
        response = self._post(
            client,
            screenshot=io.BytesIO(b"not-an-image"),
            content_type="application/pdf",
        )
        assert response.status_code == 415
        assert "image" in response.json()["detail"].lower()

    def test_screenshot_stored_encrypted(self, client):
        from backend.services.token_crypto import decrypt_token

        jpeg_data = b"\xff\xd8\xff" + b"\x00" * 10  # valid JPEG magic bytes
        response = self._post(
            client, screenshot=io.BytesIO(jpeg_data), content_type="image/jpeg"
        )
        report = response._created_reports[0]
        # Stored value is Fernet ciphertext, not raw base64
        assert report.screenshot_data_enc is not None
        assert not report.screenshot_data_enc.startswith("data:")
        # Decrypted value is the original data URL
        decrypted = decrypt_token(report.screenshot_data_enc)
        assert decrypted.startswith("data:image/jpeg;base64,")

    def test_png_screenshot_stored_encrypted_with_png_mime(self, client):
        from backend.services.token_crypto import decrypt_token

        png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10  # valid PNG magic bytes
        response = self._post(
            client, screenshot=io.BytesIO(png_data), content_type="image/png"
        )
        report = response._created_reports[0]
        assert report.screenshot_data_enc is not None
        decrypted = decrypt_token(report.screenshot_data_enc)
        assert decrypted.startswith("data:image/png;base64,")

    def test_no_screenshot_stores_none(self, client):
        response = self._post(client)
        report = response._created_reports[0]
        assert report.screenshot_data_enc is None

    def test_purge_after_set_to_90_days(self, client):
        jpeg_data = b"\xff\xd8\xff" + b"\x00" * 10
        response = self._post(
            client, screenshot=io.BytesIO(jpeg_data), content_type="image/jpeg"
        )
        report = response._created_reports[0]
        assert report.purge_after is not None
        diff = report.purge_after - datetime.now(timezone.utc)
        assert timedelta(days=89) < diff <= timedelta(days=91)

    def test_purge_after_is_none_when_no_screenshot(self, client):
        # purge_after should only be set when a screenshot is present (TTL applies to screenshot lifecycle)
        response = self._post(client)
        report = response._created_reports[0]
        assert report.screenshot_data_enc is None
        assert report.purge_after is None


class TestAdminListFeedback:
    def _get(self, client, reports=None):
        user = _make_user()
        db = _make_db()
        reports = reports or []
        db.execute = AsyncMock(
            return_value=MagicMock(
                scalars=MagicMock(
                    return_value=MagicMock(all=MagicMock(return_value=reports))
                )
            )
        )
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: db
        try:
            return client.get("/api/feedback/admin")
        finally:
            app.dependency_overrides.clear()

    def test_returns_200_empty_list(self, client):
        response = self._get(client)
        assert response.status_code == 200
        assert response.json() == []

    def test_decrypts_screenshot_in_response(self, client):
        from backend.services.token_crypto import encrypt_token

        encrypted = encrypt_token("data:image/jpeg;base64,abc123")
        report = _make_feedback_report(screenshot_data_enc=encrypted)
        response = self._get(client, reports=[report])
        data = response.json()
        assert data[0]["screenshot_data"] == "data:image/jpeg;base64,abc123"

    def test_screenshot_data_null_when_none_stored(self, client):
        report = _make_feedback_report(screenshot_data_enc=None)
        response = self._get(client, reports=[report])
        assert response.json()[0]["screenshot_data"] is None

    def test_corrupted_ciphertext_returns_null_not_500(self, client):
        # A corrupted ciphertext should degrade gracefully (null screenshot) rather than crash all
        report = _make_feedback_report(screenshot_data_enc="not-valid-fernet-ciphertext")
        response = self._get(client, reports=[report])
        assert response.status_code == 200
        assert response.json()[0]["screenshot_data"] is None


class TestScrubScreenshot:
    def _delete(self, client, report_id, report_obj=None):
        user = _make_user()
        db = _make_db()
        db.execute = AsyncMock(
            return_value=MagicMock(
                scalar_one_or_none=MagicMock(return_value=report_obj)
            )
        )
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: db
        try:
            return client.delete(f"/api/feedback/admin/{report_id}/screenshot")
        finally:
            app.dependency_overrides.clear()

    def test_returns_204_and_nulls_field(self, client):
        report = _make_feedback_report(screenshot_data_enc="encrypted-data")
        response = self._delete(client, report.id, report_obj=report)
        assert response.status_code == 204
        assert report.screenshot_data_enc is None

    def test_returns_404_when_report_not_found(self, client):
        response = self._delete(client, uuid.uuid4(), report_obj=None)
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


class TestPurgeExpiredScreenshots:
    def _delete(self, client, purged_ids=None):
        user = _make_user()
        db = _make_db()
        purged_ids = purged_ids or []
        db.execute = AsyncMock(
            return_value=MagicMock(fetchall=MagicMock(return_value=[(pid,) for pid in purged_ids]))
        )
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: db
        try:
            return client.delete("/api/feedback/admin/purge-expired-screenshots")
        finally:
            app.dependency_overrides.clear()

    def test_returns_purged_count(self, client):
        purged = [uuid.uuid4(), uuid.uuid4()]
        response = self._delete(client, purged_ids=purged)
        assert response.status_code == 200
        assert response.json() == {"purged": 2}

    def test_returns_zero_when_nothing_to_purge(self, client):
        response = self._delete(client, purged_ids=[])
        assert response.status_code == 200
        assert response.json() == {"purged": 0}
