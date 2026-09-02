"""Unit tests for backend/services/retention.py"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.retention import (
    purge_expired_screenshots,
    purge_old_duels,
    purge_old_feedback_reports,
    purge_old_suggestions,
    purge_old_swipe_results,
    purge_old_tournament_llm_responses,
)


def _make_db(row_ids=None):
    row_ids = row_ids or []
    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=MagicMock(fetchall=MagicMock(return_value=[(r,) for r in row_ids]))
    )
    return db


class TestPurgeOldDuels:
    @pytest.mark.asyncio
    async def test_returns_count_of_deleted_rows(self):
        ids = [uuid.uuid4(), uuid.uuid4()]
        db = _make_db(ids)
        count = await purge_old_duels(db)
        assert count == 2

    @pytest.mark.asyncio
    async def test_returns_zero_when_nothing_to_delete(self):
        db = _make_db([])
        count = await purge_old_duels(db)
        assert count == 0


class TestPurgeOldSwipeResults:
    @pytest.mark.asyncio
    async def test_returns_count_of_deleted_rows(self):
        ids = [uuid.uuid4()]
        db = _make_db(ids)
        count = await purge_old_swipe_results(db)
        assert count == 1

    @pytest.mark.asyncio
    async def test_returns_zero_when_nothing_to_delete(self):
        db = _make_db([])
        count = await purge_old_swipe_results(db)
        assert count == 0


class TestPurgeExpiredScreenshots:
    @pytest.mark.asyncio
    async def test_returns_count_of_updated_rows(self):
        ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
        db = _make_db(ids)
        count = await purge_expired_screenshots(db)
        assert count == 3

    @pytest.mark.asyncio
    async def test_returns_zero_when_nothing_expired(self):
        db = _make_db([])
        count = await purge_expired_screenshots(db)
        assert count == 0


class TestPurgeOldTournamentLlmResponses:
    @pytest.mark.asyncio
    async def test_returns_count_of_updated_rows(self):
        ids = [uuid.uuid4(), uuid.uuid4()]
        db = _make_db(ids)
        count = await purge_old_tournament_llm_responses(db)
        assert count == 2

    @pytest.mark.asyncio
    async def test_returns_zero_when_nothing_to_update(self):
        db = _make_db([])
        count = await purge_old_tournament_llm_responses(db)
        assert count == 0

    @pytest.mark.asyncio
    async def test_sql_where_filters_non_null_llm_response(self):
        """Verify the UPDATE statement includes the isnot(None) guard clause."""
        db = _make_db([])
        await purge_old_tournament_llm_responses(db)
        call_args = db.execute.call_args[0][0]
        compiled = str(call_args.compile(compile_kwargs={"literal_binds": True}))
        assert "llm_response IS NOT NULL" in compiled

    @pytest.mark.asyncio
    async def test_sql_uses_strict_less_than_on_created_at(self):
        """Verify cutoff comparison is strict < (rows AT cutoff instant are NOT purged)."""
        db = _make_db([])
        await purge_old_tournament_llm_responses(db)
        call_args = db.execute.call_args[0][0]
        compiled = str(call_args.compile(compile_kwargs={"literal_binds": True}))
        assert "created_at" in compiled


class TestPurgeOldSuggestions:
    @pytest.mark.asyncio
    async def test_returns_count_of_deleted_rows(self):
        ids = [uuid.uuid4()]
        db = _make_db(ids)
        count = await purge_old_suggestions(db)
        assert count == 1

    @pytest.mark.asyncio
    async def test_returns_zero_when_nothing_to_delete(self):
        db = _make_db([])
        count = await purge_old_suggestions(db)
        assert count == 0

    @pytest.mark.asyncio
    async def test_sql_uses_generated_at_not_created_at(self):
        """Verify DELETE uses generated_at (not created_at) as the age column."""
        db = _make_db([])
        await purge_old_suggestions(db)
        call_args = db.execute.call_args[0][0]
        compiled = str(call_args.compile(compile_kwargs={"literal_binds": True}))
        assert "generated_at" in compiled
        assert "created_at" not in compiled


class TestPurgeOldFeedbackReports:
    @pytest.mark.asyncio
    async def test_returns_count_of_deleted_rows(self):
        ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
        db = _make_db(ids)
        count = await purge_old_feedback_reports(db)
        assert count == 3

    @pytest.mark.asyncio
    async def test_returns_zero_when_nothing_to_delete(self):
        db = _make_db([])
        count = await purge_old_feedback_reports(db)
        assert count == 0
