"""Tests for the Sentry event, transaction, and breadcrumb scrubbing hooks."""

from __future__ import annotations

import os
import uuid

# Must set SECRET_KEY before importing backend.main — pydantic Settings validates it at import time.
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests!!")

import httpx  # noqa: E402
import pytest  # noqa: E402
import sentry_sdk  # noqa: E402
from sentry_sdk.integrations.httpx import HttpxIntegration  # noqa: E402
from sentry_sdk.transport import Transport  # noqa: E402

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.main import (  # noqa: E402
    SENTRY_OPTIONS,
    _redact_url,
    _scrub_breadcrumb,
    _scrub_event,
)


class TestRedactUrl:
    def test_query_string_is_dropped(self):
        url = "https://api.themoviedb.org/3/movie/550?api_key=SECRET&language=en"
        assert _redact_url(url) == "https://api.themoviedb.org/3/movie/550"

    def test_fragment_is_dropped(self):
        assert _redact_url("https://example.com/a#frag") == "https://example.com/a"

    def test_users_path_segment_is_masked(self):
        url = "https://api.trakt.tv/users/alice-smith/watched/movies"
        assert _redact_url(url) == "https://api.trakt.tv/users/[Filtered]/watched/movies"

    def test_span_description_is_redacted(self):
        assert (
            _redact_url("GET https://api.trakt.tv/users/alice/ratings/shows")
            == "GET https://api.trakt.tv/users/[Filtered]/ratings/shows"
        )

    def test_plain_url_is_unchanged(self):
        assert _redact_url("https://api.trakt.tv/movies/popular") == (
            "https://api.trakt.tv/movies/popular"
        )


class TestScrubBreadcrumb:
    def test_http_breadcrumb_url_and_query_are_scrubbed(self):
        crumb = {
            "type": "http",
            "category": "httplib",
            "data": {
                "http.method": "GET",
                "url": "https://api.trakt.tv/users/alice/watched/movies",
                "http.query": "api_key=SECRET",
                "http.fragment": "",
            },
        }
        result = _scrub_breadcrumb(crumb, {})
        assert result["data"] == {
            "http.method": "GET",
            "url": "https://api.trakt.tv/users/[Filtered]/watched/movies",
        }

    def test_breadcrumb_without_data_passes_through(self):
        crumb = {"category": "query", "message": "SELECT 1"}
        assert _scrub_breadcrumb(crumb, {}) == {"category": "query", "message": "SELECT 1"}


class TestScrubEvent:
    def test_oauth_callback_query_string_is_dropped(self):
        event = {
            "request": {
                "url": "https://filmduel.up.railway.app/auth/callback",
                "query_string": "code=AUTHCODE&state=STATE",
                "method": "GET",
            }
        }
        result = _scrub_event(event, {})
        assert "query_string" not in result["request"]
        assert result["request"]["url"] == "https://filmduel.up.railway.app/auth/callback"

    def test_outgoing_span_urls_are_scrubbed(self):
        event = {
            "type": "transaction",
            "spans": [
                {
                    "op": "http.client",
                    "description": "GET https://api.trakt.tv/users/alice/watched/movies",
                    "data": {
                        "url": "https://api.themoviedb.org/3/movie/550",
                        "http.query": "api_key=SECRET",
                        "http.fragment": "",
                    },
                },
                {"op": "db", "description": "SELECT 1"},
            ],
        }
        result = _scrub_event(event, {})
        http_span, db_span = result["spans"]
        assert http_span["description"] == (
            "GET https://api.trakt.tv/users/[Filtered]/watched/movies"
        )
        assert http_span["data"] == {"url": "https://api.themoviedb.org/3/movie/550"}
        assert db_span == {"op": "db", "description": "SELECT 1"}

    def test_event_without_request_passes_through(self):
        event = {"message": "hello", "level": "info"}
        assert _scrub_event(event, {}) == {"message": "hello", "level": "info"}


_TMDB_KEY = "tmdb-key-value"
_TRAKT_USER = "alice-smith"


class _CapturingTransport(Transport):
    def __init__(self, options=None):
        super().__init__(options)
        self.envelopes = []

    def capture_envelope(self, envelope):
        self.envelopes.append(envelope)


@pytest.fixture
def sentry_events():
    """Run a real Sentry client with the app's options and capture what it would send."""
    transport = _CapturingTransport()
    sentry_sdk.init(
        dsn="https://public@sentry.invalid/1",
        transport=transport,
        integrations=[HttpxIntegration()],
        **SENTRY_OPTIONS,
    )
    try:
        yield transport
    finally:
        sentry_sdk.get_client().close()
        sentry_sdk.init()


def _sent_payload(transport: _CapturingTransport) -> bytes:
    sentry_sdk.flush()
    return b"".join(
        item.payload.get_bytes() for env in transport.envelopes for item in env.items
    )


def test_real_sdk_event_carries_no_provider_secrets(sentry_events):
    """The SDK's own httpx breadcrumbs must reach the transport already scrubbed."""
    client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200)))
    client.get(f"https://api.themoviedb.org/3/movie/550?api_key={_TMDB_KEY}")
    client.get(f"https://api.trakt.tv/users/{_TRAKT_USER}/watched/movies")

    def _fail(profile):
        raise RuntimeError("boom")

    try:
        _fail({"user": {"username": _TRAKT_USER}})
    except RuntimeError:
        sentry_sdk.capture_exception()

    payload = _sent_payload(sentry_events)
    assert b"breadcrumbs" in payload
    assert b"api.themoviedb.org/3/movie/550" in payload
    assert _TMDB_KEY.encode() not in payload
    assert _TRAKT_USER.encode() not in payload


def test_real_sdk_event_carries_no_request_body(sentry_events):
    """A request that crashes after reading its body must not ship the body to Sentry."""
    app = FastAPI()

    @app.post("/feedback")
    async def _submit(request: Request):
        await request.json()
        raise RuntimeError("boom")

    # Generated so the marker can't reach the payload via the frames' source context.
    body_marker = f"private-feedback-{uuid.uuid4()}"
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/feedback", json={"message": body_marker})
    assert response.status_code == 500

    assert body_marker.encode() not in _sent_payload(sentry_events)
    (event,) = [
        item.payload.json
        for env in sentry_events.envelopes
        for item in env.items
        if item.type == "event"
    ]
    assert event["request"]["url"].endswith("/feedback")
    assert not event["request"].get("data")
