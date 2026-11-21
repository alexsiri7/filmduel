"""Tests for suggestions router — consent, not_enough_films, regenerate limits, 503."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import ANY, AsyncMock, MagicMock, patch

os.environ.setdefault("TOKEN_ENC_KEY", "test-secret-key-for-unit-tests-32b")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests!!")

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.tests import SPA_HEADERS
from backend.db import get_db
from backend.db_models import Movie, Suggestion, UserMovie
from backend.routers.auth import CURRENT_PRIVACY_POLICY_VERSION, get_current_user
from backend.schemas import MovieSchema, SuggestionSchema
from backend.services.llm import LLMNotConfiguredError
from backend.services.suggest import REGENERATION_DAILY_QUOTA


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
            side_effect=LLMNotConfiguredError("LLM_API_KEY not configured"),
        ), patch("backend.main.sentry_sdk.capture_exception") as mock_capture:
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.get("/api/suggestions")

        assert resp.status_code == 503
        assert resp.json()["detail"] == "AI features are not available"
        mock_capture.assert_called_once()
        assert isinstance(mock_capture.call_args.args[0], LLMNotConfiguredError)

    def test_get_suggestions_503_when_llm_busy(self):
        """A full LLM concurrency guard (AUD-01) maps to 503, not 500."""
        from backend.services.llm import LLMBusyError

        user = _make_user(privacy_policy_accepted=True)
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: AsyncMock()

        with patch(
            "backend.routers.suggestions.has_enough_ranked",
            new_callable=AsyncMock,
            return_value=True,
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
            side_effect=LLMBusyError("busy"),
        ), patch("backend.main.sentry_sdk.capture_exception") as mock_capture:
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.get("/api/suggestions")

        assert resp.status_code == 503
        assert resp.headers.get("Retry-After") == "15"
        mock_capture.assert_called_once()
        assert isinstance(mock_capture.call_args.args[0], LLMBusyError)

    def test_get_suggestions_500_when_all_picks_malformed(self):
        """An all-malformed LLM reply is a 500, not a false "no_candidates" 200."""
        user = _make_user(privacy_policy_accepted=True)
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: AsyncMock()

        candidates = [
            {"trakt_id": i, "movie_id": f"00000000-0000-0000-0000-{i:012d}"}
            for i in range(1, 10)
        ]
        profile = {"total_ranked": 20, "genre_affinities": {}, "top_10": [], "bottom_5": []}

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
            "backend.services.suggest._build_taste_profile",
            new_callable=AsyncMock,
            return_value=profile,
        ), patch(
            "backend.services.suggest._get_candidates",
            new_callable=AsyncMock,
            return_value=candidates,
        ), patch(
            "backend.services.suggest._call_llm",
            new_callable=AsyncMock,
            return_value=["oops", {"trakt_id": True}],
        ):
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.get("/api/suggestions")

        assert resp.status_code == 500


def _fake_suggestion_schema() -> SuggestionSchema:
    return SuggestionSchema(
        id=str(uuid.uuid4()),
        movie=MovieSchema(
            id=str(uuid.uuid4()), trakt_id=42, title="Test Film", media_type="movie"
        ),
        reason="test reason",
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _make_suggestion(owner_id: uuid.UUID) -> Suggestion:
    """Build a real transient Suggestion/Movie pair so _build_suggestion_schema
    runs for real and the response reflects actual state."""
    movie = Movie(
        id=uuid.uuid4(),
        trakt_id=42,
        title="Test Film",
        media_type="movie",
        poster_url="https://img/x.jpg",
    )
    return Suggestion(
        id=uuid.uuid4(),
        user_id=owner_id,
        movie_id=movie.id,
        movie=movie,
        reason="r",
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
        ) as self.mock_lock, patch(
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

    def test_generation_shares_the_regenerate_quota_lock(self):
        """GET and POST /regenerate must contend for one advisory lock (AUD-08)."""
        self._get(active=[], latest=None)

        self.mock_lock.assert_awaited_once_with(
            ANY, REGENERATION_DAILY_QUOTA.name, self.user.id
        )

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

    def test_batch_committed_between_reads_is_not_reported_all_dismissed(self):
        """A concurrent first batch landing after GET's first read must not make
        an undismissed batch look all-dismissed (read active only after latest)."""
        fresh = datetime.now(timezone.utc) - timedelta(minutes=1)
        reads = 0

        def committed_after_first_read(before, after):
            async def read(*args, **kwargs):
                nonlocal reads
                reads += 1
                return before if reads == 1 else after

            return read

        with patch(
            "backend.routers.suggestions.has_enough_ranked",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "backend.routers.suggestions._get_active_suggestions",
            side_effect=committed_after_first_read([], [MagicMock()]),
        ), patch(
            "backend.routers.suggestions._latest_generated_at",
            side_effect=committed_after_first_read(None, fresh),
        ), patch(
            "backend.routers.suggestions.try_acquire_xact_lock",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "backend.routers.suggestions._create_suggestions",
            new_callable=AsyncMock,
        ) as mock_create, patch(
            "backend.routers.suggestions._build_suggestion_schema",
            return_value=_fake_suggestion_schema(),
        ):
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.get("/api/suggestions")

        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"
        mock_create.assert_not_awaited()


class TestGetSuggestionsEmptyCooldown:
    """An LLM reply with nothing usable must not be retried on the next GET (SEC-11, #783)."""

    CANDIDATES = [
        {
            "trakt_id": i,
            "movie_id": f"00000000-0000-0000-0000-{i:012d}",
            "title": f"Film {i}",
            "year": 2000 + i,
            "community_rating": None,
        }
        for i in range(1, 10)
    ]

    def setup_method(self):
        app.dependency_overrides.clear()
        self.user = _make_user(privacy_policy_accepted=True)
        app.dependency_overrides[get_current_user] = lambda: self.user
        app.dependency_overrides[get_db] = lambda: AsyncMock()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _get_twice(self, llm_reply="", *, llm_error=None, candidates=None, query=""):
        """GET twice against the real generate_suggestions; return (responses, LLM mock).

        llm_reply is the raw reply text; llm_error, when set, is raised by the LLM call instead.
        """
        profile = {"total_ranked": 20, "genre_affinities": {}, "top_10": [], "bottom_5": []}
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
            "backend.services.suggest._build_taste_profile",
            new_callable=AsyncMock,
            return_value=profile,
        ), patch(
            "backend.services.suggest._get_candidates",
            new_callable=AsyncMock,
            return_value=self.CANDIDATES if candidates is None else candidates,
        ), patch(
            "backend.services.suggest.chat_completion",
            new_callable=AsyncMock,
            return_value=llm_reply,
            side_effect=llm_error,
        ) as mock_llm:
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                responses = [client.get(f"/api/suggestions{query}") for _ in range(2)]
        return responses, mock_llm

    def test_out_of_pool_reply_is_not_retried_on_next_get(self):
        responses, mock_llm = self._get_twice('{"picks": [{"trakt_id": 999}]}')

        for resp in responses:
            assert resp.status_code == 200
            assert resp.json() == {"suggestions": [], "status": "no_candidates"}
        assert mock_llm.await_count == 1

    def test_malformed_reply_is_not_retried_on_next_get(self):
        responses, mock_llm = self._get_twice('{"picks": ["oops"]}')

        assert responses[0].status_code == 500
        assert responses[1].status_code == 200
        assert responses[1].json()["status"] == "no_candidates"
        assert mock_llm.await_count == 1

    @pytest.mark.parametrize(
        "llm_reply",
        ['Here are my picks: {"picks": [', '{"suggestions": []}', '[]', '{"picks": 6}', ""],
    )
    def test_unusable_reply_is_not_retried_on_next_get(self, llm_reply):
        responses, mock_llm = self._get_twice(llm_reply)

        assert responses[0].status_code == 500
        assert responses[1].status_code == 200
        assert responses[1].json()["status"] == "no_candidates"
        assert mock_llm.await_count == 1

    def test_busy_llm_does_not_start_cooldown(self):
        """A transient failure answers 503 and retry; a cooldown would contradict that."""
        from backend.services.llm import LLMBusyError

        responses, mock_llm = self._get_twice(llm_error=LLMBusyError("busy"))

        assert [r.status_code for r in responses] == [503, 503]
        assert mock_llm.await_count == 2

    def test_unexpected_value_error_is_not_reported_as_unconfigured(self):
        """Only LLMNotConfiguredError means a missing key; any other ValueError is a bug."""
        responses, _ = self._get_twice(llm_error=ValueError("parsing bug"))

        assert responses[0].status_code == 500
        assert "AI features are not available" not in responses[0].text

    def test_llm_request_failure_answers_500(self):
        responses, _ = self._get_twice(llm_error=httpx.ConnectError("refused"))

        assert responses[0].status_code == 500
        assert responses[0].json()["detail"] == (
            "Failed to generate suggestions. Please try again later."
        )

    def test_insufficient_candidates_does_not_start_cooldown(self):
        """No LLM call was made, so "swipe more, then come back" must keep working."""
        from backend.rate_limit import empty_suggestions_recent

        _, mock_llm = self._get_twice(candidates=self.CANDIDATES[:3])

        mock_llm.assert_not_awaited()
        assert empty_suggestions_recent(self.user.id, "movie") is False

    def test_cooldown_is_per_media_type(self):
        from backend.rate_limit import record_empty_suggestions

        record_empty_suggestions(self.user.id, "movie")
        _, mock_llm = self._get_twice('{"picks": [{"trakt_id": 999}]}', query="?media_type=show")

        assert mock_llm.await_count == 1


