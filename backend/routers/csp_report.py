"""Receives browser Content-Security-Policy violation reports (SEC-27, #799)."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from fastapi import APIRouter, Request, Response

from backend.rate_limit import limiter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["security"])

CSP_REPORT_PATH = "/api/csp-report"

_MAX_REPORTS = 10
_MAX_FIELD = 200


def _str(value: object) -> str:
    return value if isinstance(value, str) else ""


def _violations(payload: object) -> list[dict[str, str]]:
    """Normalise the legacy report-uri body and the Reporting API body."""
    if isinstance(payload, dict):
        report = payload.get("csp-report")
        if not isinstance(report, dict):
            return []
        return [
            {
                "directive": _str(report.get("effective-directive"))
                or _str(report.get("violated-directive")),
                "blocked": _str(report.get("blocked-uri")),
                "document": _str(report.get("document-uri")),
            }
        ]
    if isinstance(payload, list):
        return [
            {
                "directive": _str(item["body"].get("effectiveDirective")),
                "blocked": _str(item["body"].get("blockedURL")),
                "document": _str(item["body"].get("documentURL")),
            }
            for item in payload
            if isinstance(item, dict)
            and item.get("type") == "csp-violation"
            and isinstance(item.get("body"), dict)
        ]
    return []


def _scrub_blocked(value: str) -> str:
    # Reports carry full URLs; keep only the origin. Keywords such as
    # "inline" or "eval" have no scheme and pass through.
    try:
        parsed = urlparse(value)
    except ValueError:
        return ""
    if parsed.scheme in ("http", "https") or parsed.netloc:
        value = f"{parsed.scheme}://{parsed.netloc}"
    return value[:_MAX_FIELD]


def _scrub_document(value: str) -> str:
    # The query string can hold OAuth code/state and pair tokens.
    try:
        return urlparse(value).path[:_MAX_FIELD]
    except ValueError:
        return ""


@router.post(CSP_REPORT_PATH, status_code=204)
@limiter.limit("30/minute")
async def csp_report(request: Request) -> Response:
    # Browsers send application/csp-report or application/reports+json, never
    # application/json, so the body is read from the request rather than
    # declared as a body model. Malformed bodies still get 204 so probers
    # learn nothing.
    try:
        payload = await request.json()
    except ValueError:
        return Response(status_code=204)

    for violation in _violations(payload)[:_MAX_REPORTS]:
        logger.warning(
            "csp_violation directive=%r blocked=%r document=%r",
            violation["directive"][:_MAX_FIELD],
            _scrub_blocked(violation["blocked"]),
            _scrub_document(violation["document"]),
        )
    return Response(status_code=204)
