"""FilmDuel — FastAPI application entry point."""

from __future__ import annotations

from pathlib import Path

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.config import get_settings
from backend.routers import auth, movies, duels, rankings, swipe, tournaments

settings = get_settings()

if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        send_default_pii=False,
        traces_sample_rate=0.1,
    )

app = FastAPI(title="FilmDuel", version="0.1.0")

# CORS — allow the Vite dev server in development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routers
app.include_router(auth.router)
app.include_router(movies.router)
app.include_router(duels.router)
app.include_router(rankings.router)
app.include_router(swipe.router)
app.include_router(tournaments.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


# --- Static files / SPA fallback ---

STATIC_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"

if STATIC_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        """Serve the SPA index.html for any non-API route."""
        file_path = (STATIC_DIR / full_path).resolve()
        if file_path.is_file() and str(file_path).startswith(str(STATIC_DIR.resolve())):
            return FileResponse(file_path)
        return FileResponse(STATIC_DIR / "index.html")
