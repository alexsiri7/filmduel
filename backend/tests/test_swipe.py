"""Tests for swipe logic (band indexing, community rating, next_action) and purge endpoint."""

import logging
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from backend.db import get_db
from backend.main import app
from backend.routers.auth import CURRENT_PRIVACY_POLICY_VERSION, get_current_user
from backend.services.swipe import MAX_SWIPES_PER_DAY
from backend.services.duel import should_suggest_swipe
from backend.services.swipe import (
    BANDS,
    _community_rating_range,
    _elo_to_band_index,
    count_unresolved,
    plan_card_mix,
    select_swipe_cards,
)
from backend.tests import SPA_HEADERS

# ---------------------------------------------------------------------------
# _elo_to_band_index
# ---------------------------------------------------------------------------


class TestEloToBandIndex:
    def test_elite(self):
        assert _elo_to_band_index(1300) == 0
        assert _elo_to_band_index(9999) == 0

    def test_strong(self):
        assert _elo_to_band_index(1100) == 1
        assert _elo_to_band_index(1299) == 1

    def test_mid(self):
        assert _elo_to_band_index(900) == 2
        assert _elo_to_band_index(1099) == 2

    def test_weak(self):
        assert _elo_to_band_index(700) == 3
        assert _elo_to_band_index(899) == 3

    def test_low(self):
        assert _elo_to_band_index(0) == 4
        assert _elo_to_band_index(699) == 4

    def test_out_of_range_defaults_to_mid(self):
        # Negative ELO is not in any band range -> defaults to 2 (mid)
        assert _elo_to_band_index(-100) == 2

    def test_exact_boundaries(self):
        # Check each boundary value
        assert _elo_to_band_index(1300) == 0  # elite lower bound
        assert _elo_to_band_index(1100) == 1  # strong lower bound
        assert _elo_to_band_index(900) == 2  # mid lower bound
        assert _elo_to_band_index(700) == 3  # weak lower bound


# ---------------------------------------------------------------------------
# _community_rating_range
# ---------------------------------------------------------------------------


class TestCommunityRatingRange:
    def test_elite_range(self):
        low, high = _community_rating_range(0)
        assert low == 80.0
        assert high == 100.0

    def test_strong_range(self):
        low, high = _community_rating_range(1)
        assert low == 65.0
        assert high == 79.9

    def test_mid_range(self):
        low, high = _community_rating_range(2)
        assert low == 45.0
        assert high == 64.9

    def test_weak_range(self):
        low, high = _community_rating_range(3)
        assert low == 25.0
        assert high == 44.9

    def test_low_range(self):
        low, high = _community_rating_range(4)
        assert low == 0.0
        assert high == 24.9

    def test_returns_floats(self):
        low, high = _community_rating_range(0)
        assert isinstance(low, float)
        assert isinstance(high, float)


# ---------------------------------------------------------------------------
# BANDS structure
# ---------------------------------------------------------------------------


class TestBandsStructure:
    def test_has_5_bands(self):
        assert len(BANDS) == 5

    def test_band_names(self):
        names = [b[0] for b in BANDS]
        assert names == ["elite", "strong", "mid", "weak", "poor"]

    def test_elo_ranges_descending(self):
        """ELO lower bounds should be strictly descending from elite to low."""
        lows = [b[1] for b in BANDS]
        for i in range(len(lows) - 1):
            assert lows[i] > lows[i + 1], (
                f"Band {i} low={lows[i]} not > band {i + 1} low={lows[i + 1]}"
            )

    def test_community_rating_ranges_descending(self):
        """CR lower bounds should be strictly descending from elite to low."""
        cr_lows = [b[3] for b in BANDS]
        for i in range(len(cr_lows) - 1):
            assert cr_lows[i] > cr_lows[i + 1], (
                f"Band {i} cr_low={cr_lows[i]} not > band {i + 1} cr_low={cr_lows[i + 1]}"
            )


# ---------------------------------------------------------------------------
# next_action logic (swipe vs duel threshold)
# ---------------------------------------------------------------------------


class TestNextActionLogic:
    """Tests for the next_action determination in swipe results.

    The rule: suggest swipe when seen_unranked < MIN_SEEN_UNRANKED (3)
              or total_seen < MIN_TOTAL_SEEN (10).
    """

    def test_threshold_met_suggests_duel(self):
        # enough seen_unranked AND enough total_seen -> duel (should_suggest_swipe returns False)
        assert should_suggest_swipe(3, 10) is False
        assert should_suggest_swipe(5, 100) is False

    def test_below_seen_unranked_threshold_suggests_swipe(self):
        # seen_unranked < 3 -> swipe
        assert should_suggest_swipe(0, 10) is True
        assert should_suggest_swipe(2, 10) is True

    def test_below_total_seen_threshold_suggests_swipe(self):
        # total_seen < 10 -> swipe
        assert should_suggest_swipe(3, 0) is True
        assert should_suggest_swipe(3, 9) is True


