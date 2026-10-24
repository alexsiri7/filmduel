"""Tests for the pool-import background job helpers in backend/routers/users.py.

Covers `_force_pool_sync`, `_run_pool_import`, and `_effective_pool_import_status`
with assertions that backend/tests/test_users_router.py's existing
TestRunPoolImport / TestRecordPoolImportOutcome / TestEffectivePoolImportStatus
classes do not make (provider-dispatch details, multi-session failure
fallbacks, and naive-datetime / missing-started_at edge cases).
"""

from __future__ import annotations

import logging
import types
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.routers.users import (
    _effective_pool_import_status,
    _force_pool_sync,
    _run_pool_import,
)


# ---------------------------------------------------------------------------
# _force_pool_sync — provider dispatch
# ---------------------------------------------------------------------------


class TestForcePoolSync:
    @pytest.mark.asyncio
    async def test_trakt_only_user_refreshes_trakt_token_only(self):
        user = MagicMock()
        user.trakt_access_token_enc = "enc"
        user.simkl_access_token_enc = None
        refreshed = MagicMock()
        # _force_pool_sync re-checks simkl_access_token_enc on the *returned*
        # user (which becomes `refreshed` after the trakt refresh), so this
        # must be falsy too or the simkl branch would spuriously fire.
        refreshed.simkl_access_token_enc = None
        db = MagicMock()

        with (
            patch(
                "backend.routers.users.ensure_fresh_token",
                new=AsyncMock(return_value=refreshed),
            ) as mock_trakt_refresh,
            patch(
                "backend.routers.users.ensure_fresh_simkl_token",
                new=AsyncMock(),
            ) as mock_simkl_refresh,
            patch(
                "backend.routers.users.populate_movie_pool",
                new=AsyncMock(return_value=True),
            ) as mock_pool,
        ):
            result = await _force_pool_sync(user, db)

        mock_trakt_refresh.assert_awaited_once_with(user, db)
        mock_simkl_refresh.assert_not_awaited()
        mock_pool.assert_awaited_once_with(refreshed, db, force=True)
        assert result == (refreshed, True)

    @pytest.mark.asyncio
    async def test_simkl_only_user_refreshes_simkl_token_only(self):
        user = MagicMock()
        user.trakt_access_token_enc = None
        user.simkl_access_token_enc = "enc"
        db = MagicMock()

        with (
            patch(
                "backend.routers.users.ensure_fresh_token",
                new=AsyncMock(),
            ) as mock_trakt_refresh,
            patch(
                "backend.routers.users.ensure_fresh_simkl_token",
                new=AsyncMock(return_value=user),
            ) as mock_simkl_refresh,
            patch(
                "backend.routers.users.populate_movie_pool",
                new=AsyncMock(return_value=False),
            ) as mock_pool,
        ):
            result = await _force_pool_sync(user, db)

        mock_trakt_refresh.assert_not_awaited()
        mock_simkl_refresh.assert_awaited_once_with(user, db)
        mock_pool.assert_awaited_once_with(user, db, force=True)
        assert result == (user, False)

    @pytest.mark.asyncio
    async def test_user_without_provider_tokens_skips_both_refreshes(self):
        user = MagicMock()
        user.trakt_access_token_enc = None
        user.simkl_access_token_enc = None
        db = MagicMock()

        with (
            patch(
                "backend.routers.users.ensure_fresh_token",
                new=AsyncMock(),
            ) as mock_trakt_refresh,
            patch(
                "backend.routers.users.ensure_fresh_simkl_token",
                new=AsyncMock(),
            ) as mock_simkl_refresh,
            patch(
                "backend.routers.users.populate_movie_pool",
                new=AsyncMock(return_value=True),
            ) as mock_pool,
        ):
            result = await _force_pool_sync(user, db)

        mock_trakt_refresh.assert_not_awaited()
        mock_simkl_refresh.assert_not_awaited()
        mock_pool.assert_awaited_once_with(user, db, force=True)
        assert result == (user, True)


# ---------------------------------------------------------------------------
# _run_pool_import — session-factory test helper
# ---------------------------------------------------------------------------


def _session_factory(*sessions):
    """A MagicMock async-session-factory.

    Its side_effect yields one context-manager mock per call, each wrapping
    the next session in `sessions` (so a second `async with
    async_session_factory() as session:` in the same test gets a distinct
    session/mock set).
    """
    managers = []
    for session in sessions:
        manager = MagicMock()
        manager.__aenter__ = AsyncMock(return_value=session)
        manager.__aexit__ = AsyncMock(return_value=False)
        managers.append(manager)
    return MagicMock(side_effect=managers)


def _recorded_params(session):
    (stmt,) = [c.args[0] for c in session.execute.await_args_list]
    return stmt.compile().params


# ---------------------------------------------------------------------------
# _run_pool_import — records the outcome of a successful sync
# ---------------------------------------------------------------------------


