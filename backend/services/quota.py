"""Per-user rolling daily quotas on created rows (SEC-02, SEC-03, SEC-21).

Each domain declares a DailyQuota next to the rows it counts; routers enforce
it with one enforce_daily_quota call, and backend.main maps QuotaExceeded to 429.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import acquire_quota_lock, acquire_quota_lock_nowait

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DailyQuota:
    name: str  # advisory-lock scope and log-event prefix
    limit: int
    count_since: Callable[[AsyncSession, uuid.UUID, datetime], Awaitable[int]]
    message: str  # 429 detail; built from the limit constant
    window: timedelta = timedelta(hours=24)


class QuotaExceeded(Exception):
    def __init__(self, quota: DailyQuota) -> None:
        super().__init__(quota.message)
        self.quota = quota


async def enforce_daily_quota(
    db: AsyncSession, quota: DailyQuota, user_id: uuid.UUID, *, nowait: bool
) -> None:
    """Raise QuotaExceeded if the user already has quota.limit rows in the window.

    The count is serialized per user with a transaction-scoped advisory lock held
    until get_db commits, so parallel requests cannot all read the same count and
    bypass the cap (SEC-02, #570). Handlers that go on to await an LLM call pass
    nowait=True: a queued waiter would hold a pooled connection through the
    leader's call, so a concurrent request is refused with 429 instead (AUD-01).
    """
    if nowait:
        await acquire_quota_lock_nowait(db, quota.name, user_id)
    else:
        await acquire_quota_lock(db, quota.name, user_id)

    cutoff = datetime.now(timezone.utc) - quota.window
    count = await quota.count_since(db, user_id, cutoff)
    if count >= quota.limit:
        logger.warning("%s_hit user_id=%s count=%d", quota.name, user_id, count)
        raise QuotaExceeded(quota)
