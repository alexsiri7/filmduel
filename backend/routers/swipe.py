"""Swipe session routes — classify films as seen/unseen."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import acquire_quota_lock, get_db
from backend.db_models import SwipeResult, User
from backend.rate_limit import limiter
from backend.routers.auth import get_admin_user, require_consent
from backend.schemas import MediaType, SwipeCardSchema, SwipeResponse, SwipeSubmit
from backend.services.duel import compute_next_action
from backend.services.expand import expand_pool
from backend.services.retention import (
    purge_old_swipe_results as _purge_old_swipe_results,
)
from backend.services.swipe import (
    pool_needs_expansion,
    record_swipes,
    select_swipe_cards,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/swipe", tags=["swipe"])

# Per-user daily cap on swipe_results rows (SEC-21, #589). A session is at most
# 10 cards, so this allows ~200 sessions/day while bounding 180-day retention growth.
MAX_SWIPES_PER_DAY = 2000


@router.get("/cards", response_model=list[SwipeCardSchema])
@limiter.limit("20/minute")
async def get_swipe_cards(
    request: Request,
    current_user: User = Depends(require_consent),
    db: AsyncSession = Depends(get_db),
    media_type: MediaType = Query(default="movie"),
):
    """Return up to 10 unknown films for a swipe session, weighted by community rating band."""
    uid = current_user.id
    logger.info("swipe_cards_requested user_id=%s", uid)

    rows = await select_swipe_cards(db, uid, media_type)
    logger.info("swipe_cards_result user_id=%s cards_returned=%d", uid, len(rows))

    if not rows:
        logger.warning("swipe_cards_empty user_id=%s no_unknown_films_available", uid)
        raise HTTPException(
            status_code=404,
            detail="No unknown films available. Import more movies from Trakt.",
        )

    return [
        SwipeCardSchema(
            id=str(r.id),
            trakt_id=r.trakt_id,
            title=r.title,
            year=r.year,
            genres=r.genres or [],
            poster_url=r.poster_url,
            community_rating=float(r.community_rating) if r.community_rating else None,
        )
        for r in rows
    ]


@router.post("/results", response_model=SwipeResponse)
@limiter.limit("20/minute")
async def submit_swipe_results(
    request: Request,
    body: SwipeSubmit,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_consent),
    db: AsyncSession = Depends(get_db),
    media_type: MediaType = Query(default="movie"),
):
    """Submit all swipe results at once — bulk update seen status."""
    uid = current_user.id
    now = datetime.now(timezone.utc)

    # Serialize the cap check per user (SEC-02, #570); held until get_db commits.
    await acquire_quota_lock(db, "swipe_daily_cap", uid)

    # Per-user daily cap on swipe_results rows: prevents database bloat (SEC-21, #589).
    window_start = now - timedelta(hours=24)
    count_stmt = select(func.count()).where(
        SwipeResult.user_id == uid,
        SwipeResult.created_at >= window_start,
    )
    daily_count = (await db.execute(count_stmt)).scalar_one()
    if daily_count >= MAX_SWIPES_PER_DAY:
        logger.warning("swipe_daily_cap_hit user_id=%s count=%d", uid, daily_count)
        raise HTTPException(
            status_code=429,
            detail=f"Daily swipe limit reached ({MAX_SWIPES_PER_DAY} per 24 hours). Please try again later.",
        )

    tally = await record_swipes(db, uid, body.results)
    next_action = await compute_next_action(db, uid, media_type)

    logger.debug(
        "swipe_submit user_id=%s seen_count=%d unseen_count=%d next_action=%s",
        uid,
        tally.seen,
        tally.unseen,
        next_action,
    )
    if tally.skipped:
        logger.debug("swipe_submit_skipped user_id=%s skipped=%d", uid, tally.skipped)

    if await pool_needs_expansion(db, uid, media_type):
        background_tasks.add_task(expand_pool, uid, media_type)

    return SwipeResponse(
        seen_count=tally.seen, unseen_count=tally.unseen, next_action=next_action
    )


@router.delete("/admin/purge-old-records", status_code=200)
@limiter.limit("10/minute")
async def purge_old_swipe_results(
    request: Request,
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    count = await _purge_old_swipe_results(db)
    logger.info("purge_old_swipe_results count=%d triggered_by=%s", count, current_user.id)
    return {"purged": count}
