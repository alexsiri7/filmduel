"""Feedback report routes."""

from __future__ import annotations

import base64
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from backend.db import get_db
from backend.db_models import FeedbackReport, User
from backend.rate_limit import limiter
from backend.routers.auth import get_current_user
from backend.schemas import FeedbackAdminResponse, FeedbackReportResponse
from backend.services.token_crypto import decrypt_token, encrypt_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/feedback", tags=["feedback"])


def _safe_decrypt(report_id: str, ciphertext: str | None) -> str | None:
    """Decrypt screenshot ciphertext, returning None and logging on failure.

    Prevents one corrupted or key-mismatched record from crashing the full admin listing.
    """
    if not ciphertext:
        return None
    try:
        return decrypt_token(ciphertext)
    except RuntimeError:
        logger.error(
            "screenshot_decrypt_failed report_id=%s — returning null screenshot",
            report_id,
        )
        return None


MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_FEEDBACK_PER_DAY = 20  # per-user daily cap

# Magic bytes for allowed image types
_IMAGE_SIGNATURES = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
    b"RIFF": "image/webp",  # WebP starts with RIFF....WEBP
}


def _detect_image_type(data: bytes) -> str | None:
    """Detect image type from magic bytes. Returns MIME type or None."""
    for sig, mime in _IMAGE_SIGNATURES.items():
        if data[: len(sig)] == sig:
            if mime == "image/webp" and data[8:12] != b"WEBP":
                continue
            return mime
    return None


@router.post("", response_model=FeedbackReportResponse, status_code=201)
@limiter.limit("5/hour")
async def submit_feedback(
    request: Request,
    title: str = Form(...),
    description: str = Form(...),
    screenshot: UploadFile = File(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    daily_count: int = (
        await db.scalar(
            select(func.count()).where(
                FeedbackReport.user_id == current_user.id,
                FeedbackReport.created_at >= cutoff,
            )
        )
    ) or 0
    if daily_count >= MAX_FEEDBACK_PER_DAY:
        raise HTTPException(
            status_code=429,
            detail="Feedback limit reached. You may submit up to 20 reports per day.",
        )

    screenshot_data_enc = None
    if screenshot and screenshot.filename:
        raw = await screenshot.read(MAX_SCREENSHOT_BYTES + 1)
        if len(raw) > MAX_SCREENSHOT_BYTES:
            raise HTTPException(
                status_code=413, detail="Screenshot too large (max 5 MB)"
            )
        mime = _detect_image_type(raw)
        if not mime:
            raise HTTPException(
                status_code=415,
                detail="Screenshot must be a valid image (JPEG, PNG, GIF, or WebP)",
            )
        plain = f"data:{mime};base64," + base64.b64encode(raw).decode()
        try:
            screenshot_data_enc = encrypt_token(plain)
        except RuntimeError:
            logger.error(
                "screenshot_encrypt_failed user_id=%s — TOKEN_ENC_KEY misconfigured?",
                current_user.id,
            )
            raise HTTPException(
                status_code=503,
                detail="Screenshot could not be stored securely. Please try again later.",
            )

    purge_after = (
        datetime.now(timezone.utc) + timedelta(days=90)
        if screenshot_data_enc is not None
        else None
    )
    report = FeedbackReport(
        user_id=current_user.id,
        title=title.strip(),
        description=description.strip(),
        screenshot_data_enc=screenshot_data_enc,
        purge_after=purge_after,
    )
    db.add(report)
    await db.flush()

    logger.info("feedback_submitted user_id=%s title=%r", current_user.id, title[:50])

    return FeedbackReportResponse(id=str(report.id), created_at=report.created_at)


@router.get("/admin", response_model=list[FeedbackAdminResponse])
async def list_feedback(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # TODO: replace with proper role check when admin roles are implemented
    result = await db.execute(
        select(FeedbackReport).order_by(FeedbackReport.created_at.desc()).limit(100)
    )
    reports = result.scalars().all()
    return [
        FeedbackAdminResponse(
            id=str(r.id),
            user_id=str(r.user_id),
            title=r.title,
            description=r.description,
            screenshot_data=_safe_decrypt(str(r.id), r.screenshot_data_enc),
            created_at=r.created_at,
            purge_after=r.purge_after,
        )
        for r in reports
    ]


@router.delete("/admin/{report_id}/screenshot", status_code=204)
async def scrub_screenshot(
    report_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # TODO: replace with proper role check when admin roles are implemented
    result = await db.execute(
        select(FeedbackReport).where(FeedbackReport.id == report_id)
    )
    report = result.scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    report.screenshot_data_enc = None
    await db.flush()
    logger.info(
        "screenshot_scrubbed report_id=%s by user_id=%s",
        report_id,
        current_user.id,
    )


@router.delete("/admin/purge-expired-screenshots", status_code=200)
async def purge_expired_screenshots(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # TODO: replace with proper role check when admin roles are implemented
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(FeedbackReport)
        .where(FeedbackReport.purge_after <= now)
        .where(FeedbackReport.screenshot_data_enc.isnot(None))
        .values(screenshot_data_enc=None)
        .returning(FeedbackReport.id)
    )
    purged_ids = result.fetchall()
    logger.info("purged_screenshots count=%d", len(purged_ids))
    return {"purged": len(purged_ids)}
