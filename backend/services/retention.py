"""Data retention service — purge functions enforcing GDPR Art. 5(1)(e) limits."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.db_models import (
    Duel,
    DuelHistory,
    FeedbackReport,
    Suggestion,
    SwipeResult,
    Tournament,
    User,
)
from backend.services.simkl import SimklClient
from backend.services.token_crypto import decrypt_token
from backend.services.trakt import TraktClient

logger = logging.getLogger(__name__)

_DUEL_HISTORY_COLUMNS = tuple(
    c.name for c in DuelHistory.__table__.columns if c.name != "id"
)


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
    """Move duels older than DUEL_RETENTION_DAYS into duel_history.

    Only the minimal columns are kept; the full row (Elo snapshots, mode,
    pair_type) is deleted. Delete and insert run as one statement, so
    concurrent purges cannot copy the same duel twice.
    Does not commit; caller must commit.

    Returns:
        Number of rows moved.
    """
    retention_days = get_settings().DUEL_RETENTION_DAYS
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    moved = (
        delete(Duel)
        .where(Duel.created_at < cutoff)
        .returning(*(getattr(Duel, c) for c in _DUEL_HISTORY_COLUMNS))
        .cte("moved_duels")
    )
    result = await db.execute(
        insert(DuelHistory)
        .from_select(
            _DUEL_HISTORY_COLUMNS, select(*(moved.c[c] for c in _DUEL_HISTORY_COLUMNS))
        )
        .returning(DuelHistory.id)
    )
    count = len(result.fetchall())
    logger.info("purged_duels count=%d retention_days=%d", count, retention_days)
    return count


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


async def purge_unconsented_users(db: AsyncSession) -> int:
    """Delete users who never accepted the privacy policy and signed in more
    than UNCONSENTED_USER_RETENTION_DAYS ago, then best-effort revoke their
    provider access tokens upstream.

    Only tokens of rows the DELETE actually removed are revoked, so a user who
    consents while the purge runs keeps a working token.
    Does not commit; caller must commit.

    Returns:
        Number of rows deleted.
    """
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(
        days=settings.UNCONSENTED_USER_RETENTION_DAYS
    )
    result = await db.execute(
        delete(User)
        .where(User.privacy_policy_accepted.is_(False))
        .where(User.created_at < cutoff)
        .returning(User.trakt_access_token_enc, User.simkl_access_token_enc)
    )
    rows = result.fetchall()
    trakt = TraktClient(client_id=settings.TRAKT_CLIENT_ID)
    simkl = SimklClient(client_id=settings.SIMKL_CLIENT_ID)
    for trakt_enc, simkl_enc in rows:
        for client, token_enc, client_secret in (
            (trakt, trakt_enc, settings.TRAKT_CLIENT_SECRET),
            (simkl, simkl_enc, settings.SIMKL_CLIENT_SECRET),
        ):
            if not token_enc:
                continue
            try:
                await client.revoke_token(
                    decrypt_token(token_enc), client_secret=client_secret
                )
            except Exception:
                logger.warning("unconsented_user_token_revoke failed", exc_info=True)
    count = len(rows)
    logger.info(
        "purged_unconsented_users count=%d retention_days=%d",
        count,
        settings.UNCONSENTED_USER_RETENTION_DAYS,
    )
    return count
