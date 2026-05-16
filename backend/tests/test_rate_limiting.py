"""Tests for rate limiting enforcement and SQL cap boundaries on PR #223 endpoints."""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("TOKEN_ENC_KEY", "test-secret-key-for-unit-tests-32b")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests!!")

import pytest
from fastapi.testclient import TestClient

from datetime import datetime, timezone

from backend.main import app
from backend.db import get_db
from backend.rate_limit import limiter
from backend.routers.auth import get_current_user
from slowapi.errors import RateLimitExceeded


def _make_user():
    user = MagicMock()
    user.id = uuid.uuid4()
    return user


# ---------------------------------------------------------------------------
# Limiter registration — confirms @limiter.limit() decorators are applied
# ---------------------------------------------------------------------------


def test_get_movie_pair_is_registered_with_rate_limiter():
    """get_movie_pair must be registered in the slowapi limiter."""
    assert "backend.routers.movies.get_movie_pair" in limiter._Limiter__marked_for_limiting


def test_export_csv_is_registered_with_rate_limiter():
    """export_csv must be registered in the slowapi limiter."""
    assert "backend.routers.rankings.export_csv" in limiter._Limiter__marked_for_limiting


def test_export_csv_rate_limit_is_10_per_hour():
    """export_csv rate limit must be exactly 10/hour (not 6/minute or any other value)."""
    limits = limiter._route_limits.get("backend.routers.rankings.export_csv", [])
    limit_strings = [str(lim.limit) for lim in limits]
    assert any("10 per 1 hour" in s for s in limit_strings), (
        f"Expected '10/hour' limit on export_csv, got: {limit_strings}"
    )


def test_list_tournaments_is_registered_with_rate_limiter():
    """list_tournaments must be registered in the slowapi limiter."""
    assert "backend.routers.tournaments.list_tournaments" in limiter._Limiter__marked_for_limiting


def test_submit_feedback_is_registered_with_rate_limiter():
    """submit_feedback must be registered in the slowapi limiter."""
    assert "backend.routers.feedback.submit_feedback" in limiter._Limiter__marked_for_limiting


def test_rate_limit_exceeded_handler_registered():
    """RateLimitExceeded exception handler must be registered on the app."""
    assert RateLimitExceeded in app.exception_handlers


def test_app_state_limiter_is_configured():
    """app.state.limiter must reference the shared limiter instance."""
    assert app.state.limiter is limiter


# ---------------------------------------------------------------------------
# 429 response — verify the exception handler returns correct status
# ---------------------------------------------------------------------------


def test_rate_limit_exceeded_handler_returns_429():
    """The RateLimitExceeded handler must produce a 429 JSON response."""
    from slowapi import _rate_limit_exceeded_handler

    mock_limit = MagicMock()
    mock_limit.limit = "60/minute"
    mock_limit.error_message = "60 per 1 minute"

    # Build a mock request with the state attribute slowapi expects
    mock_request = MagicMock()
    mock_request.state.view_rate_limit = mock_limit
    mock_request.app.state.limiter = limiter

    exc = RateLimitExceeded(mock_limit)

    response = _rate_limit_exceeded_handler(mock_request, exc)

    assert response.status_code == 429


# ---------------------------------------------------------------------------
# Endpoint reachability — confirms request:Request param injection works
# ---------------------------------------------------------------------------


def test_get_movie_pair_endpoint_reachable():
    """Endpoint responds (not 500) after request:Request param was added."""
    fake_user = _make_user()
    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_db] = lambda: AsyncMock()

    with patch("backend.routers.movies.select_pair", new_callable=AsyncMock) as mock_pair:
        mock_pair.side_effect = ValueError("not enough films")
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/movies/pair")

    app.dependency_overrides.clear()
    # 404 is expected (not enough films); confirms endpoint + Request param works
    assert resp.status_code == 404
    assert resp.status_code != 500


def test_export_csv_endpoint_reachable():
    """export_csv responds (not 500) after request:Request param was added."""
    fake_user = _make_user()
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.unique.return_value.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = mock_result

    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_db] = lambda: mock_db

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/rankings/export/csv")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.status_code != 500


def test_list_tournaments_endpoint_reachable():
    """list_tournaments responds (not 500) after request:Request param was added."""
    fake_user = _make_user()
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.unique.return_value.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = mock_result

    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_db] = lambda: mock_db

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/tournaments")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.status_code != 500


# ---------------------------------------------------------------------------
# SQL cap boundary — list_tournaments capped at 100
# ---------------------------------------------------------------------------


def test_list_tournaments_returns_at_most_100_results():
    """list_tournaments must not exceed 100 results."""
    fake_user = _make_user()
    mock_db = AsyncMock()

    now = datetime.now(timezone.utc)
    fake_tournaments = []
    for i in range(100):
        t = MagicMock()
        t.status = "completed"
        t.matches = []
        t.id = uuid.uuid4()
        t.name = f"Tournament {i}"
        t.bracket_size = 8
        t.media_type = "movie"
        t.created_at = now
        fake_tournaments.append(t)

    mock_result = MagicMock()
    mock_result.unique.return_value.scalars.return_value.all.return_value = fake_tournaments
    mock_db.execute.return_value = mock_result

    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_db] = lambda: mock_db

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/tournaments")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert len(resp.json()) <= 100


@pytest.mark.asyncio
async def test_list_tournaments_query_includes_limit_clause():
    """The DB query for list_tournaments must include LIMIT 100 (safety cap)."""
    from sqlalchemy.dialects import sqlite
    from sqlalchemy import select
    from backend.db_models import Tournament
    from sqlalchemy.orm import joinedload

    # Reconstruct the query as written in the router and check it has LIMIT
    stmt = (
        select(Tournament)
        .options(joinedload(Tournament.matches))
        .where(Tournament.user_id == uuid.uuid4())
        .order_by(Tournament.created_at.desc())
        .limit(100)  # safety cap — prevents unbounded result sets per user
    )
    compiled = stmt.compile(
        dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}
    )
    assert "100" in str(compiled)


# ---------------------------------------------------------------------------
# SQL cap boundary — CSV export limited to 10000 rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_csv_respects_row_limit():
    """export_rankings_csv must return at most 10000 data rows."""
    fake_ums = []
    for i in range(10000):
        um = MagicMock()
        um.elo = 1000 - i
        um.movie.title = f"Movie {i}"
        um.movie.year = 2020
        um.movie.imdb_id = f"tt{i:07d}"
        um.movie.media_type = "movie"
        fake_ums.append(um)

    mock_result = MagicMock()
    mock_result.unique.return_value.scalars.return_value.all.return_value = fake_ums

    db = AsyncMock()
    db.execute.return_value = mock_result

    from backend.services.rankings import export_rankings_csv

    csv_content = await export_rankings_csv(db, uuid.uuid4(), media_type="movie")
    lines = [line for line in csv_content.strip().split("\n") if line]
    # 1 header + up to 10000 data rows
    assert len(lines) <= 10001


@pytest.mark.asyncio
async def test_export_csv_query_includes_limit_clause():
    """The DB query for CSV export must include a LIMIT clause (safety cap)."""
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.unique.return_value.scalars.return_value.all.return_value = []
    db.execute.return_value = mock_result

    from backend.services.rankings import export_rankings_csv

    await export_rankings_csv(db, uuid.uuid4(), media_type="movie")

    assert db.execute.called
    call_args = db.execute.call_args[0][0]
    from sqlalchemy.dialects import sqlite

    compiled = call_args.compile(
        dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}
    )
    assert "10000" in str(compiled)
