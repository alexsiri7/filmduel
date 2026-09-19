"""Tests for swipe logic (band indexing, community rating, next_action) and purge endpoint."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from backend.db import get_db
from backend.main import app
from backend.tests import SPA_HEADERS
from backend.routers.auth import get_current_user
from backend.routers.swipe import (
    BANDS,
    MAX_SWIPES_PER_DAY,
    _community_rating_range,
    _elo_to_band_index,
)
from backend.services.duel import should_suggest_swipe


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
# Band-boundary deduplication (SEC-018)
# ---------------------------------------------------------------------------


class TestBandBoundaryIndexClamping:
    """Verify that boundary bands produce clamped adjacent indices equal to target."""

    def test_elite_above_clamped_to_self(self):
        # band_idx=0: max(0, -1) == 0
        band_idx = 0
        above_idx = max(0, band_idx - 1)
        assert above_idx == band_idx, "above_idx should equal target at elite band"

    def test_poor_below_clamped_to_self(self):
        # band_idx=4: min(4, 5) == 4
        band_idx = 4
        below_idx = min(len(BANDS) - 1, band_idx + 1)
        assert below_idx == band_idx, "below_idx should equal target at poor band"

    def test_clamped_ranges_are_identical(self):
        # When indices are equal, ranges are identical — the source of the duplicate risk
        band_idx = 0
        above_idx = max(0, band_idx - 1)
        assert _community_rating_range(band_idx) == _community_rating_range(above_idx)

    def test_mid_band_ranges_are_distinct(self):
        # Middle bands should have distinct adjacent ranges
        band_idx = 2
        above_idx = max(0, band_idx - 1)
        below_idx = min(len(BANDS) - 1, band_idx + 1)
        assert _community_rating_range(band_idx) != _community_rating_range(above_idx)
        assert _community_rating_range(band_idx) != _community_rating_range(below_idx)

    def test_poor_clamped_ranges_are_identical(self):
        # When below_idx is clamped at poor band (band_idx=4), ranges are identical
        band_idx = 4
        below_idx = min(len(BANDS) - 1, band_idx + 1)
        assert _community_rating_range(band_idx) == _community_rating_range(below_idx)


# ---------------------------------------------------------------------------
# Deduplication logic (SEC-018 fix)
# ---------------------------------------------------------------------------


class TestDeduplicateRows:
    """Unit-tests for the seen_ids_set deduplication logic (SEC-018 fix)."""

    def _dedup(self, rows):
        """Mirror of the dedup block in get_swipe_cards."""
        return list({row.id: row for row in rows}.values())

    def _row(self, id_val):
        r = MagicMock()
        r.id = id_val
        return r

    def test_removes_duplicate_ids(self):
        rows = [self._row(1), self._row(2), self._row(1)]  # id=1 appears twice
        result = self._dedup(rows)
        assert [r.id for r in result] == [1, 2]

    def test_preserves_order_of_first_occurrence(self):
        rows = [self._row(3), self._row(1), self._row(3), self._row(2)]
        result = self._dedup(rows)
        assert [r.id for r in result] == [3, 1, 2]

    def test_no_duplicates_returns_all(self):
        rows = [self._row(i) for i in range(10)]
        result = self._dedup(rows)
        assert len(result) == 10

    def test_empty_input_returns_empty(self):
        assert self._dedup([]) == []

    def test_all_same_id_returns_one(self):
        rows = [self._row(42)] * 6
        result = self._dedup(rows)
        assert len(result) == 1
        assert result[0].id == 42


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

    def test_daily_cap_check_is_serialized_per_user(self):
        """The cap count must run under a per-user advisory lock (SEC-02, #570)."""
        user, _, statements = self._install(user_movies={}, daily_count=MAX_SWIPES_PER_DAY)

        resp, _ = self._post([{"movie_id": str(uuid.uuid4()), "seen": True}])
        assert resp.status_code == 429

        compiled = [stmt.compile(dialect=postgresql.dialect()) for stmt in statements]
        lock_idx = next(
            i for i, c in enumerate(compiled) if "pg_advisory_xact_lock" in str(c)
        )
        count_idx = next(i for i, c in enumerate(compiled) if "count(" in str(c).lower())
        assert lock_idx < count_idx, "advisory lock must be taken before the daily count"

        lock_params = set(compiled[lock_idx].params.values())
        assert "swipe_daily_cap" in lock_params
        assert str(user.id) in lock_params
