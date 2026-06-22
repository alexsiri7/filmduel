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
    """Run all three retention purge jobs, each in its own DB session.

    Each purge operation commits independently so that a failure in one
    does not roll back successful deletions from another.
    """
    results: dict[str, int] = {}
    for name, fn in [
        ("duels", purge_old_duels),
        ("swipes", purge_old_swipe_results),
        ("screenshots", purge_expired_screenshots),
    ]:
        async with async_session_factory() as session:
            try:
                results[name] = await fn(session)
                await session.commit()
            except Exception:
                await session.rollback()
                logger.exception("scheduled_retention_purge failed name=%s", name)
    logger.info(
        "scheduled_retention_purge duels=%d swipes=%d screenshots=%d",
        results.get("duels", -1),
        results.get("swipes", -1),
        results.get("screenshots", -1),
    )


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
        misfire_grace_time=3600,  # run the job if missed by up to 1 h (e.g. after restart)
    )
    return scheduler
