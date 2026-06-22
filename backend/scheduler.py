"""APScheduler configuration — daily data retention purge jobs."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from backend.config import get_settings
from backend.db import async_session_factory
from backend.services.retention import (
    purge_expired_screenshots,
    purge_old_duels,
    purge_old_swipe_results,
)

logger = logging.getLogger(__name__)


async def _run_retention_purge() -> None:
    """Run all three retention purge jobs within a single DB session."""
    async with async_session_factory() as session:
        try:
            duels = await purge_old_duels(session)
            swipes = await purge_old_swipe_results(session)
            screenshots = await purge_expired_screenshots(session)
            await session.commit()
            logger.info(
                "scheduled_retention_purge duels=%d swipes=%d screenshots=%d",
                duels, swipes, screenshots,
            )
        except Exception:
            await session.rollback()
            logger.exception("scheduled_retention_purge failed")
            raise


def build_scheduler() -> AsyncIOScheduler:
    """Create and configure the retention scheduler (does not start it)."""
    settings = get_settings()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _run_retention_purge,
        trigger="cron",
        hour=settings.PURGE_SCHEDULE_HOUR,
        minute=0,
        id="retention_purge",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    return scheduler
