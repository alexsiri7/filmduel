"""FilmDuel — FastAPI application entry point."""

from __future__ import annotations

import logging
from pathlib import Path

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
from backend.routers import auth, movies, duels, rankings, suggestions, swipe, tournaments, feedback
from backend.schemas import SELF_DUEL_ERROR_MSG

logger = logging.getLogger(__name__)

settings = get_settings()

if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        send_default_pii=False,
        traces_sample_rate=0.1,
    )

app = FastAPI(title="FilmDuel", version="0.1.0")


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
        exc.errors(),
    )
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — origins configurable via CORS_ORIGINS env var
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' https://image.tmdb.org data:; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "connect-src 'self' https://*.sentry.io"
    )
    return response


# Register API routers
app.include_router(auth.router)
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

STATIC_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"

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
        logger.warning("frontend/dist/index.html missing at %s — returning 503", index_html)
        return JSONResponse({"detail": "Frontend not available"}, status_code=503)
    file_path = (STATIC_DIR / full_path).resolve()
    if file_path.is_file() and str(file_path).startswith(str(STATIC_DIR.resolve())):
        return FileResponse(file_path)
    return FileResponse(index_html)