class TestLatestGeneratedAt:
    @pytest.mark.asyncio
    async def test_freshness_includes_dismissed_rows(self):
        """Filtering dismissed rows out of freshness would reopen AUD-08 (#690)."""
        from sqlalchemy.dialects import postgresql

        from backend.routers.suggestions import _latest_generated_at

        db = AsyncMock()
        db.execute.return_value = MagicMock()

        await _latest_generated_at(uuid.uuid4(), db, "movie")

        sql = str(db.execute.call_args.args[0].compile(dialect=postgresql.dialect()))
        assert "max(suggestions.generated_at)" in sql
        assert "dismissed_at" not in sql


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
            i for i, c in enumerate(compiled) if "advisory_xact_lock" in str(c)
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
            "advisory_xact_lock" in str(stmt.compile(dialect=postgresql.dialect()))
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
        # Mock _create_suggestions to raise LLMNotConfiguredError

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
            side_effect=LLMNotConfiguredError("LLM_API_KEY not configured"),
        ):
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.post("/api/suggestions/regenerate")

        assert resp.status_code == 503
        assert resp.json()["detail"] == "AI features are not available"

    def test_regenerate_returns_503_when_llm_busy(self):
        """A full LLM concurrency guard (AUD-01) maps to 503, not 500."""
        from backend.services.llm import LLMBusyError

        user = _make_user(privacy_policy_accepted=True)
        mock_db = AsyncMock()
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0
        mock_db.execute.return_value = mock_count_result

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
            side_effect=LLMBusyError("busy"),
        ):
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.post("/api/suggestions/regenerate")

        assert resp.status_code == 503
        assert resp.headers.get("Retry-After") == "15"

    def test_regenerate_429_when_lock_held(self):
        """A concurrent regenerate for the same user is rejected, not queued (AUD-01)."""
        user = _make_user(privacy_policy_accepted=True)
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = False  # lock not acquired
        mock_db.execute.return_value = mock_result

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch(
            "backend.routers.suggestions.has_enough_ranked",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "backend.routers.suggestions._create_suggestions",
            new_callable=AsyncMock,
        ) as mock_create:
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.post("/api/suggestions/regenerate")

        assert resp.status_code == 429
        mock_create.assert_not_awaited()

    def test_regenerate_ignores_empty_cooldown(self):
        """Manual regenerate has its own cap; the GET cooldown must not block it."""
        from backend.rate_limit import record_empty_suggestions

        user = _make_user(privacy_policy_accepted=True)
        mock_db = AsyncMock()
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0
        mock_db.execute.return_value = mock_count_result

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: mock_db
        record_empty_suggestions(user.id, "movie")

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
            return_value=[],
        ) as mock_create:
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                client.post("/api/suggestions/regenerate")

        mock_create.assert_awaited_once()


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


