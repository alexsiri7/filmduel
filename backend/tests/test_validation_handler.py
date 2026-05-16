"""Tests for the validation error handler — ensures user input is not logged."""

from __future__ import annotations

import logging
import os
import uuid
from unittest.mock import MagicMock

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests!!")

from fastapi.testclient import TestClient

from backend.main import _scrub_validation_errors, app
from backend.routers.auth import get_current_user

client = TestClient(app)


def _make_fake_user() -> MagicMock:
    """Return a minimal fake User object sufficient for dependency override."""
    fake = MagicMock()
    fake.id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    return fake


class TestScrubValidationErrors:
    def test_input_key_is_stripped(self):
        errors = [{"type": "string_too_long", "loc": ("name",), "msg": "...", "input": "user text"}]
        result = _scrub_validation_errors(errors)
        assert "input" in errors[0], "original should be unchanged"
        assert "input" not in result[0]

    def test_other_keys_preserved(self):
        errors = [{"type": "string_too_long", "loc": ("name",), "msg": "too long", "input": "x"}]
        result = _scrub_validation_errors(errors)
        assert result[0]["type"] == "string_too_long"
        assert result[0]["loc"] == ("name",)
        assert result[0]["msg"] == "too long"

    def test_multiple_errors_all_stripped(self):
        errors = [
            {"type": "a", "input": "val1"},
            {"type": "b", "input": "val2"},
        ]
        result = _scrub_validation_errors(errors)
        assert all("input" not in e for e in result)

    def test_error_without_input_key_is_safe(self):
        errors = [{"type": "missing", "loc": ("field",), "msg": "field required"}]
        result = _scrub_validation_errors(errors)
        assert result == errors

    def test_logger_does_not_emit_raw_input(self, caplog):
        """Integration: WARNING log must not contain the raw user input."""
        fake_user = _make_fake_user()
        app.dependency_overrides[get_current_user] = lambda: fake_user
        try:
            with caplog.at_level(logging.WARNING, logger="backend.main"):
                resp = client.post(
                    "/api/tournaments",
                    json={"name": "x" * 200},  # triggers string_too_long (max_length=100)
                )
            assert resp.status_code == 422

            validation_records = [r for r in caplog.records if "validation_error" in r.message]
            assert validation_records, "expected at least one validation_error log record"
            for record in validation_records:
                assert "x" * 200 not in record.message, "raw user input must not appear in logs"
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    def test_422_response_still_includes_input(self):
        """The client 422 response must contain the raw 'input' value (only the log is scrubbed)."""
        fake_user = _make_fake_user()
        app.dependency_overrides[get_current_user] = lambda: fake_user
        try:
            response = client.post(
                "/api/tournaments",
                json={"name": "x" * 200},  # triggers string_too_long (max_length=100)
            )
            assert response.status_code == 422
            detail = response.json()["detail"]
            # The response body must still carry the raw input value — only the log is scrubbed
            assert any(e.get("input") == "x" * 200 for e in detail), (
                "422 response must include raw input for client debugging"
            )
        finally:
            app.dependency_overrides.pop(get_current_user, None)
