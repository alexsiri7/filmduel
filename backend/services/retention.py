"""Data retention service — purge functions enforcing GDPR Art. 5(1)(e) limits."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, exists, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.db_models import (
    Base,
    Duel,
    DuelHistory,
    FeedbackReport,
    Suggestion,
    SwipeResult,
    Tournament,
    User,
)
from backend.services.simkl import SimklClient
from backend.services.token_crypto import TokenDecryptError, TokenPurpose, decrypt_token
from backend.services.trakt import TraktClient

logger = logging.getLogger(__name__)

_DUEL_HISTORY_COLUMNS = tuple(
    c.name for c in DuelHistory.__table__.columns if c.name != "id"
)

# Every column holding a users.id, so a table added later is protected from
# purge_unconsented_accounts without anyone remembering to list it.
_USER_REFERENCES = tuple(
    fk.parent
    for table in Base.metadata.sorted_tables
    for fk in table.foreign_keys
    if fk.column is User.__table__.c.id
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


def _plain_token(ciphertext: str | None, user_id) -> str | None:
    """Decrypt a stored provider token; None when absent or no key decrypts it."""
    if not ciphertext:
        return None
    try:
        return decrypt_token(ciphertext, purpose=TokenPurpose.OAUTH)
    except TokenDecryptError:
        logger.warning("purge_token_undecryptable user_id=%s", user_id)
        return None


async def _revoke_provider_tokens(row) -> None:
    """Best-effort upstream revocation of a row's Trakt and SIMKL access tokens.

    ``row`` carries ``id``, ``trakt_access_token_enc`` and ``simkl_access_token_enc``.
    """
    settings = get_settings()
    trakt_token = _plain_token(row.trakt_access_token_enc, row.id)
    if trakt_token:
        await TraktClient(client_id=settings.TRAKT_CLIENT_ID).revoke_token(
            trakt_token, client_secret=settings.TRAKT_CLIENT_SECRET
        )
    simkl_token = _plain_token(row.simkl_access_token_enc, row.id)
    if simkl_token:
        await SimklClient(client_id=settings.SIMKL_CLIENT_ID).revoke_token(
            simkl_token, client_secret=settings.SIMKL_CLIENT_SECRET
        )


async def purge_unconsented_accounts(db: AsyncSession) -> int:
    """Delete accounts that never consented, hold no data and have not signed in
    for UNCONSENTED_ACCOUNT_RETENTION_DAYS, revoking their provider tokens upstream.

    A withdrawn user looks never-consented on the consent columns, but keeps a
    pool_import_status from their first consent; a legacy pre-consent-gate
    account keeps rows in some table referencing users.id. Both are kept.
    Does not commit; caller must commit.

    Returns:
        Number of accounts deleted.
    """
    retention_days = get_settings().UNCONSENTED_ACCOUNT_RETENTION_DAYS
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    result = await db.execute(
        delete(User)
        .where(
            User.privacy_policy_accepted.is_(False),
            User.privacy_policy_accepted_at.is_(None),
            User.privacy_policy_version.is_(None),
            User.pool_import_status.is_(None),
            User.is_admin.is_(False),
            User.created_at < cutoff,
            User.last_seen_at < cutoff,
            *(~exists().where(column == User.id) for column in _USER_REFERENCES),
        )
        .returning(User.id, User.trakt_access_token_enc, User.simkl_access_token_enc)
    )
    rows = result.fetchall()
    for row in rows:
        await _revoke_provider_tokens(row)
    logger.info(
        "purged_unconsented_accounts count=%d retention_days=%d", len(rows), retention_days
    )
    return len(rows)


async def purge_dormant_provider_tokens(db: AsyncSession) -> int:
    """Revoke upstream and clear the provider tokens of accounts with no sign-in
    for DORMANT_TOKEN_RETENTION_DAYS. The account and its data are kept; signing
    in again stores fresh tokens.

    Skips pre-#684 rows not yet adopted (no trakt_uuid, slug still held): their
    stored Trakt token is the only proof of ownership the next sign-in can use.
    Does not commit; caller must commit.

    Returns:
        Number of accounts whose tokens were cleared.
    """
    retention_days = get_settings().DORMANT_TOKEN_RETENTION_DAYS
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    result = await db.execute(
        select(User.id, User.trakt_access_token_enc, User.simkl_access_token_enc)
        .where(
            User.last_seen_at < cutoff,
            or_(
                User.trakt_access_token_enc.isnot(None),
                User.trakt_refresh_token_enc.isnot(None),
                User.simkl_access_token_enc.isnot(None),
                User.simkl_refresh_token_enc.isnot(None),
            ),
            or_(User.trakt_uuid.isnot(None), User.trakt_user_id.is_(None)),
        )
        .with_for_update()
    )
    rows = result.fetchall()
    if rows:
        await db.execute(
            update(User)
            .where(User.id.in_([row.id for row in rows]))
            .values(
                trakt_access_token_enc=None,
                trakt_refresh_token_enc=None,
                trakt_token_expires_at=None,
                simkl_access_token_enc=None,
                simkl_refresh_token_enc=None,
                simkl_token_expires_at=None,
            )
        )
        for row in rows:
            await _revoke_provider_tokens(row)
    logger.info(
        "purged_dormant_provider_tokens count=%d retention_days=%d", len(rows), retention_days
    )
    return len(rows)
