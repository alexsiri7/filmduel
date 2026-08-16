"""Data retention service — purge functions enforcing GDPR Art. 5(1)(e) limits."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.db_models import Duel, FeedbackReport, SwipeResult

logger = logging.getLogger(__name__)


async def _purge_by_age(
    db: AsyncSession, model: Any, cutoff: datetime, log_name: str, retention_days: int
) -> int:
    """Delete rows from ``model`` with created_at older than ``cutoff``. Returns row count."""
    result = await db.execute(
        delete(model).where(model.created_at < cutoff).returning(model.id)
    )
    count = len(result.fetchall())
    logger.info("purged_%s count=%d retention_days=%d", log_name, count, retention_days)
    return count


async def purge_old_duels(db: AsyncSession) -> int:
    """Delete duels older than DUEL_RETENTION_DAYS. Does not commit; caller must commit.

    Returns:
        Number of rows deleted.
    """
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.DUEL_RETENTION_DAYS)
    return await _purge_by_age(db, Duel, cutoff, "duels", settings.DUEL_RETENTION_DAYS)


async def purge_old_swipe_results(db: AsyncSession) -> int:
    """Delete swipe results older than SWIPE_RETENTION_DAYS. Does not commit; caller must commit.

    Returns:
        Number of rows deleted.
    """
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.SWIPE_RETENTION_DAYS)
    return await _purge_by_age(db, SwipeResult, cutoff, "swipe_results", settings.SWIPE_RETENTION_DAYS)


async def purge_expired_screenshots(db: AsyncSession) -> int:
    """Null out screenshot_data_enc for FeedbackReports past their purge_after date.
    Does not commit; caller must commit.

    Returns:
        Number of rows updated.
    """
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(FeedbackReport)
        .where(FeedbackReport.purge_after <= now)
        .where(FeedbackReport.screenshot_data_enc.isnot(None))
        .values(screenshot_data_enc=None)
        .returning(FeedbackReport.id)
    )
    count = len(result.fetchall())
    logger.info("purged_screenshots count=%d", count)
    return count
