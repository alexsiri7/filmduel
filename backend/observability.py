"""Sentry and log scrubbing: redact URLs, UUIDs, and OAuth query params."""

from __future__ import annotations

import logging
import re

from sentry_sdk.consts import SPANDATA

_PROVIDER_USER_PATH = re.compile(r"/users/[^/?#\s]+")
_URL_IN_TEXT = re.compile(r"https?://[^\s'\"<>]+")
_UUID_IN_TEXT = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE
)


def _strip_query(url: str) -> str:
    return re.split(r"[?#]", url, maxsplit=1)[0]


def _redact_url(url: str) -> str:
    """Drop the query string and fragment, and mask the account in ``/users/<id>``."""
    return _PROVIDER_USER_PATH.sub("/users/[Filtered]", _strip_query(url))


def _redact_text(text: str) -> str:
    """Redact every URL and UUID embedded in free text, such as httpx's error messages.

    User ids are UUIDs and log lines embed them; Sentry and Railway keep events
    and log lines after the account is deleted, so no UUID may reach either.
    """
    text = _URL_IN_TEXT.sub(lambda m: _redact_url(m.group()), text)
    return _UUID_IN_TEXT.sub("[Filtered]", text)


class _AccessLogQueryFilter(logging.Filter):
    """Drop query strings (OAuth ``code``/``state``) from uvicorn access log lines.

    uvicorn logs ``'%s - "%s %s HTTP/%s" %d'`` with the path-and-query as the
    third argument.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str):
            record.args = (*args[:2], _strip_query(args[2]), *args[3:])
        return True


logging.getLogger("uvicorn.access").addFilter(_AccessLogQueryFilter())


class _RedactingFormatter(logging.Formatter):
    """Redact URLs and UUIDs from the whole rendered line, traceback included."""

    def format(self, record: logging.LogRecord) -> str:
        return _redact_text(super().format(record))


# Applied once at app import, after uvicorn's own dictConfig. Every line reaching
# stderr goes through the one redacting handler: naming ``uvicorn`` here makes
# dictConfig drop the handlers uvicorn gave it and its ``error``/``access``
# children, so they propagate to root (the access query filter stays attached).
LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "redacting": {
            "()": _RedactingFormatter,
            "format": "%(levelname)s %(name)s: %(message)s",
        },
    },
    "handlers": {
        "redacting": {
            "class": "logging.StreamHandler",
            "formatter": "redacting",
            "stream": "ext://sys.stderr",
        },
    },
    "root": {"level": "WARNING", "handlers": ["redacting"]},
    "loggers": {
        "backend": {"level": "INFO"},
        "uvicorn": {"handlers": [], "propagate": True},
    },
}


def _scrub_http_data(data: dict) -> None:
    """Scrub the URL fields the httpx integration attaches to breadcrumbs and spans.

    The integration records outgoing URLs unsanitized, so TMDB ``api_key`` query
    params and Trakt usernames would otherwise reach Sentry.
    """
    data.pop(SPANDATA.HTTP_QUERY, None)
    data.pop(SPANDATA.HTTP_FRAGMENT, None)
    if isinstance(data.get("url"), str):
        data["url"] = _redact_url(data["url"])


def _scrub_breadcrumb(crumb: dict, hint: dict) -> dict:
    _scrub_http_data(crumb.get("data") or {})
    if isinstance(crumb.get("message"), str):
        crumb["message"] = _redact_text(crumb["message"])
    return crumb


def _scrub_logentry(logentry: dict) -> None:
    """Redact URLs and UUIDs in a log event's text.

    ``params`` holds the raw log arguments, which may be exceptions whose repr
    embeds a URL; ``formatted`` already renders them, so they are dropped.
    """
    logentry.pop("params", None)
    for key in ("message", "formatted"):
        if isinstance(logentry.get(key), str):
            logentry[key] = _redact_text(logentry[key])


def _scrub_event(event: dict, hint: dict) -> dict:
    """Strip query strings and provider account paths from every URL the event carries.

    Covers incoming requests (OAuth ``code``/``state``), outgoing span URLs, and
    URLs and UUIDs embedded in log messages and exception text.
    """
    request = event.get("request") or {}
    request.pop("query_string", None)
    if isinstance(request.get("url"), str):
        request["url"] = _redact_url(request["url"])
    for span in event.get("spans") or []:
        _scrub_http_data(span.get("data") or {})
        if isinstance(span.get("description"), str):
            span["description"] = _redact_url(span["description"])
    _scrub_logentry(event.get("logentry") or {})
    for exc in (event.get("exception") or {}).get("values") or []:
        if isinstance(exc.get("value"), str):
            exc["value"] = _redact_text(exc["value"])
    return event


SENTRY_OPTIONS = dict(
    send_default_pii=False,
    max_request_body_size="never",
    include_local_variables=False,
    traces_sample_rate=0.1,
    before_send=_scrub_event,
    before_send_transaction=_scrub_event,
    before_breadcrumb=_scrub_breadcrumb,
)