# ---------------------------------------------------------------------------
# Purge old swipe results
# ---------------------------------------------------------------------------


def _make_user():
    user = MagicMock()
    user.id = uuid.uuid4()
    user.is_admin = True
    return user


def _make_db():
    return AsyncMock()


class TestPurgeSwipeResults:
    def _delete(self, client, purged_ids=None):
        user = _make_user()
        db = _make_db()
        purged_ids = purged_ids or []
        db.execute = AsyncMock(
            return_value=MagicMock(
                fetchall=MagicMock(return_value=[(pid,) for pid in purged_ids])
            )
        )
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: db
        try:
            return client.delete("/api/swipe/admin/purge-old-records")
        finally:
            app.dependency_overrides.clear()

    def test_returns_purged_count(self):
        purged = [uuid.uuid4(), uuid.uuid4()]
        client = TestClient(app, headers=SPA_HEADERS)
        response = self._delete(client, purged_ids=purged)
        assert response.status_code == 200
        assert response.json() == {"purged": 2}

    def test_returns_zero_when_nothing_to_purge(self):
        client = TestClient(app, headers=SPA_HEADERS)
        response = self._delete(client, purged_ids=[])
        assert response.status_code == 200
        assert response.json() == {"purged": 0}

    def test_non_admin_returns_403(self):
        user = _make_user()
        user.is_admin = False
        db = _make_db()
        client = TestClient(app, headers=SPA_HEADERS)
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: db
        try:
            response = client.delete("/api/swipe/admin/purge-old-records")
        finally:
            app.dependency_overrides.clear()
        assert response.status_code == 403
        assert "admin" in response.json()["detail"].lower()

    def test_unauthenticated_returns_401(self):
        client = TestClient(app, headers=SPA_HEADERS)
        # No dependency overrides — auth stack runs normally
        response = client.delete("/api/swipe/admin/purge-old-records")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# plan_card_mix
# ---------------------------------------------------------------------------


class TestPlanCardMix:
    def test_no_ranked_films_draws_any_rated_film(self):
        assert plan_card_mix(None) == [(None, 10)]

    def test_mid_band_takes_neighbours_above_and_below(self):
        assert plan_card_mix(1000) == [
            ((45.0, 64.9), 6),
            ((65.0, 79.9), 2),
            ((25.0, 44.9), 2),
        ]

    def test_out_of_range_elo_defaults_to_mid(self):
        assert plan_card_mix(-100) == plan_card_mix(1000)

    def test_elite_clamps_above_to_target(self):
        # SEC-018: the clamped part repeats the target range, so its rows can duplicate.
        assert plan_card_mix(1300) == [
            ((80.0, 100.0), 6),
            ((80.0, 100.0), 2),
            ((65.0, 79.9), 2),
        ]

    def test_poor_clamps_below_to_target(self):
        assert plan_card_mix(699) == [
            ((0.0, 24.9), 6),
            ((25.0, 44.9), 2),
            ((0.0, 24.9), 2),
        ]

    def test_fractional_median_uses_band_of_truncated_elo(self):
        assert plan_card_mix(1299.9)[0] == ((65.0, 79.9), 6)

    def test_counts_fill_the_session(self):
        assert sum(n for _, n in plan_card_mix(1000, session_size=20)) == 20
        assert [n for _, n in plan_card_mix(1000, session_size=20)] == [12, 4, 4]


