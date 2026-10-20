"""SEC-03: request bodies are bounded before they are read."""

from __future__ import annotations

import io

from fastapi.testclient import TestClient

from backend.main import app
from backend.middleware.body_limit import (
    DEFAULT_MAX_BODY_BYTES,
    FEEDBACK_MAX_BODY_BYTES,
    BodyLimitMiddleware,
)
from backend.tests import SPA_HEADERS


def test_middleware_is_registered():
    classes = [m.cls for m in app.user_middleware]
    assert BodyLimitMiddleware in classes


def test_limit_for_prefers_longest_prefix():
    mw = BodyLimitMiddleware(app=None)
    assert mw.limit_for("/api/feedback") == FEEDBACK_MAX_BODY_BYTES
    assert mw.limit_for("/api/feedback/123") == FEEDBACK_MAX_BODY_BYTES
    assert mw.limit_for("/api/feedbackx") == DEFAULT_MAX_BODY_BYTES
    assert mw.limit_for("/api/duels") == DEFAULT_MAX_BODY_BYTES


def test_oversized_json_is_rejected_before_auth():
    """No cookie: the 413 must arrive before the route's 401 would."""
    body = b'{"x":"' + b"a" * (DEFAULT_MAX_BODY_BYTES + 1) + b'"}'
    with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
        resp = client.post(
            "/api/duels", content=body, headers={"Content-Type": "application/json"}
        )
    assert resp.status_code == 413


def test_oversized_multipart_is_rejected_before_auth():
    blob = io.BytesIO(b"\x89PNG" + b"\0" * (FEEDBACK_MAX_BODY_BYTES + 1))
    with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
        resp = client.post(
            "/api/feedback",
            data={"title": "x", "description": "x"},
            files={"screenshot": ("a.png", blob, "image/png")},
        )
    assert resp.status_code == 413


def test_chunked_body_is_cut_off_at_limit():
    """Under-declared / chunked bodies are stopped by the wrapped receive."""

    def gen():
        for _ in range(4):
            yield b"a" * (DEFAULT_MAX_BODY_BYTES // 2)

    with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
        resp = client.post(
            "/api/duels",
            content=gen(),
            headers={"Content-Type": "application/json", "Transfer-Encoding": "chunked"},
        )
    assert resp.status_code == 413


def test_small_body_passes_through_to_auth():
    with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
        resp = client.post("/api/duels", json={"winner_id": "x", "loser_id": "y"})
    assert resp.status_code == 401  # body was read; auth rejected it as before


def test_get_is_never_limited():
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