# ---------------------------------------------------------------------------
# Item 4: mark_seen updates or creates a UserMovie
# ---------------------------------------------------------------------------


class TestMarkSeen:
    def setup_method(self):
        app.dependency_overrides.clear()
        self.user = _make_user()
        app.dependency_overrides[get_current_user] = lambda: self.user

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_mark_seen_updates_existing_user_movie(self):
        s = _make_suggestion(self.user.id)
        um = UserMovie(user_id=self.user.id, movie_id=s.movie_id, seen=None)

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.execute.return_value = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = um
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch(
            "backend.routers.suggestions._get_user_suggestion",
            new_callable=AsyncMock,
            return_value=s,
        ):
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.post(f"/api/suggestions/{s.id}/seen")

        assert resp.status_code == 200
        assert um.seen is True
        assert um.updated_at is not None
        assert s.dismissed_at is not None
        assert resp.json()["dismissed_at"] is not None
        mock_db.add.assert_not_called()

    def test_mark_seen_creates_user_movie_when_missing(self):
        s = _make_suggestion(self.user.id)

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.execute.return_value = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch(
            "backend.routers.suggestions._get_user_suggestion",
            new_callable=AsyncMock,
            return_value=s,
        ):
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.post(f"/api/suggestions/{s.id}/seen")

        assert resp.status_code == 200
        mock_db.add.assert_called_once()
        created = mock_db.add.call_args.args[0]
        assert isinstance(created, UserMovie)
        assert created.user_id == self.user.id
        assert created.movie_id == s.movie_id
        assert created.seen is True
        assert resp.json()["dismissed_at"] is not None


