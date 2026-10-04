"""FilmDuel — FastAPI application entry point."""

from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import sentry_sdk
from sentry_sdk.consts import SPANDATA
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from backend.config import detected_proxy_platform, get_settings
from backend.rate_limit import limiter
from backend.scheduler import build_scheduler
from backend.services.tmdb import is_read_access_token
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

_PROVIDER_USER_PATH = re.compile(r"/users/[^/?#\s]+")


def _redact_url(url: str) -> str:
    """Drop the query string and fragment, and mask the account in ``/users/<id>``."""
    without_query = re.split(r"[?#]", url, maxsplit=1)[0]
    return _PROVIDER_USER_PATH.sub("/users/[Filtered]", without_query)


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
    return crumb


def _scrub_event(event: dict, hint: dict) -> dict:
    """Strip incoming query strings (OAuth ``code``/``state``) and outgoing span URLs."""
    request = event.get("request") or {}
    request.pop("query_string", None)
    if isinstance(request.get("url"), str):
        request["url"] = _redact_url(request["url"])
    for span in event.get("spans") or []:
        _scrub_http_data(span.get("data") or {})
        if isinstance(span.get("description"), str):
            span["description"] = _redact_url(span["description"])
    return event


if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        send_default_pii=False,
        max_request_body_size="never",
        include_local_variables=False,
        traces_sample_rate=0.1,
        before_send=_scrub_event,
        before_send_transaction=_scrub_event,
        before_breadcrumb=_scrub_breadcrumb,
    )

_is_dev = settings.BASE_URL.startswith("http://localhost")

_scheduler = build_scheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _scheduler.start()
    logger.info("retention_scheduler started")
    # Warn operators who deploy to hosted platforms without shared rate-limit
    # storage. (Missing SECURE_COOKIES on those platforms is rejected by Settings.)
    detected = detected_proxy_platform()
    if settings.RATE_LIMIT_STORAGE_URI:
        logger.info("rate_limit_storage: redis (shared, survives restarts)")
    elif detected:
        logger.warning(
            "rate_limit_storage_unset: detected platform env var %r but "
            "RATE_LIMIT_STORAGE_URI is not set. Rate-limit counters are per-process: "
            "they reset on every deploy and are not shared across replicas. "
            "Set RATE_LIMIT_STORAGE_URI to a redis:// URI to fix this.",
            detected,
        )
    if settings.TMDB_API_KEY and not is_read_access_token(settings.TMDB_API_KEY):
        logger.warning(
            "tmdb_v3_api_key: TMDB_API_KEY is not a v4 API Read Access Token, so it is "
            "sent to TMDB as an api_key URL query parameter and can leak via proxy logs "
            "and error reports. Replace it with the API Read Access Token from "
            "https://www.themoviedb.org/settings/api to authenticate via the "
            "Authorization header (SEC-019, #580)."
        )
    yield
    _scheduler.shutdown(wait=False)
    logger.info("retention_scheduler stopped")


app = FastAPI(
    title="FilmDuel",
    version="0.1.0",
    docs_url="/docs" if _is_dev else None,
    redoc_url="/redoc" if _is_dev else None,
    openapi_url="/openapi.json" if _is_dev else None,
    lifespan=lifespan,
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
    if any(e.get("loc", ())[-1:] == ("pair_token",) for e in exc.errors()):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid pair token"},
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

    Requests with X-Requested-With: XMLHttpRequest (set by our SPA) are
    accepted; anything else must carry an Origin (or Referer fallback) in the
    CORS allowlist. Requests with none of these headers are rejected.
    Exempt: GET, HEAD, OPTIONS (safe methods / preflight).
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return await call_next(request)

    # X-Requested-With is a custom header — browsers never send it cross-site
    # without a preflight, so its presence proves the request came from our SPA
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return await call_next(request)

    origin = request.headers.get("origin") or request.headers.get("referer", "")

    # The SPA always sends X-Requested-With and browsers always send Origin on
    # cross-site POSTs, so a request with none of the three headers has no
    # provenance we can verify — reject rather than trust it.
    if not origin:
        logger.warning(
            "csrf_no_origin_rejected method=%s path=%s",
            request.method,
            request.url.path,
        )
        return JSONResponse(
            status_code=403,
            content={"detail": "CSRF check failed: missing Origin/Referer"},
        )

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
    if settings.cookie_secure:
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
@limiter.limit("1000/minute")
async def health(request: Request):
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
        safe_path = full_path.replace("\n", "\\n").replace("\r", "\\r")
        logger.warning(
            "spa_fallback blocked out-of-bounds access: requested=%s resolved=%s",
            safe_path,
            file_path,
        )
    return FileResponse(index_html)
