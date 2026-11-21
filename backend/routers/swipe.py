"""Swipe session routes — classify films as seen/unseen."""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import get_db
from backend.db_models import User
from backend.rate_limit import limiter
from backend.routers.auth import get_admin_user, require_consent
from backend.schemas import MediaType, SwipeCardSchema, SwipeResponse, SwipeSubmit
from backend.services.duel import compute_next_action
from backend.services.expand import expand_pool
from backend.services.quota import enforce_daily_quota
from backend.services.retention import (
    purge_old_swipe_results as _purge_old_swipe_results,
)
from backend.services.swipe import (
    SWIPE_DAILY_QUOTA,
    pool_needs_expansion,
    record_swipes,
    select_swipe_cards,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/swipe", tags=["swipe"])

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

    # A title listed twice is written once, so it counts once against the cap.
    titles = len({item.movie_id for item in body.results})
    await enforce_daily_quota(db, SWIPE_DAILY_QUOTA, uid, nowait=False, adding=titles)

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
