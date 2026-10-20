"""Tests for the CSP violation report endpoint (SEC-27, #799)."""

from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _capture_warnings(caplog):
    caplog.set_level(logging.WARNING)


def test_legacy_report_is_logged_without_query_strings(caplog):
    body = {
        "csp-report": {
            "document-uri": "https://filmduel.example/auth/callback?code=SECRET&state=XYZ",
            "referrer": "https://filmduel.example/?code=SECRET",
            "violated-directive": "script-src-elem",
            "effective-directive": "script-src",
            "blocked-uri": "https://evil.example/x.js?t=1",
        }
    }
    # A foreign Origin and no X-Requested-With: the CSRF check must not apply.
    r = client.post(
        "/api/csp-report",
        content=json.dumps(body),
        headers={"Content-Type": "application/csp-report", "Origin": "https://evil.example"},
    )
    assert r.status_code == 204
    assert "csp_violation" in caplog.text
    assert "'script-src'" in caplog.text
    assert "'https://evil.example'" in caplog.text
    assert "'/auth/callback'" in caplog.text
    assert "SECRET" not in caplog.text
    assert "state=" not in caplog.text
    assert "t=1" not in caplog.text


def test_reporting_api_report_is_logged(caplog):
    body = [
        {
            "type": "csp-violation",
            "body": {
                "documentURL": "https://filmduel.example/duel?pair=TOKEN",
                "effectiveDirective": "img-src",
                "blockedURL": "https://tracker.example/pixel.gif",
            },
        },
        {"type": "deprecation", "body": {"message": "ignored"}},
    ]
    r = client.post(
        "/api/csp-report",
        content=json.dumps(body),
        headers={"Content-Type": "application/reports+json"},
    )
    assert r.status_code == 204
    lines = [rec.getMessage() for rec in caplog.records if "csp_violation" in rec.getMessage()]
    assert lines == [
        "csp_violation directive='img-src' blocked='https://tracker.example' document='/duel'"
    ]


def test_inline_violation_keeps_keyword(caplog):
    body = {"csp-report": {"effective-directive": "script-src-elem", "blocked-uri": "inline"}}
    client.post(
        "/api/csp-report",
        content=json.dumps(body),
        headers={"Content-Type": "application/csp-report"},
    )
    assert "blocked='inline'" in caplog.text


def test_logs_at_most_ten_reports_per_request(caplog):
    report = {"type": "csp-violation", "body": {"effectiveDirective": "img-src"}}
    client.post(
        "/api/csp-report",
        content=json.dumps([report] * 50),
        headers={"Content-Type": "application/reports+json"},
    )
    assert caplog.text.count("csp_violation") == 10


@pytest.mark.parametrize("content", [b"not json", b'{"other": 1}', b"\xff\xfe", b"42"])
def test_malformed_body_is_accepted_silently(caplog, content):
    r = client.post(
        "/api/csp-report",
        content=content,
        headers={"Content-Type": "application/csp-report"},
    )
    assert r.status_code == 204
    assert "csp_violation" not in caplog.text


@pytest.mark.parametrize(
    "content",
    [
        b'{"csp-report": {"blocked-uri": "http://[::1"}}',
        b'[{"type": "csp-violation", "body": {"documentURL": "https://[x/"}}]',
    ],
)
def test_unparseable_url_is_logged_empty(caplog, content):
    r = client.post(
        "/api/csp-report",
        content=content,
        headers={"Content-Type": "application/csp-report"},
    )
    assert r.status_code == 204
    assert "csp_violation" in caplog.text
    assert "[" not in caplog.text


def test_csrf_exemption_is_limited_to_the_report_path():
    r = client.post("/api/duels", json={}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
