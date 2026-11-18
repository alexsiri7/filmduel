"""Tests for backend.services.quota."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests!!")

import pytest

from backend.services.quota import DailyQuota, QuotaExceeded, enforce_daily_quota

LIMIT = 5


def _quota(count: int) -> DailyQuota:
    return DailyQuota(
        name="test_daily_cap",
        limit=LIMIT,
        count_since=AsyncMock(return_value=count),
        message=f"Up to {LIMIT} per day.",
    )


@pytest.mark.asyncio
async def test_under_limit_takes_blocking_lock_then_counts_the_window():
    db = AsyncMock()
    user_id = uuid.uuid4()
    quota = _quota(LIMIT - 1)

    with (
        patch("backend.services.quota.acquire_quota_lock", new_callable=AsyncMock) as lock,
        patch("backend.services.quota.acquire_quota_lock_nowait", new_callable=AsyncMock) as nowait_lock,
    ):
        await enforce_daily_quota(db, quota, user_id, nowait=False)

    lock.assert_awaited_once_with(db, "test_daily_cap", user_id)
    nowait_lock.assert_not_awaited()
    quota.count_since.assert_awaited_once()
    count_db, count_user, cutoff = quota.count_since.await_args.args
    assert (count_db, count_user) == (db, user_id)
    expected = datetime.now(timezone.utc) - timedelta(hours=24)
    assert abs(cutoff - expected) < timedelta(seconds=5)


@pytest.mark.asyncio
async def test_at_limit_raises_with_the_quota_message():
    db = AsyncMock()
    user_id = uuid.uuid4()
    quota = _quota(LIMIT)

    with (
        patch("backend.services.quota.acquire_quota_lock", new_callable=AsyncMock) as lock,
        patch("backend.services.quota.acquire_quota_lock_nowait", new_callable=AsyncMock) as nowait_lock,
    ):
        with pytest.raises(QuotaExceeded) as excinfo:
            await enforce_daily_quota(db, quota, user_id, nowait=True)

    nowait_lock.assert_awaited_once_with(db, "test_daily_cap", user_id)
    lock.assert_not_awaited()
    assert excinfo.value.quota is quota
    assert str(excinfo.value) == quota.message
