"""Integration tests for CORS middleware configuration."""

from __future__ import annotations

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
