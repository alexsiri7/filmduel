"""Tests for POST /api/feedback endpoint."""
from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone
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
    report.screenshot_data = kwargs.get("screenshot_data", None)
    return report


@pytest.fixture
def client():
    return TestClient(app)


class TestSubmitFeedback:
    def _post(self, client, title="Bug", description="Details", screenshot=None, content_type="image/jpeg", user=None, db=None):
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

            with patch("backend.routers.feedback.FeedbackReport", side_effect=make_report):
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
        small_image = b'\xff\xd8\xff' + b'\x00' * 100  # valid JPEG magic bytes
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

    def test_screenshot_stored_as_base64_data_url_with_correct_mime(self, client):
        jpeg_data = b'\xff\xd8\xff' + b'\x00' * 10  # valid JPEG magic bytes
        response = self._post(client, screenshot=io.BytesIO(jpeg_data), content_type="image/jpeg")
        report = response._created_reports[0]
        assert report.screenshot_data.startswith("data:image/jpeg;base64,")

    def test_png_screenshot_stored_with_png_mime(self, client):
        png_data = b'\x89PNG\r\n\x1a\n' + b'\x00' * 10  # valid PNG magic bytes
        response = self._post(client, screenshot=io.BytesIO(png_data), content_type="image/png")
        report = response._created_reports[0]
        assert report.screenshot_data.startswith("data:image/png;base64,")

    def test_no_screenshot_stores_none(self, client):
        response = self._post(client)
        report = response._created_reports[0]
        assert report.screenshot_data is None
