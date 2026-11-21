"""SPA request provenance.

Shared by the CSRF middleware in main.py and routers/suggestions.py so every
site that trusts "this request came from our SPA" applies the same rule.
"""

from __future__ import annotations

from starlette.requests import Request


def is_spa_request(request: Request) -> bool:
    """True when the request carries the SPA's ``X-Requested-With`` header.

    It is a custom header, so browsers never send it cross-site without a
    CORS preflight our allowlist would refuse.
    """
    return request.headers.get("x-requested-with") == "XMLHttpRequest"