# ---------------------------------------------------------------------------
# Item 5: acting on another user's suggestion is a 404
# ---------------------------------------------------------------------------


class TestSuggestionOwnership:
    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _fake_db(self, owner_id: uuid.UUID, s: Suggestion) -> AsyncMock:
        from sqlalchemy.dialects import postgresql

        async def fake_execute(stmt, *args, **kwargs):
            compiled = stmt.compile(dialect=postgresql.dialect())
            params = set(compiled.params.values())
            result = MagicMock()
            if owner_id in params or str(owner_id) in params:
                result.unique.return_value.scalar_one_or_none.return_value = s
            else:
                result.unique.return_value.scalar_one_or_none.return_value = None
            return result

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=fake_execute)
        return mock_db

    @pytest.mark.parametrize("action", ["dismiss", "watchlist", "seen"])
    def test_other_users_suggestion_is_not_found(self, action):
        owner_id = uuid.uuid4()
        s = _make_suggestion(owner_id)
        mock_db = self._fake_db(owner_id, s)
        user = _make_user()  # different id from owner_id

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch("backend.routers.suggestions.async_session_factory"), patch(
            "backend.routers.suggestions.TraktClient"
        ):
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.post(f"/api/suggestions/{s.id}/{action}")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Suggestion not found"
        assert s.dismissed_at is None
        assert s.added_to_watchlist_at is None

    def test_owner_can_act_on_own_suggestion(self):
        owner_id = uuid.uuid4()
        s = _make_suggestion(owner_id)
        mock_db = self._fake_db(owner_id, s)
        user = _make_user()
        user.id = owner_id

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: mock_db

        with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
            resp = client.post(f"/api/suggestions/{s.id}/dismiss")

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Item 6: dismiss sets dismissed_at; dismissed rows drop out of the active list
# ---------------------------------------------------------------------------


