"""Shared feedback-report helpers used by the feedback and users routers."""

from __future__ import annotations

import logging
from datetime import timedelta

from backend.services.token_crypto import TokenPurpose, decrypt_token

logger = logging.getLogger(__name__)

FEEDBACK_CAP_WINDOW = timedelta(hours=24)


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
