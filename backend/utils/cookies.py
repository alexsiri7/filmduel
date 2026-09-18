"""Cookie names and the ``__Host-`` prefix rule.

Shared by routers/auth.py, routers/users.py and rate_limit.py so every site
that issues, reads or expires one of these cookies agrees on its wire name.
"""

from __future__ import annotations

COOKIE_NAME = "filmduel_session"
OAUTH_STATE_COOKIE = "filmduel_oauth_state"
OAUTH_SIMKL_STATE_COOKIE = "filmduel_oauth_simkl_state"
OAUTH_PKCE_COOKIE = "filmduel_oauth_pkce"
OAUTH_SIMKL_PKCE_COOKIE = "filmduel_oauth_simkl_pkce"


def cookie_name(base: str, secure: bool) -> str:
    """On-the-wire name for ``base``: ``__Host-``-prefixed when Secure.

    __Host- stops a sibling subdomain from overwriting the cookie (cookie
    tossing / session fixation), but browsers only accept the prefix on a
    Secure, Path=/, Domain-less cookie — so it is tied to the Secure flag.
    """
    return f"__Host-{base}" if secure else base
