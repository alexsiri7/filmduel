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
        if screenshot.content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(
                status_code=415,
                detail="Screenshot must be an image (JPEG, PNG, GIF, or WebP)",
            )
        raw = await screenshot.read(MAX_SCREENSHOT_BYTES + 1)
        if len(raw) > MAX_SCREENSHOT_BYTES:
            raise HTTPException(
                status_code=413, detail="Screenshot too large (max 5 MB)"
            )
        mime = screenshot.content_type
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