class TestSelectSwipeCards:
    @staticmethod
    def _db(median_elo, part_results):
        """Fake db: the first query is the median ELO, the rest return `part_results` in order."""
        results = iter(part_results)
        statements: list[str] = []

        async def fake_execute(stmt, *args, **kwargs):
            statements.append(str(stmt.compile(dialect=postgresql.dialect())).lower())
            result = MagicMock()
            if len(statements) == 1:
                result.scalar_one_or_none.return_value = median_elo
            else:
                result.all.return_value = next(results)
            return result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)
        return db, statements

    @staticmethod
    def _rows(*ids):
        return [MagicMock(id=i) for i in ids]

    @pytest.mark.asyncio
    async def test_elite_dedups_clamped_part_and_backfills_once(self):
        db, statements = self._db(
            1400, [self._rows(1, 2, 3), self._rows(2, 3), self._rows(4), self._rows(5)]
        )

        rows = await select_swipe_cards(db, uuid.uuid4(), "movie")

        assert [r.id for r in rows] == [1, 2, 3, 4, 5]
        parts, backfill = statements[1:4], statements[4:]
        assert all("community_rating between" in sql for sql in parts)
        assert len(backfill) == 1
        assert "not in" in backfill[0] and "community_rating" not in backfill[0].split("where")[1]

    @pytest.mark.asyncio
    async def test_no_ranked_films_draws_rated_films_without_backfill_when_full(self):
        db, statements = self._db(None, [self._rows(*range(10))])

        rows = await select_swipe_cards(db, uuid.uuid4(), "movie")

        assert len(rows) == 10
        assert len(statements) == 2
        assert "community_rating is not null" in statements[1]


# ---------------------------------------------------------------------------
# Submit results — unresolved-card filter and daily cap (SEC-21, #589)
# ---------------------------------------------------------------------------


