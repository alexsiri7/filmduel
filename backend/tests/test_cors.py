"""Integration tests for CORS middleware configuration."""

import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests!!")

from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_cors_preflight_allows_content_type_header():
    """Verify allow_headers=["Content-Type"] is reflected in CORS preflight response."""
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )
    assert response.status_code == 200
    assert "content-type" in response.headers.get(
        "access-control-allow-headers", ""
    ).lower()


def test_cors_preflight_allows_x_requested_with_header():
    """Verify X-Requested-With is reflected in CORS preflight response."""
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-Requested-With",
        },
    )
    assert response.status_code == 200
    assert "x-requested-with" in response.headers.get(
        "access-control-allow-headers", ""
    ).lower()
