"""Unit tests for backend/services/retention.py"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.retention import (
    purge_expired_screenshots,
    purge_old_duels,
    purge_old_swipe_results,
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
