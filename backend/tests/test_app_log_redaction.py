"""Application log lines reaching Railway must not carry user UUIDs or URL secrets (PRIV-004, #981)."""

from __future__ import annotations

import io
import logging
import logging.config
import uuid

import pytest
from uvicorn.config import LOGGING_CONFIG as UVICORN_LOGGING_CONFIG

from backend.observability import LOGGING_CONFIG, _RedactingFormatter


@pytest.fixture
def output():
    """Configure logging in production order (uvicorn's, then the app's) and capture it."""
    logging.config.dictConfig(UVICORN_LOGGING_CONFIG)
    logging.config.dictConfig(LOGGING_CONFIG)
    (handler,) = [
        h for h in logging.getLogger().handlers if isinstance(h.formatter, _RedactingFormatter)
    ]
    buffer = io.StringIO()
    previous = handler.setStream(buffer)
    yield buffer
    handler.setStream(previous)


def test_exception_with_user_id_is_redacted(output):
    user_id = uuid.uuid4()
    try:
        raise RuntimeError(
            f"lookup failed for {user_id}: https://api.trakt.tv/users/alice/history?api_key=SECRET"
        )
    except RuntimeError:
        logging.getLogger("backend.routers.users").exception(
            "Pool import failed for user %s", user_id
        )
    text = output.getvalue()
    assert "Pool import failed for user [Filtered]" in text
    assert "Traceback" in text
    assert "lookup failed for [Filtered]: https://api.trakt.tv/users/[Filtered]/history" in text
    assert str(user_id) not in text
    assert "alice" not in text
    assert "SECRET" not in text


def test_warning_with_user_id_is_redacted(output):
    user_id = uuid.uuid4()
    logging.getLogger("backend.services.quota").warning(
        "%s_hit user_id=%s count=%d", "llm_quota", user_id, 5
    )
    assert output.getvalue() == (
        "WARNING backend.services.quota: llm_quota_hit user_id=[Filtered] count=5\n"
    )


def test_app_info_is_emitted(output):
    logging.getLogger("backend.main").info("retention_scheduler started")
    assert output.getvalue() == "INFO backend.main: retention_scheduler started\n"


def test_uvicorn_error_traceback_is_redacted(output):
    user_id = uuid.uuid4()
    try:
        raise ValueError(f"no row for {user_id}")
    except ValueError:
        logging.getLogger("uvicorn.error").exception("Exception in ASGI application")
    text = output.getvalue()
    assert "ValueError: no row for [Filtered]" in text
    assert str(user_id) not in text
