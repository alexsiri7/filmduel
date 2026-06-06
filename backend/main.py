"""FilmDuel — FastAPI application entry point."""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlparse

import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from backend.config import get_settings
from backend.rate_limit import limiter
from backend.routers import (
    auth,
    movies,
    duels,
    rankings,
    suggestions,
    swipe,
    tournaments,
    feedback,
    users,
)
from backend.schemas import SELF_DUEL_ERROR_MSG

logger = logging.getLogger(__name__)

settings = get_settings()

_SCRUB_KEYS = frozenset(
    {
        "trakt_access_token",
        "trakt_refresh_token",
        "trakt_access_token_enc",
        "trakt_refresh_token_enc",
        "access_token",
        "refresh_token",
        "SECRET_KEY",
        "Authorization",
        "authorization",  # httpx normalizes response headers to lowercase
        "_headers",
    }
)


def _scrub_sensitive(event: dict, hint: dict) -> dict:
    """Strip OAuth tokens and secret keys from Sentry stack frame locals.

    Scrubs using two strategies:
    - Exact match against _SCRUB_KEYS (denylist of known sensitive fields)
    - Substring match: any local variable whose name contains "token" or "secret"
      (case-insensitive) is also filtered, covering future fields automatically.

    Filtered values are replaced with "[Filtered]".
    """
    for exc_val in (event.get("exception") or {}).get("values") or []:
        for frame in (exc_val.get("stacktrace") or {}).get("frames") or []:
            vars_ = frame.get("vars") or {}
            for key in list(vars_):
                lower = key.lower()
                if key in _SCRUB_KEYS or "token" in lower or "secret" in lower:
                    vars_[key] = "[Filtered]"
    return event


if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        send_default_pii=False,
        traces_sample_rate=0.1,
        before_send=_scrub_sensitive,
    )

_is_dev = settings.BASE_URL.startswith("http://localhost")
app = FastAPI(
    title="FilmDuel",
    version="0.1.0",
    docs_url="/docs" if _is_dev else None,
    redoc_url="/redoc" if _is_dev else None,
    openapi_url="/openapi.json" if _is_dev else None,
)


def _scrub_validation_errors(errors: list[dict]) -> list[dict]:
    """Strip 'input' values from Pydantic v2 error dicts before logging.

    Pydantic v2 includes the raw user-submitted value under the 'input' key.
    Removing it prevents free-text user data from appearing in logs/Sentry.
    The full errors() list (including 'input') is still returned to the client.

    Note: scrubbing is shallow (top-level 'input' only). Pydantic v2 flattens
    most errors, so nested inputs are rare. Revisit if discriminated unions are added.
    """
    return [{k: v for k, v in e.items() if k != "input"} for e in errors]


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    if any(SELF_DUEL_ERROR_MSG in e.get("msg", "") for e in exc.errors()):
        return JSONResponse(
            status_code=400,
            content={"detail": "A movie cannot duel against itself"},
        )
    logger.warning(
        "validation_error path=%s errors=%s",
        request.url.path,
        _scrub_validation_errors(exc.errors()),
    )
    return JSONResponse(
        status_code=422, content={"detail": _scrub_validation_errors(exc.errors())}
    )


# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — origins configurable via CORS_ORIGINS env var
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    # X-Requested-With is required for the CSRF bypass (see csrf_origin_check middleware)
    allow_headers=["Content-Type", "X-Requested-With"],
)


@app.middleware("http")
async def csrf_origin_check(request: Request, call_next):
    """Block state-changing requests from unexpected origins.

    Checks Origin (or Referer fallback) against the CORS allowlist.
    Also accepts requests with X-Requested-With header (set by our SPA).
    Exempt: GET, HEAD, OPTIONS (safe methods / preflight).
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return await call_next(request)

    # X-Requested-With is a custom header — browsers never send it cross-site
    # without a preflight, so its presence proves the request came from our SPA
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return await call_next(request)

    origin = request.headers.get("origin") or request.headers.get("referer", "")

    # No origin or referer header — non-browser / server-to-server clients cannot
    # perform CSRF (they have no victim session cookie), so allow through.
    if not origin:
        return await call_next(request)

    # Normalise to scheme+host — strips path/query from Referer; Origin already
    # carries only scheme+host, so this is a no-op for them.
    parsed = urlparse(origin)
    origin_base = f"{parsed.scheme}://{parsed.netloc}"

    if origin_base in settings.CORS_ORIGINS:
        return await call_next(request)

    logger.warning(
        "csrf_check_failed method=%s origin=%r path=%s",
        request.method,
        origin,
        request.url.path,
    )
    return JSONResponse(
        status_code=403,
        content={"detail": "CSRF check failed: unexpected origin"},
    )


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if settings.is_https:
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains; preload"
        )
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' https://image.tmdb.org data:; "
        "script-src 'self'; "
        "style-src 'self'; "
        "connect-src 'self' https://*.sentry.io; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "object-src 'none'"
    )
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    return response


# Register API routers
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(movies.router)
app.include_router(duels.router)
app.include_router(rankings.router)
app.include_router(suggestions.router)
app.include_router(swipe.router)
app.include_router(tournaments.router)
app.include_router(feedback.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


# --- Static files / SPA fallback ---

STATIC_DIR = (Path(__file__).parent.parent / "frontend" / "dist").resolve()

if (STATIC_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    """Serve the SPA index.html for any non-API route."""
    if not STATIC_DIR.is_dir():
        logger.warning("frontend/dist not found at %s — returning 503", STATIC_DIR)
        return JSONResponse({"detail": "Frontend not available"}, status_code=503)
    index_html = STATIC_DIR / "index.html"
    if not index_html.is_file():
        logger.error(
            "frontend/dist/index.html missing at %s — returning 503", index_html
        )
        return JSONResponse({"detail": "Frontend not available"}, status_code=503)
    file_path = (STATIC_DIR / full_path).resolve()
    if file_path.is_file():
        if file_path.is_relative_to(STATIC_DIR):
            return FileResponse(file_path)
        logger.warning(
            "spa_fallback blocked out-of-bounds access: requested=%s resolved=%s",
            full_path,
            file_path,
        )
    return FileResponse(index_html)
