"""Data retention service — purge functions enforcing GDPR Art. 5(1)(e) limits."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.db_models import Duel, FeedbackReport, Suggestion, SwipeResult, Tournament

logger = logging.getLogger(__name__)


async def _purge_by_age(
    db: AsyncSession, model: type, retention_days: int, log_name: str
) -> int:
    """Delete rows from ``model`` with created_at older than ``retention_days``.

    Returns row count.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
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
    return await _purge_by_age(db, Duel, get_settings().DUEL_RETENTION_DAYS, "duels")


async def purge_old_swipe_results(db: AsyncSession) -> int:
    """Delete swipe results older than SWIPE_RETENTION_DAYS. Does not commit; caller must commit.

    Returns:
        Number of rows deleted.
    """
    return await _purge_by_age(
        db, SwipeResult, get_settings().SWIPE_RETENTION_DAYS, "swipe_results"
    )


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


async def purge_old_tournament_llm_responses(db: AsyncSession) -> int:
    """Null out llm_response on tournaments older than TOURNAMENT_LLM_RETENTION_DAYS.
    Preserves tournament rows for UX; removes only the LLM payload.
    Does not commit; caller must commit.

    Returns:
        Number of rows updated.
    """
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.TOURNAMENT_LLM_RETENTION_DAYS)
    result = await db.execute(
        update(Tournament)
        .where(Tournament.created_at < cutoff)
        .where(Tournament.llm_response.isnot(None))
        .values(llm_response=None)
        .returning(Tournament.id)
    )
    count = len(result.fetchall())
    logger.info(
        "purged_tournament_llm_responses count=%d retention_days=%d",
        count,
        settings.TOURNAMENT_LLM_RETENTION_DAYS,
    )
    return count


async def purge_old_suggestions(db: AsyncSession) -> int:
    """Delete suggestions older than SUGGESTION_RETENTION_DAYS. Does not commit; caller must commit.

    Inlines its own delete (rather than using ``_purge_by_age``) because
    ``Suggestion`` uses ``generated_at`` as its age column, not ``created_at``.

    Returns:
        Number of rows deleted.
    """
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.SUGGESTION_RETENTION_DAYS)
    result = await db.execute(
        delete(Suggestion).where(Suggestion.generated_at < cutoff).returning(Suggestion.id)
    )
    count = len(result.fetchall())
    logger.info(
        "purged_suggestions count=%d retention_days=%d",
        count,
        settings.SUGGESTION_RETENTION_DAYS,
    )
    return count


async def purge_old_feedback_reports(db: AsyncSession) -> int:
    """Delete feedback_reports older than FEEDBACK_RETENTION_DAYS.

    Does not commit; caller must commit.

    Returns:
        Number of rows deleted.
    """
    return await _purge_by_age(
        db, FeedbackReport, get_settings().FEEDBACK_RETENTION_DAYS, "feedback_reports"
    )
