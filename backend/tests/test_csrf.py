"""Tests for CSRF Origin/Referer middleware."""

import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests!!")

from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_get_skips_csrf_check():
    """GET requests are never blocked."""
    response = client.get("/health")
    assert response.status_code != 403


def test_post_blocked_unknown_origin():
    """POST from unknown origin without X-Requested-With is rejected."""
    response = client.post(
        "/api/duels",
        json={"winner_id": 1, "loser_id": 2},
        headers={"Origin": "https://attacker.example.com"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "CSRF check failed: unexpected origin"


def test_post_allowed_with_x_requested_with():
    """POST with X-Requested-With header is allowed regardless of origin."""
    response = client.post(
        "/api/duels",
        json={"winner_id": 1, "loser_id": 2},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    # Should reach route (may fail for other reasons, but not 403)
    assert response.status_code != 403


def test_post_allowed_known_origin():
    """POST from allowed origin passes CSRF check."""
    response = client.post(
        "/api/duels",
        json={"winner_id": 1, "loser_id": 2},
        headers={"Origin": "http://localhost:5173"},
    )
    assert response.status_code != 403


def test_post_no_origin_allowed():
    """POST with no Origin header (CLI/API client) is allowed through."""
    response = client.post(
        "/api/duels",
        json={"winner_id": 1, "loser_id": 2},
    )
    assert response.status_code != 403


def test_feedback_multipart_blocked_unknown_origin():
    """Multipart feedback POST from unknown origin is blocked."""
    response = client.post(
        "/api/feedback",
        data={"title": "test", "description": "test"},
        headers={"Origin": "https://attacker.example.com"},
    )
    assert response.status_code == 403


def test_feedback_multipart_allowed_with_header():
    """Multipart feedback POST with X-Requested-With is allowed."""
    response = client.post(
        "/api/feedback",
        data={"title": "test", "description": "test"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert response.status_code != 403
