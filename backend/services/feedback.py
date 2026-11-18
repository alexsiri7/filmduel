"""Feedback-report rules shared by the feedback and users routers: the per-user
daily cap and screenshot decryption."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db_models import FeedbackReport
from backend.services.quota import DailyQuota
from backend.services.token_crypto import TokenPurpose, decrypt_token

logger = logging.getLogger(__name__)

FEEDBACK_CAP_WINDOW = timedelta(hours=24)
MAX_FEEDBACK_PER_DAY = 20


async def _count_reports_since(
    db: AsyncSession, user_id: uuid.UUID, cutoff: datetime
) -> int:
    # `or 0`: some drivers return NULL for an empty count.
    return (
        await db.scalar(
            select(func.count()).where(
                FeedbackReport.user_id == user_id,
                FeedbackReport.created_at >= cutoff,
            )
        )
    ) or 0


FEEDBACK_DAILY_QUOTA = DailyQuota(
    name="feedback_daily_cap",
    limit=MAX_FEEDBACK_PER_DAY,
    window=FEEDBACK_CAP_WINDOW,
    count_since=_count_reports_since,
    message=f"Feedback limit reached. You may submit up to {MAX_FEEDBACK_PER_DAY} reports per day.",
)


def safe_decrypt_screenshot(report_id: str, ciphertext: str | None) -> str | None:
    """Decrypt screenshot ciphertext, returning None and logging on failure.

    A corrupted or key-mismatched record is reported as missing rather than as a 500.
    """
    if not ciphertext:
        return None
    try:
        return decrypt_token(ciphertext, purpose=TokenPurpose.SCREENSHOT)
    except RuntimeError:
        logger.error(
            "screenshot_decrypt_failed report_id=%s — returning null screenshot",
            report_id,
        )
        return None
