"""Tests for the SPA catch-all route (spa_fallback)."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

import backend.main as main_module
from backend.main import app

client = TestClient(app)


def test_root_returns_503_when_dist_missing(tmp_path):
    """Route must be registered even when frontend/dist doesn't exist."""
    missing = tmp_path / "nonexistent"
    with patch.object(main_module, "STATIC_DIR", missing):
        response = client.get("/")
    assert response.status_code == 503
    assert response.json() == {"detail": "Frontend not available"}


def test_spa_fallback_returns_503_for_unknown_path_when_dist_missing(tmp_path):
    """Any SPA route must return 503 when dist is missing, not 404."""
    missing = tmp_path / "nonexistent"
    with patch.object(main_module, "STATIC_DIR", missing):
        response = client.get("/some/deep/route")
    assert response.status_code == 503
    assert response.json() == {"detail": "Frontend not available"}


def test_root_returns_503_when_index_html_missing(tmp_path):
    """Dist dir exists but no index.html must return 503, not 404."""
    dist = tmp_path / "dist"
    dist.mkdir()
    with patch.object(main_module, "STATIC_DIR", dist):
        response = client.get("/")
    assert response.status_code == 503
    assert response.json() == {"detail": "Frontend not available"}


def test_spa_fallback_returns_503_for_unknown_path_when_index_html_missing(tmp_path):
    """Any SPA route must return 503 when index.html is missing, not 404."""
    dist = tmp_path / "dist"
    dist.mkdir()
    with patch.object(main_module, "STATIC_DIR", dist):
        response = client.get("/some/deep/route")
    assert response.status_code == 503
    assert response.json() == {"detail": "Frontend not available"}


def test_spa_fallback_serves_index_html_for_spa_route(tmp_path):
    """Non-file SPA routes (e.g. /login) must serve index.html."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>app</html>")
    with patch.object(main_module, "STATIC_DIR", dist):
        response = client.get("/login")
    assert response.status_code == 200


def test_spa_fallback_serves_static_file_when_it_exists(tmp_path):
    """Requests for existing static files must return the file directly."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>app</html>")
    static_file = dist / "favicon.ico"
    static_file.write_bytes(b"\x00")
    with patch.object(main_module, "STATIC_DIR", dist):
        response = client.get("/favicon.ico")
    assert response.status_code == 200


def test_path_traversal_is_blocked(tmp_path):
    """Path traversal attempts must not serve files outside frontend/dist."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>app</html>")
    sensitive = tmp_path / "secret.txt"
    sensitive.write_text("SECRET")

    with patch.object(main_module, "STATIC_DIR", dist):
        response = client.get("/../secret.txt")
    assert response.status_code == 200
    assert "SECRET" not in response.text


def test_sibling_directory_is_blocked_via_symlink(tmp_path):
    """A symlink inside dist pointing to a sibling directory must not be followed."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>app</html>")
    sibling = tmp_path / "dist-sibling"
    sibling.mkdir()
    (sibling / "secret.txt").write_text("SECRET")

    # Symlink inside dist pointing to the sibling — this is the actual attack vector
    # that the startswith → is_relative_to fix addresses.
    (dist / "link").symlink_to("../dist-sibling")

    with patch.object(main_module, "STATIC_DIR", dist):
        response = client.get("/link/secret.txt")
    assert response.status_code == 200
    assert "SECRET" not in response.text
    assert "app" in response.text


def test_log_injection_newlines_are_escaped(tmp_path, caplog):
    """Newlines in full_path must be escaped before logging to prevent log injection."""
    import logging

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>app</html>")
    # Place a file outside dist to trigger the out-of-bounds warning
    outside = tmp_path / "outside.txt"
    outside.write_text("OUTSIDE")
    # Symlink inside dist pointing outside to trigger the warning log
    (dist / "escape").symlink_to("../outside.txt")

    with patch.object(main_module, "STATIC_DIR", dist):
        with caplog.at_level(logging.WARNING, logger="backend.main"):
            client.get("/escape%0a%0dFAKE_LOG_LINE")

    # The literal newline/CR must not appear in the log record
    for record in caplog.records:
        assert "\n" not in record.getMessage()
        assert "\r" not in record.getMessage()