class TestDismiss:
    def setup_method(self):
        app.dependency_overrides.clear()
        self.user = _make_user()
        app.dependency_overrides[get_current_user] = lambda: self.user
        app.dependency_overrides[get_db] = lambda: AsyncMock()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_dismiss_sets_dismissed_at(self):
        s = _make_suggestion(self.user.id)

        with patch(
            "backend.routers.suggestions._get_user_suggestion",
            new_callable=AsyncMock,
            return_value=s,
        ):
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.post(f"/api/suggestions/{s.id}/dismiss")

        assert resp.status_code == 200
        assert s.dismissed_at is not None
        now = datetime.now(timezone.utc)
        assert abs((now - s.dismissed_at).total_seconds()) < 5
        body = resp.json()
        assert body["dismissed_at"] is not None
        assert body["id"] == str(s.id)


class TestActiveSuggestions:
    @pytest.mark.asyncio
    async def test_active_list_excludes_dismissed(self):
        from sqlalchemy.dialects import postgresql

        from backend.routers.suggestions import _get_active_suggestions

        db = AsyncMock()
        db.execute.return_value = MagicMock()
        db.execute.return_value.unique.return_value.scalars.return_value.all.return_value = []

        await _get_active_suggestions(uuid.uuid4(), db, "show")

        stmt = db.execute.call_args.args[0]
        compiled = stmt.compile(dialect=postgresql.dialect())
        sql = str(compiled)

        assert "suggestions.dismissed_at IS NULL" in sql
        assert "movies.poster_url IS NOT NULL" in sql
        assert "show" in compiled.params.values()


# ---------------------------------------------------------------------------
# Item 7: watchlist background sync failure paths
# ---------------------------------------------------------------------------


class TestSyncTraktWatchlistFailures:
    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _post_watchlist(self, bg_user_token, add_side_effect=None):
        """POST .../watchlist with the background sync's token lookup and Trakt
        call mocked. Returns (resp, mock_ensure_fresh, mock_trakt_cls)."""
        user = _make_user()
        s = _make_suggestion(user.id)

        bg_user = MagicMock()
        bg_user.trakt_access_token = bg_user_token

        async def fake_bg_session_execute(stmt, *args, **kwargs):
            result = MagicMock()
            result.scalar_one_or_none.return_value = bg_user
            return result

        mock_bg_session = AsyncMock()
        mock_bg_session.execute.side_effect = fake_bg_session_execute
        mock_bg_session.commit = AsyncMock()

        mock_db = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: mock_db

        with (
            patch(
                "backend.routers.suggestions._get_user_suggestion",
                new_callable=AsyncMock,
                return_value=s,
            ),
            patch(
                "backend.routers.suggestions.async_session_factory"
            ) as mock_factory,
            patch(
                "backend.routers.suggestions.ensure_fresh_token",
                new_callable=AsyncMock,
                return_value=bg_user,
            ) as mock_ensure_fresh,
            patch(
                "backend.routers.suggestions.TraktClient"
            ) as mock_trakt_cls,
        ):
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_bg_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_trakt_cls.return_value = AsyncMock()
            mock_trakt_cls.return_value.add_to_watchlist = AsyncMock(side_effect=add_side_effect)

            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=True) as client:
                resp = client.post(f"/api/suggestions/{s.id}/watchlist")

        return resp, mock_ensure_fresh, mock_trakt_cls

    def test_no_trakt_token_skips_sync(self):
        resp, mock_ensure_fresh, mock_trakt_cls = self._post_watchlist(bg_user_token=None)

        assert resp.status_code == 200
        mock_ensure_fresh.assert_not_awaited()
        mock_trakt_cls.assert_not_called()

    def test_trakt_failure_is_logged_not_raised(self, caplog):
        import logging

        with caplog.at_level(logging.ERROR, logger="backend.routers.suggestions"):
            resp, _, mock_trakt_cls = self._post_watchlist(
                bg_user_token="valid-token",
                add_side_effect=httpx.ConnectError("down"),
            )

        assert resp.status_code == 200
        assert resp.json()["added_to_watchlist_at"] is not None
        mock_trakt_cls.return_value.add_to_watchlist.assert_awaited_once_with(42)
        assert "Failed to sync watchlist to Trakt for movie 42" in caplog.text