class TestRunPoolImportRecordsOutcome:
    STARTED_AT = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)

    @pytest.mark.asyncio
    async def test_successful_sync_records_complete_status(self):
        user_id = uuid.uuid4()
        user = MagicMock()
        session = MagicMock()
        session.get = AsyncMock(return_value=user)
        session.execute = AsyncMock()
        session.commit = AsyncMock()

        factory = _session_factory(session)

        with (
            patch("backend.routers.users.async_session_factory", factory),
            patch(
                "backend.routers.users._force_pool_sync",
                new=AsyncMock(return_value=(user, True)),
            ),
        ):
            await _run_pool_import(user_id, self.STARTED_AT)

        stmt = session.execute.await_args.args[0]
        params = stmt.compile().params
        assert params["pool_import_status"] == "complete"
        assert self.STARTED_AT in params.values()
        assert user_id in params.values()
        session.commit.assert_awaited_once()
        factory.assert_called_once()

    @pytest.mark.asyncio
    async def test_incomplete_sync_records_failed_status(self):
        user_id = uuid.uuid4()
        user = MagicMock()
        session = MagicMock()
        session.get = AsyncMock(return_value=user)
        session.execute = AsyncMock()
        session.commit = AsyncMock()

        factory = _session_factory(session)

        with (
            patch("backend.routers.users.async_session_factory", factory),
            patch(
                "backend.routers.users._force_pool_sync",
                new=AsyncMock(return_value=(user, False)),
            ),
        ):
            await _run_pool_import(user_id, self.STARTED_AT)

        stmt = session.execute.await_args.args[0]
        params = stmt.compile().params
        assert params["pool_import_status"] == "failed"
        assert self.STARTED_AT in params.values()
        assert user_id in params.values()
        session.commit.assert_awaited_once()
        factory.assert_called_once()


# ---------------------------------------------------------------------------
# _run_pool_import — failure paths
# ---------------------------------------------------------------------------


class TestRunPoolImportFailurePaths:
    STARTED_AT = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)

    @pytest.mark.asyncio
    async def test_sync_raising_falls_back_to_recording_failed_in_second_session(
        self, caplog
    ):
        user_id = uuid.uuid4()
        user = MagicMock()

        session1 = MagicMock()
        session1.get = AsyncMock(return_value=user)
        session1.execute = AsyncMock()
        session1.commit = AsyncMock()

        session2 = MagicMock()
        session2.execute = AsyncMock()
        session2.commit = AsyncMock()

        factory = _session_factory(session1, session2)

        with (
            patch("backend.routers.users.async_session_factory", factory),
            patch(
                "backend.routers.users._force_pool_sync",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ),
            caplog.at_level(logging.ERROR, logger="backend.routers.users"),
        ):
            await _run_pool_import(user_id, self.STARTED_AT)

        stmt = session2.execute.await_args.args[0]
        params = stmt.compile().params
        assert params["pool_import_status"] == "failed"
        assert self.STARTED_AT in params.values()
        session2.commit.assert_awaited_once()
        assert "Pool import failed" in caplog.text

    @pytest.mark.asyncio
    async def test_missing_user_returns_early_without_recording(self):
        user_id = uuid.uuid4()
        session = MagicMock()
        session.get = AsyncMock(return_value=None)
        session.execute = AsyncMock()
        session.commit = AsyncMock()

        factory = _session_factory(session)

        with (
            patch("backend.routers.users.async_session_factory", factory),
            patch(
                "backend.routers.users._force_pool_sync",
                new=AsyncMock(),
            ) as mock_force_sync,
        ):
            await _run_pool_import(user_id, self.STARTED_AT)

        mock_force_sync.assert_not_awaited()
        session.execute.assert_not_awaited()
        factory.assert_called_once()

    @pytest.mark.asyncio
    async def test_both_sessions_failing_logs_without_raising(self, caplog):
        user_id = uuid.uuid4()
        user = MagicMock()

        session1 = MagicMock()
        session1.get = AsyncMock(return_value=user)
        session1.execute = AsyncMock()
        session1.commit = AsyncMock()

        session2 = MagicMock()
        session2.execute = AsyncMock(side_effect=RuntimeError("db down"))
        session2.commit = AsyncMock()

        factory = _session_factory(session1, session2)

        with (
            patch("backend.routers.users.async_session_factory", factory),
            patch(
                "backend.routers.users._force_pool_sync",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ),
            caplog.at_level(logging.ERROR, logger="backend.routers.users"),
        ):
            await _run_pool_import(user_id, self.STARTED_AT)

        assert "Could not mark pool import failed" in caplog.text


# ---------------------------------------------------------------------------
# _effective_pool_import_status — staleness and naive datetimes
# ---------------------------------------------------------------------------


class TestEffectivePoolImportStatusNaiveDatetimes:
    """Covers the naive-started_at and None-started_at-while-importing
    branches that test_users_router.py's TestEffectivePoolImportStatus does
    not exercise (it only uses aware started_at values)."""

    @pytest.mark.parametrize(
        "started_ago, aware, expected",
        [
            (None, True, "failed"),
            (timedelta(minutes=1), False, "importing"),
            (timedelta(minutes=25), False, "failed"),
            (timedelta(minutes=19), True, "importing"),
            (timedelta(minutes=21), True, "failed"),
        ],
    )
    def test_importing_status_with_various_started_at(
        self, started_ago, aware, expected
    ):
        if started_ago is None:
            started_at = None
        else:
            now = datetime.now(timezone.utc)
            if not aware:
                now = now.replace(tzinfo=None)
            started_at = now - started_ago

        user = types.SimpleNamespace(
            pool_import_status="importing",
            pool_import_started_at=started_at,
        )

        assert _effective_pool_import_status(user) == expected