class TestSubmitSwipeResults:
    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _install(self, *, user_movies, daily_count=0):
        """Install a consented user and a db fake that dispatches on compiled SQL.

        `user_movies` maps movie_id -> UserMovie mock for the ids that are still
        unresolved; any other id resolves to None. Returns (user, db, statements).
        """
        user = _make_user()
        user.is_admin = False
        user.privacy_policy_accepted = True
        user.privacy_policy_version = CURRENT_PRIVACY_POLICY_VERSION
        db = _make_db()
        db.add = MagicMock()
        statements: list = []

        async def fake_execute(stmt, *args, **kwargs):
            statements.append(stmt)
            compiled = stmt.compile(dialect=postgresql.dialect())
            sql = str(compiled).lower()
            result = MagicMock()
            if "pg_advisory_xact_lock" in sql:
                return result
            if "count(" in sql and "swipe_results" in sql:
                result.scalar_one.return_value = daily_count
            elif "count(" in sql and "user_movies" in sql and "movie_id in" in sql:
                ids = next(v for v in compiled.params.values() if isinstance(v, list))
                result.scalar_one.return_value = sum(m in user_movies for m in ids)
            elif "count(" in sql and "user_movies" in sql:
                result.scalar.return_value = 100  # pool not low; no expand_pool
            else:
                # Both user_id and movie_id are UUID params; match on registered ids.
                um = next(
                    (user_movies[v] for v in compiled.params.values() if v in user_movies),
                    None,
                )
                result.scalar_one_or_none.return_value = um
            return result

        db.execute = AsyncMock(side_effect=fake_execute)
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: db
        return user, db, statements

    def _post(self, results):
        with patch(
            "backend.routers.swipe.compute_next_action",
            new_callable=AsyncMock,
            return_value="duel",
        ) as mock_next:
            with TestClient(app, headers=SPA_HEADERS, raise_server_exceptions=False) as client:
                resp = client.post("/api/swipe/results", json={"results": results})
        return resp, mock_next

    @staticmethod
    def _user_movie_selects(statements):
        compiled = [str(s.compile(dialect=postgresql.dialect())).lower() for s in statements]
        return [c for c in compiled if "from user_movies" in c and "count(" not in c]

    def test_skips_movies_that_are_not_unresolved_cards(self):
        served, resolved = uuid.uuid4(), uuid.uuid4()
        um = MagicMock()
        _, db, statements = self._install(user_movies={served: um})

        resp, _ = self._post(
            [
                {"movie_id": str(served), "seen": True},
                {"movie_id": str(resolved), "seen": True},
            ]
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["seen_count"] == 1
        assert body["unseen_count"] == 0
        assert um.seen is True
        assert db.add.call_count == 1
        assert db.add.call_args.args[0].movie_id == served

        selects = self._user_movie_selects(statements)
        assert len(selects) == 2
        assert all("seen is null" in c for c in selects)

    def test_skipped_items_are_not_logged_at_warning(self, caplog):
        """Skips pair a user id with a movie id and fire on benign duel races,
        so they are summarized at DEBUG only, never WARNING (SEC-21, #589)."""
        served, resolved = uuid.uuid4(), uuid.uuid4()
        user, _, _ = self._install(user_movies={served: MagicMock()})

        with caplog.at_level(logging.DEBUG, logger="backend.routers.swipe"):
            resp, _ = self._post(
                [
                    {"movie_id": str(served), "seen": True},
                    {"movie_id": str(resolved), "seen": True},
                ]
            )

        assert resp.status_code == 200
        records = [r for r in caplog.records if r.name == "backend.routers.swipe"]
        assert not [r for r in records if r.levelno >= logging.WARNING]
        assert any(
            r.levelno == logging.DEBUG
            and r.getMessage() == f"swipe_submit_skipped user_id={user.id} skipped=1"
            for r in records
        )

    def test_duplicate_movie_ids_in_one_batch_write_one_row(self):
        served = uuid.uuid4()
        um = MagicMock()
        _, db, statements = self._install(user_movies={served: um})

        resp, _ = self._post(
            [
                {"movie_id": str(served), "seen": True},
                {"movie_id": str(served), "seen": True},
                {"movie_id": str(served), "seen": False},
            ]
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["seen_count"] == 0
        assert body["unseen_count"] == 1
        assert um.seen is False
        assert db.add.call_count == 1
        assert len(self._user_movie_selects(statements)) == 1

    def test_daily_cap_returns_429(self):
        served = uuid.uuid4()
        _, db, _ = self._install(
            user_movies={served: MagicMock()}, daily_count=MAX_SWIPES_PER_DAY
        )

        resp, mock_next = self._post([{"movie_id": str(served), "seen": True}])

        assert resp.status_code == 429
        assert "Daily swipe limit" in resp.json()["detail"]
        db.add.assert_not_called()
        mock_next.assert_not_awaited()

    def test_batch_that_would_cross_daily_cap_is_refused_whole(self):
        served = [uuid.uuid4() for _ in range(3)]
        _, db, _ = self._install(
            user_movies={m: MagicMock() for m in served}, daily_count=MAX_SWIPES_PER_DAY - 2
        )

        resp, mock_next = self._post([{"movie_id": str(m), "seen": True} for m in served])

        assert resp.status_code == 429
        db.add.assert_not_called()
        mock_next.assert_not_awaited()

    def test_batch_that_reaches_daily_cap_counts_repeated_titles_once(self):
        served = [uuid.uuid4() for _ in range(2)]
        _, db, _ = self._install(
            user_movies={m: MagicMock() for m in served}, daily_count=MAX_SWIPES_PER_DAY - 2
        )

        resp, _ = self._post(
            [{"movie_id": str(m), "seen": True} for m in served]
            + [{"movie_id": str(served[0]), "seen": False}]
        )

        assert resp.status_code == 200
        assert db.add.call_count == 2

    def test_already_resolved_titles_do_not_count_against_daily_cap(self):
        served = [uuid.uuid4() for _ in range(2)]
        resolved = uuid.uuid4()
        _, db, _ = self._install(
            user_movies={m: MagicMock() for m in served}, daily_count=MAX_SWIPES_PER_DAY - 2
        )

        resp, _ = self._post([{"movie_id": str(m), "seen": True} for m in [*served, resolved]])

        assert resp.status_code == 200
        assert resp.json()["seen_count"] == 2
        assert db.add.call_count == 2

    def test_daily_cap_check_is_serialized_per_user(self):
        """The cap count must run under a per-user advisory lock (SEC-02, #570)."""
        served = uuid.uuid4()
        user, _, statements = self._install(
            user_movies={served: MagicMock()}, daily_count=MAX_SWIPES_PER_DAY
        )

        resp, _ = self._post([{"movie_id": str(served), "seen": True}])
        assert resp.status_code == 429

        compiled = [stmt.compile(dialect=postgresql.dialect()) for stmt in statements]
        lock_idx = next(
            i for i, c in enumerate(compiled) if "pg_advisory_xact_lock" in str(c)
        )
        count_idx = next(
            i for i, c in enumerate(compiled)
            if "count(" in str(c).lower() and "swipe_results" in str(c).lower()
        )
        assert lock_idx < count_idx, "advisory lock must be taken before the daily count"

        lock_params = set(compiled[lock_idx].params.values())
        assert "swipe_daily_cap" in lock_params
        assert str(user.id) in lock_params


@pytest.mark.asyncio
async def test_count_unresolved_counts_only_this_users_unresolved_rows():
    """The cap's batch size must count exactly the rows record_swipes will write."""
    db = AsyncMock()
    db.execute.return_value = MagicMock(scalar_one=MagicMock(return_value=0))
    user_id = uuid.uuid4()
    movie_id = uuid.uuid4()

    await count_unresolved(db, user_id, {movie_id})

    compiled = db.execute.await_args.args[0].compile(dialect=postgresql.dialect())
    params = {str(v) for v in compiled.params.values()}
    assert str(user_id) in params
    assert "user_movies.seen is null" in str(compiled).lower()
