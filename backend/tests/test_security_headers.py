"""Tests for security response headers set by the add_security_headers middleware."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import backend.main
from backend.config import Settings
from backend.main import app

client = TestClient(app)

_SETTINGS_DEFAULTS = {
    "SECRET_KEY": "test-secret-key-for-unit-tests!!",
    "TRAKT_CLIENT_ID": "",
    "TRAKT_CLIENT_SECRET": "",
    "DATABASE_URL": "postgresql+asyncpg://localhost/test",
}


def _make_settings(**overrides) -> Settings:
    return Settings(**{**_SETTINGS_DEFAULTS, **overrides})


@pytest.fixture(scope="module")
def response():
    return client.get("/health")


def test_csp_frame_ancestors(response):
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_csp_base_uri(response):
    assert "base-uri 'self'" in response.headers["content-security-policy"]


def test_csp_form_action(response):
    assert "form-action 'self'" in response.headers["content-security-policy"]


def test_csp_object_src(response):
    assert "object-src 'none'" in response.headers["content-security-policy"]


def test_csp_no_unsafe_inline_style(response):
    csp = response.headers["content-security-policy"]
    assert "'unsafe-inline'" not in csp


def test_permissions_policy_present(response):
    assert "permissions-policy" in response.headers


def test_permissions_policy_disables_geolocation(response):
    assert "geolocation=()" in response.headers["permissions-policy"]


class TestHSTS:
    def test_hsts_present_when_https_base_url(self, monkeypatch):
        """HSTS header emitted when BASE_URL uses https://."""
        monkeypatch.setattr(
            backend.main, "settings", _make_settings(BASE_URL="https://filmduel.example.com")
        )
        r = client.get("/health")
        assert "strict-transport-security" in r.headers

    def test_hsts_present_when_secure_cookies_proxy_override(self, monkeypatch):
        """HSTS header emitted when SECURE_COOKIES=True even with http:// BASE_URL."""
        monkeypatch.setattr(
            backend.main,
            "settings",
            _make_settings(BASE_URL="http://localhost:8000", SECURE_COOKIES=True),
        )
        r = client.get("/health")
        assert "strict-transport-security" in r.headers

    def test_hsts_absent_when_http_base_url_no_override(self, monkeypatch):
        """HSTS header not emitted for plain http:// without SECURE_COOKIES override."""
        monkeypatch.setattr(
            backend.main,
            "settings",
            _make_settings(BASE_URL="http://localhost:8000"),
        )
        r = client.get("/health")
        assert "strict-transport-security" not in r.headers
