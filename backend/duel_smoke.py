"""Post-deploy duel smoke test: fetch a pair and submit a duel as a smoke user (#648).

Run against a deployed environment through ``railway run``, which injects the
service's ``SECRET_KEY`` so a short-lived session can be minted for the smoke user:

    SMOKE_BASE_URL=https://... SMOKE_USER_ID=<uuid> \\
        railway run --service web --environment staging -- python3 -m backend.duel_smoke

Standard library only: CI runs it with the runner's python3 without installing
backend/requirements.txt. Never print the key or the minted token.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable

# Keep in sync with create_jwt in backend/routers/auth.py and cookie_name in
# backend/utils/cookies.py — enforced by backend/tests/test_duel_smoke.py.
JWT_ISSUER = JWT_AUDIENCE = "filmduel"
JWT_LIFETIME_SECONDS = 600
SESSION_COOKIE = "__Host-filmduel_session"

REQUEST_TIMEOUT_SECONDS = 15

Request = Callable[[str, str, str, dict | None], tuple[int, dict | None]]


class SmokeFailure(Exception):
    pass


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def mint_session_jwt(user_id: str, secret: str, now: float | None = None) -> str:
    """HS256 session token with the claims get_current_user_id requires."""
    now = time.time() if now is None else now
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": user_id,
        "jti": secrets.token_hex(16),
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "iat": int(now),
        "exp": int(now) + JWT_LIFETIME_SECONDS,
        "orig_iat": float(now),
    }
    signing_input = ".".join(
        _b64url(json.dumps(part, separators=(",", ":")).encode())
        for part in (header, payload)
    )
    signature = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url(signature)}"


def _request(
    method: str, url: str, token: str, body: dict | None = None
) -> tuple[int, dict | None]:
    headers = {
        "Cookie": f"{SESSION_COOKIE}={token}",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json",
    }
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            return resp.status, _parse_json(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, _parse_json(exc.read())


def _parse_json(raw: bytes) -> dict | None:
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _describe(status: int, body: dict | None) -> str:
    detail = body.get("detail") if body else None
    return f"HTTP {status}: {detail!r}" if detail is not None else f"HTTP {status}"


def run(base_url: str, user_id: str, secret: str, request: Request = _request) -> dict:
    """Fetch a pair and submit it back the way the SPA does; return the duel result."""
    base = base_url.rstrip("/")
    token = mint_session_jwt(user_id, secret)

    status, pair = request(
        "GET", f"{base}/api/movies/pair?mode=discovery&media_type=movie", token, None
    )
    if status == 401:
        raise SmokeFailure(
            f"GET /api/movies/pair {_describe(status, pair)} — smoke user not found or "
            "session rejected; check SMOKE_USER_ID for this environment"
        )
    if status == 404:
        raise SmokeFailure(
            f"GET /api/movies/pair {_describe(status, pair)} — smoke user has fewer than "
            "2 seen films; swipe some as the smoke user"
        )
    if status != 200 or pair is None:
        raise SmokeFailure(f"GET /api/movies/pair {_describe(status, pair)}")

    status, result = request(
        "POST",
        f"{base}/api/duels",
        token,
        {
            "movie_a_id": pair["movie_a"]["id"],
            "movie_b_id": pair["movie_b"]["id"],
            "outcome": "a_wins",
            "mode": "discovery",
            "pair_token": pair["next_pair_token"],
        },
    )
    if status == 403:
        raise SmokeFailure(
            f"POST /api/duels {_describe(status, result)} — smoke user has not accepted "
            "the current privacy policy; log in as the smoke user and accept it"
        )
    if status != 200 or result is None:
        raise SmokeFailure(f"POST /api/duels {_describe(status, result)}")
    return result


def main() -> int:
    env = {name: os.environ.get(name) for name in ("SMOKE_BASE_URL", "SMOKE_USER_ID", "SECRET_KEY")}
    missing = [name for name, value in env.items() if not value]
    if missing:
        print(f"FAIL: missing environment variables: {', '.join(missing)}", file=sys.stderr)
        return 2
    try:
        run(env["SMOKE_BASE_URL"], env["SMOKE_USER_ID"], env["SECRET_KEY"])
    except (SmokeFailure, urllib.error.URLError, TimeoutError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("PASS: fetched pair and submitted duel (HTTP 200)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
