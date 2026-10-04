"""Tests for suggestions router — consent, not_enough_films, regenerate limits, 503."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("TOKEN_ENC_KEY", "test-secret-key-for-unit-tests-32b")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests!!")

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.tests import SPA_HEADERS
from backend.db import get_db
from backend.routers.auth import CURRENT_PRIVACY_POLICY_VERSION, get_current_user
from backend.schemas import MovieSchema, SuggestionSchema


def _make_user(*, privacy_policy_accepted: bool = True):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.privacy_policy_accepted = privacy_policy_accepted
    user.privacy_policy_version = CURRENT_PRIVACY_POLICY_VERSION
    return user


# ---------------------------------------------------------------------------
# Items 5: consent gate & not_enough_films
# ---------------------------------------------------------------------------


class TestGetSuggestions:
    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_get_suggestions_requires_consent(self):
        """GET /api/suggestions returns 403 when user has not accepted privacy policy."""
        user = _make_user(privacy_policy_accepted=False)
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: AsyncMock()

        with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
            resp = client.get("/api/suggestions")

        assert resp.status_code == 403
        assert "consent" in resp.json()["detail"].lower()

    def test_get_suggestions_not_enough_films(self):
        """GET /api/suggestions returns status='not_enough_films' with empty list."""
        user = _make_user(privacy_policy_accepted=True)
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: AsyncMock()

        with patch(
            "backend.routers.suggestions.has_enough_ranked",
            new_callable=AsyncMock,
            return_value=False,
        ):
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.get("/api/suggestions")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "not_enough_films"
        assert body["suggestions"] == []

    def test_get_suggestions_503_when_llm_key_missing(self):
        """GET /api/suggestions returns 503 with generic detail when LLM key not configured."""
        user = _make_user(privacy_policy_accepted=True)
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: AsyncMock()

        with patch(
            "backend.routers.suggestions.has_enough_ranked",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "backend.routers.suggestions._get_active_suggestions",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "backend.routers.suggestions._latest_generated_at",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "backend.routers.suggestions.try_acquire_xact_lock",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "backend.routers.suggestions._create_suggestions",
            new_callable=AsyncMock,
            side_effect=ValueError("LLM_API_KEY not configured"),
        ):
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.get("/api/suggestions")

        assert resp.status_code == 503
        assert resp.json()["detail"] == "AI features are not available"


def _fake_suggestion_schema() -> SuggestionSchema:
    return SuggestionSchema(
        id=str(uuid.uuid4()),
        movie=MovieSchema(
            id=str(uuid.uuid4()), trakt_id=42, title="Test Film", media_type="movie"
        ),
        reason="test reason",
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


class TestGetSuggestionsGeneration:
    """GET may only generate on first use or when the newest batch is stale,
    regardless of dismissal state (AUD-08, #690)."""

    def setup_method(self):
        app.dependency_overrides.clear()
        self.user = _make_user(privacy_policy_accepted=True)
        app.dependency_overrides[get_current_user] = lambda: self.user
        app.dependency_overrides[get_db] = lambda: AsyncMock()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _get(self, *, active, latest, lock=True, created=None):
        """Call GET with the router's data helpers stubbed; return (resp, create mock)."""
        latest_kwargs = (
            {"side_effect": latest} if isinstance(latest, list) else {"return_value": latest}
        )
        with patch(
            "backend.routers.suggestions.has_enough_ranked",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "backend.routers.suggestions._get_active_suggestions",
            new_callable=AsyncMock,
            return_value=active,
        ), patch(
            "backend.routers.suggestions._latest_generated_at",
            new_callable=AsyncMock,
            **latest_kwargs,
        ), patch(
            "backend.routers.suggestions.try_acquire_xact_lock",
            new_callable=AsyncMock,
            return_value=lock,
        ), patch(
            "backend.routers.suggestions._create_suggestions",
            new_callable=AsyncMock,
            return_value=created if created is not None else [MagicMock()],
        ) as mock_create, patch(
            "backend.routers.suggestions._build_suggestion_schema",
            return_value=_fake_suggestion_schema(),
        ):
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.get("/api/suggestions")
        return resp, mock_create

    def test_all_dismissed_fresh_batch_does_not_generate(self):
        now = datetime.now(timezone.utc)
        resp, mock_create = self._get(active=[], latest=now - timedelta(hours=1))

        assert resp.status_code == 200
        assert resp.json() == {"suggestions": [], "status": "all_dismissed"}
        mock_create.assert_not_awaited()

    def test_stale_active_card_with_fresh_dismissed_batch_does_not_generate(self):
        now = datetime.now(timezone.utc)
        resp, mock_create = self._get(active=[MagicMock()], latest=now - timedelta(hours=1))

        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"
        assert len(resp.json()["suggestions"]) == 1
        mock_create.assert_not_awaited()

    def test_first_use_generates(self):
        resp, mock_create = self._get(active=[], latest=None)

        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"
        mock_create.assert_awaited_once()

    def test_stale_batch_regenerates(self):
        now = datetime.now(timezone.utc)
        resp, mock_create = self._get(active=[MagicMock()], latest=now - timedelta(hours=25))

        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"
        mock_create.assert_awaited_once()

    def test_generation_in_flight_returns_429_without_generating(self):
        resp, mock_create = self._get(active=[], latest=None, lock=False)

        assert resp.status_code == 429
        mock_create.assert_not_awaited()

    def test_generation_in_flight_returns_existing_active(self):
        now = datetime.now(timezone.utc)
        resp, mock_create = self._get(
            active=[MagicMock()], latest=now - timedelta(hours=25), lock=False
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"
        mock_create.assert_not_awaited()

    def test_rechecks_freshness_under_lock(self):
        now = datetime.now(timezone.utc)
        resp, mock_create = self._get(
            active=[], latest=[None, now - timedelta(minutes=1)]
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "all_dismissed"
        mock_create.assert_not_awaited()


# ---------------------------------------------------------------------------
# Item 6: regenerate daily limit & 503
# ---------------------------------------------------------------------------


class TestRegenerateSuggestions:
    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_regenerate_enforces_daily_limit(self):
        """POST /api/suggestions/regenerate returns 429 when daily limit reached."""
        user = _make_user(privacy_policy_accepted=True)
        mock_db = AsyncMock()

        # Mock has_enough_ranked to return True
        # Mock the regen count query to return 3 (at limit)
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 3
        mock_db.execute.return_value = mock_count_result

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch(
            "backend.routers.suggestions.has_enough_ranked",
            new_callable=AsyncMock,
            return_value=True,
        ):
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.post("/api/suggestions/regenerate")

        assert resp.status_code == 429
        assert "3 times per day" in resp.json()["detail"]

    def test_regen_cap_check_is_serialized_per_user(self):
        """The regen count must run under a per-user advisory lock (SEC-02, #570)."""
        from sqlalchemy.dialects import postgresql

        user = _make_user(privacy_policy_accepted=True)
        mock_db = AsyncMock()
        statements: list = []

        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 3

        async def record_execute(stmt, *args, **kwargs):
            statements.append(stmt)
            return mock_count_result

        mock_db.execute = AsyncMock(side_effect=record_execute)

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch(
            "backend.routers.suggestions.has_enough_ranked",
            new_callable=AsyncMock,
            return_value=True,
        ):
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.post("/api/suggestions/regenerate")

        assert resp.status_code == 429
        mock_db.commit.assert_not_called()

        compiled = [stmt.compile(dialect=postgresql.dialect()) for stmt in statements]
        lock_idx = next(
            i for i, c in enumerate(compiled) if "pg_advisory_xact_lock" in str(c)
        )
        count_idx = next(i for i, c in enumerate(compiled) if "count(" in str(c).lower())
        assert lock_idx < count_idx, "advisory lock must be taken before the regen count"

        lock_params = set(compiled[lock_idx].params.values())
        assert "suggestions_regen" in lock_params
        assert str(user.id) in lock_params

    def test_regen_cap_lock_is_held_through_generation(self):
        """Under the cap, nothing between the count and the LLM call may commit (SEC-02, #570)."""
        from datetime import datetime, timezone

        from sqlalchemy.dialects import postgresql

        from backend.schemas import MovieSchema, SuggestionSchema

        user = _make_user(privacy_policy_accepted=True)
        mock_db = AsyncMock()
        statements: list = []

        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0

        async def record_execute(stmt, *args, **kwargs):
            statements.append(stmt)
            return mock_count_result

        mock_db.execute = AsyncMock(side_effect=record_execute)

        fake_schema = SuggestionSchema(
            id=str(uuid.uuid4()),
            movie=MovieSchema(
                id=str(uuid.uuid4()), trakt_id=42, title="Test Film", media_type="movie"
            ),
            reason="test reason",
            generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch(
            "backend.routers.suggestions.has_enough_ranked",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "backend.routers.suggestions._get_active_suggestions",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "backend.routers.suggestions._create_suggestions",
            new_callable=AsyncMock,
            return_value=[MagicMock()],
        ) as mock_create, patch(
            "backend.routers.suggestions._build_suggestion_schema",
            return_value=fake_schema,
        ):
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.post("/api/suggestions/regenerate")

        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"
        mock_create.assert_awaited_once()
        mock_db.commit.assert_not_called()
        assert any(
            "pg_advisory_xact_lock" in str(stmt.compile(dialect=postgresql.dialect()))
            for stmt in statements
        )

    def test_regenerate_503_without_llm_key(self):
        """POST /api/suggestions/regenerate returns 503 when LLM key not configured."""
        user = _make_user(privacy_policy_accepted=True)
        mock_db = AsyncMock()

        # Mock regen count below limit
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0
        mock_db.execute.return_value = mock_count_result

        # Mock _get_active_suggestions to return empty (no existing to dismiss)
        # Mock _create_suggestions to raise ValueError (LLM key missing)

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch(
            "backend.routers.suggestions.has_enough_ranked",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "backend.routers.suggestions._get_active_suggestions",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "backend.routers.suggestions._create_suggestions",
            new_callable=AsyncMock,
            side_effect=ValueError("LLM_API_KEY not configured"),
        ):
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.post("/api/suggestions/regenerate")

        assert resp.status_code == 503
        assert resp.json()["detail"] == "AI features are not available"


# ---------------------------------------------------------------------------
# _sync_trakt_watchlist — SELECT FOR UPDATE assertion
# ---------------------------------------------------------------------------


class TestSyncTraktWatchlistForUpdate:
    """Verify _sync_trakt_watchlist locks the user row with SELECT ... FOR UPDATE."""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_sync_trakt_watchlist_uses_select_for_update(self):
        """_sync_trakt_watchlist must lock the user row to prevent concurrent token refresh.

        TestClient runs background tasks synchronously, allowing us to capture
        the SQLAlchemy statement passed to session.execute and verify that
        SELECT ... FOR UPDATE is used.
        """
        from datetime import datetime, timezone

        from sqlalchemy.dialects import postgresql

        from backend.schemas import MovieSchema, SuggestionSchema

        user_id = uuid.uuid4()
        suggestion_id = uuid.uuid4()
        movie_id = uuid.uuid4()

        mock_user = MagicMock()
        mock_user.id = user_id
        mock_user.privacy_policy_accepted = True
        mock_user.privacy_policy_version = CURRENT_PRIVACY_POLICY_VERSION
        mock_user.trakt_access_token = "valid-token"

        # Mock the suggestion returned by the route's db query
        mock_movie = MagicMock()
        mock_movie.trakt_id = 42

        mock_suggestion = MagicMock()
        mock_suggestion.id = suggestion_id
        mock_suggestion.movie = mock_movie
        mock_suggestion.added_to_watchlist_at = None

        # Build a valid SuggestionSchema for the mock response
        fake_schema = SuggestionSchema(
            id=str(suggestion_id),
            movie=MovieSchema(
                id=str(movie_id),
                trakt_id=42,
                title="Test Film",
                media_type="movie",
            ),
            reason="test reason",
            generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

        captured_bg_stmts = []

        async def fake_bg_session_execute(stmt, *args, **kwargs):
            captured_bg_stmts.append(stmt)
            result = MagicMock()
            result.scalar_one_or_none.return_value = mock_user
            return result

        mock_bg_session = AsyncMock()
        mock_bg_session.execute.side_effect = fake_bg_session_execute
        mock_bg_session.commit = AsyncMock()

        mock_db = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db

        with (
            patch(
                "backend.routers.suggestions._get_user_suggestion",
                new_callable=AsyncMock,
                return_value=mock_suggestion,
            ),
            patch(
                "backend.routers.suggestions._build_suggestion_schema",
                return_value=fake_schema,
            ),
            patch(
                "backend.routers.suggestions.async_session_factory"
            ) as mock_factory,
            patch(
                "backend.routers.suggestions.ensure_fresh_token",
                new_callable=AsyncMock,
                return_value=mock_user,
            ),
            patch(
                "backend.routers.suggestions.TraktClient"
            ) as mock_trakt_cls,
        ):
            mock_factory.return_value.__aenter__ = AsyncMock(
                return_value=mock_bg_session
            )
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_trakt_cls.return_value = AsyncMock()

            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=True) as client:
                resp = client.post(
                    f"/api/suggestions/{suggestion_id}/watchlist"
                )

        assert resp.status_code == 200, f"Unexpected status: {resp.status_code}"
        assert captured_bg_stmts, "session.execute was never called in background task"

        user_stmt = captured_bg_stmts[0]
        compiled = user_stmt.compile(dialect=postgresql.dialect())
        assert "FOR UPDATE" in str(compiled).upper(), (
            "User query in _sync_trakt_watchlist must use .with_for_update() "
            "to prevent concurrent token refresh"
        )
