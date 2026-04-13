"""Feedback report routes."""

from __future__ import annotations

import base64
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import get_db
from backend.db_models import FeedbackReport, User
from backend.routers.auth import get_current_user
from backend.schemas import FeedbackReportResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/feedback", tags=["feedback"])

MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

# Magic bytes for allowed image types
_IMAGE_SIGNATURES = {
    b'\x89PNG\r\n\x1a\n': "image/png",
    b'\xff\xd8\xff': "image/jpeg",
    b'GIF87a': "image/gif",
    b'GIF89a': "image/gif",
    b'RIFF': "image/webp",  # WebP starts with RIFF....WEBP
}


def _detect_image_type(data: bytes) -> str | None:
    """Detect image type from magic bytes. Returns MIME type or None."""
    for sig, mime in _IMAGE_SIGNATURES.items():
        if data[:len(sig)] == sig:
            if mime == "image/webp" and data[8:12] != b'WEBP':
                continue
            return mime
    return None


@router.post("", response_model=FeedbackReportResponse, status_code=201)
async def submit_feedback(
    title: str = Form(...),
    description: str = Form(...),
    screenshot: UploadFile = File(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    screenshot_data = None
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
        screenshot_data = f"data:{mime};base64," + base64.b64encode(raw).decode()

    report = FeedbackReport(
        user_id=current_user.id,
        title=title.strip(),
        description=description.strip(),
        screenshot_data=screenshot_data,
    )
    db.add(report)
    await db.flush()

    logger.info(
        "feedback_submitted user_id=%s title=%r", current_user.id, title[:50]
    )

    return FeedbackReportResponse(id=str(report.id), created_at=report.created_at)
