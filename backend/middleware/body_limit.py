"""Request-body size ceiling (SEC-03).

FastAPI consumes the request body before resolving dependencies, so without
this middleware an unauthenticated client can spool an unbounded multipart
upload to disk or buffer an unbounded JSON body in memory before the 401 is
ever produced. uvicorn/h11 impose no ceiling of their own.

Content-Length is checked up front; chunked or under-declared bodies are cut
off by the wrapped ``receive`` once the cap is crossed. The HTTPException
raised there propagates through FastAPI's body-read block unchanged and is
rendered as a normal 413 by the app's exception handlers.
"""

from __future__ import annotations

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

DEFAULT_MAX_BODY_BYTES = 64 * 1024
FEEDBACK_MAX_BODY_BYTES = 6 * 1024 * 1024  # 5 MB screenshot cap + multipart overhead

# Longest prefix wins. Keep this list short; anything not listed gets the default.
PATH_LIMITS: tuple[tuple[str, int], ...] = (
    ("/api/feedback", FEEDBACK_MAX_BODY_BYTES),
)

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class BodyLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        default_max_bytes: int = DEFAULT_MAX_BODY_BYTES,
        path_limits: tuple[tuple[str, int], ...] = PATH_LIMITS,
    ) -> None:
        self.app = app
        self.default_max_bytes = default_max_bytes
        # Sort longest prefix first so the most specific entry matches.
        self.path_limits = tuple(sorted(path_limits, key=lambda p: -len(p[0])))

    def limit_for(self, path: str) -> int:
        for prefix, limit in self.path_limits:
            if path == prefix or path.startswith(prefix + "/"):
                return limit
        return self.default_max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method", "GET") in _SAFE_METHODS:
            await self.app(scope, receive, send)
            return

        limit = self.limit_for(scope.get("path", ""))

        declared = None
        for name, value in scope.get("headers", ()):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    response = JSONResponse(
                        {"detail": "Invalid Content-Length"}, status_code=400
                    )
                    await response(scope, receive, send)
                    return
                break

        if declared is not None and declared > limit:
            response = JSONResponse(
                {"detail": f"Request body too large (max {limit} bytes)"},
                status_code=413,
            )
            await response(scope, receive, send)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Request body too large (max {limit} bytes)",
                    )
            return message

        await self.app(scope, limited_receive, send)
