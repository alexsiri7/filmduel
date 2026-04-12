"""Tests for the /health endpoint."""

from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


def test_health_returns_200():
    response = client.get("/health")
    assert response.status_code == 200


def test_health_returns_ok_status():
    response = client.get("/health")
    assert response.json() == {"status": "ok"}
