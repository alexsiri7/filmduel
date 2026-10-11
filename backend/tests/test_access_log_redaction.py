"""uvicorn access log lines must not carry OAuth ``code``/``state`` query params (AUD-19, #701)."""

from __future__ import annotations

import logging
import logging.config
import os

# Must set SECRET_KEY before importing backend.main — pydantic Settings validates it at import time.
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests!!")

import pytest  # noqa: E402
from uvicorn.config import LOGGING_CONFIG  # noqa: E402

import backend.main  # noqa: E402, F401 — installs the access-log filter


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@pytest.fixture
def access_log():
    # uvicorn applies its own dictConfig at startup; the filter must survive it.
    logging.config.dictConfig(LOGGING_CONFIG)
    logger = logging.getLogger("uvicorn.access")
    capture = _Capture()
    logger.addHandler(capture)
    yield logger, capture.messages
    logger.removeHandler(capture)


def _log_request(logger: logging.Logger, path: str) -> None:
    # Same format string and argument order uvicorn's HTTP protocols use.
    logger.info('%s - "%s %s HTTP/%s" %d', "203.0.113.7:5000", "GET", path, "1.1", 307)


@pytest.mark.parametrize("path", ["/auth/callback", "/auth/simkl/callback"])
def test_oauth_callback_code_and_state_are_dropped(access_log, path):
    logger, messages = access_log
    _log_request(logger, f"{path}?code=SECRET-CODE&state=SECRET-STATE")
    assert messages == [f'203.0.113.7:5000 - "GET {path} HTTP/1.1" 307']


def test_path_without_query_is_unchanged(access_log):
    logger, messages = access_log
    _log_request(logger, "/api/rankings")
    assert messages == ['203.0.113.7:5000 - "GET /api/rankings HTTP/1.1" 307']


def test_other_access_logger_records_pass_through(access_log):
    logger, messages = access_log
    logger.info("plain message %s", "?kept")
    assert messages == ["plain message ?kept"]
