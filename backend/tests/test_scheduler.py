"""Unit tests for backend/scheduler.py"""

from __future__ import annotations

import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests!!")

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.scheduler import _run_retention_purge, build_scheduler


def _make_mock_ctx() -> tuple[AsyncMock, MagicMock]:
    """Return (mock_session, mock_ctx) suitable for patching async_session_factory."""
    mock_session = AsyncMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_session, mock_ctx


class TestBuildScheduler:
    def test_scheduler_has_one_job(self):
        scheduler = build_scheduler()
        jobs = scheduler.get_jobs()
        assert len(jobs) == 1

    def test_job_id_is_retention_purge(self):
        scheduler = build_scheduler()
        job = scheduler.get_jobs()[0]
        assert job.id == "retention_purge"

    def test_job_trigger_is_cron(self):
        scheduler = build_scheduler()
        job = scheduler.get_jobs()[0]
        assert job.trigger.__class__.__name__ == "CronTrigger"

    def test_job_hour_matches_config_default(self):
        scheduler = build_scheduler()
        job = scheduler.get_jobs()[0]
        hour_field = next(f for f in job.trigger.fields if f.name == "hour")
        assert str(hour_field) == "2"


class TestRunRetentionPurge:
    @pytest.mark.asyncio
    async def test_commits_on_success(self):
        """Happy path: all three purge functions succeed; each session is committed."""
        sessions = []

        def make_ctx():
            session, ctx = _make_mock_ctx()
            sessions.append(session)
            return ctx

        with patch("backend.scheduler.async_session_factory", side_effect=make_ctx), \
             patch("backend.scheduler.purge_old_duels", return_value=3) as mock_duels, \
             patch("backend.scheduler.purge_old_swipe_results", return_value=1) as mock_swipes, \
             patch("backend.scheduler.purge_expired_screenshots", return_value=0) as mock_ss:
            await _run_retention_purge()

        assert mock_duels.await_count == 1
        assert mock_swipes.await_count == 1
        assert mock_ss.await_count == 1
        for session in sessions:
            session.commit.assert_awaited_once()
            session.rollback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rolls_back_on_exception_and_continues(self):
        """If one purge fails, that session rolls back but the others still run."""
        sessions = []

        def make_ctx():
            session, ctx = _make_mock_ctx()
            sessions.append(session)
            return ctx

        with patch("backend.scheduler.async_session_factory", side_effect=make_ctx), \
             patch("backend.scheduler.purge_old_duels", side_effect=RuntimeError("db error")), \
             patch("backend.scheduler.purge_old_swipe_results", return_value=1), \
             patch("backend.scheduler.purge_expired_screenshots", return_value=0):
            # Should NOT raise — per-session errors are logged and swallowed
            await _run_retention_purge()

        # First session (duels) rolled back, not committed
        sessions[0].rollback.assert_awaited_once()
        sessions[0].commit.assert_not_awaited()
        # Remaining sessions (swipes, screenshots) committed normally
        sessions[1].commit.assert_awaited_once()
        sessions[1].rollback.assert_not_awaited()
        sessions[2].commit.assert_awaited_once()
        sessions[2].rollback.assert_not_awaited()
