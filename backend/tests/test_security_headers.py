"""Tests for security response headers set by the add_security_headers middleware."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


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
