"""Swipe session routes — classify films as seen/unseen."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import get_db
from backend.db_models import Movie, SwipeResult, User, UserMovie
from backend.routers.auth import get_current_user
from backend.schemas import SwipeCardSchema, SwipeResponse, SwipeSubmit
from backend.services.expand import expand_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/swipe", tags=["swipe"])

# Quality bands: (elo_low, elo_high, community_rating_low, community_rating_high)
BANDS = [
    ("elite", 1300, 9999, 80, 100),
    ("strong", 1100, 1299, 65, 79),
    ("mid", 900, 1099, 45, 64),
    ("weak", 700, 899, 25, 44),
    ("low", 0, 699, 0, 24),
]


def _elo_to_band_index(elo: int) -> int:
    """Map an ELO value to a band index (0=elite .. 4=low)."""
    for i, (_, low, high, _, _) in enumerate(BANDS):
        if low <= elo <= high:
            return i
    return 2  # default to mid


def _community_rating_range(band_index: int) -> tuple[float, float]:
    """Return (low, high) community rating for a band index."""
    _, _, _, cr_low, cr_high = BANDS[band_index]
    return float(cr_low), float(cr_high)


@router.get("/cards", response_model=list[SwipeCardSchema])
async def get_swipe_cards(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return up to 10 unknown films for a swipe session, weighted by community rating band."""
    uid = current_user.id

    # Find user's median ELO to determine taste band
    median_stmt = select(func.percentile_cont(0.5).within_group(UserMovie.elo)).where(
        UserMovie.user_id == uid,
        UserMovie.elo.is_not(None),
    )
    result = await db.execute(median_stmt)
    median_elo = result.scalar_one_or_none()

    # Base query: unknown films for this user (must have poster)
    base = (
        select(
            Movie.id,
            Movie.trakt_id,
            Movie.title,
            Movie.year,
            Movie.genres,
            Movie.poster_url,
            Movie.community_rating,
        )
        .join(UserMovie, UserMovie.movie_id == Movie.id)
        .where(UserMovie.user_id == uid, UserMovie.seen.is_(None), Movie.poster_url.isnot(None))
    )

    if median_elo is None:
        # No ranked films yet — prioritize popular/trending (high community_rating)
        stmt = base.where(Movie.community_rating.isnot(None)).order_by(
            Movie.community_rating.desc(), func.random()
        ).limit(10)
        result = await db.execute(stmt)
        rows = result.all()
        # Backfill with random if not enough rated films
        if len(rows) < 10:
            seen_ids = [r.id for r in rows]
            backfill = base.order_by(func.random()).limit(10 - len(rows))
            if seen_ids:
                backfill = backfill.where(Movie.id.notin_(seen_ids))
            result = await db.execute(backfill)
            rows.extend(result.all())
    else:
        # Band-weighted selection: 60% target, 20% above, 20% below
        band_idx = _elo_to_band_index(int(median_elo))

        target_range = _community_rating_range(band_idx)
        above_idx = max(0, band_idx - 1)
        below_idx = min(len(BANDS) - 1, band_idx + 1)
        above_range = _community_rating_range(above_idx)
        below_range = _community_rating_range(below_idx)

        rows = []
        for cr_range, limit in [
            (target_range, 6),
            (above_range, 2),
            (below_range, 2),
        ]:
            stmt = (
                base.where(
                    Movie.community_rating >= cr_range[0],
                    Movie.community_rating <= cr_range[1],
                )
                .order_by(func.random())
                .limit(limit)
            )
            result = await db.execute(stmt)
            rows.extend(result.all())

        # If we didn't get enough from banded selection, backfill randomly
        if len(rows) < 10:
            seen_ids = [r.id for r in rows]
            backfill_stmt = base.order_by(func.random()).limit(10 - len(rows))
            if seen_ids:
                backfill_stmt = backfill_stmt.where(Movie.id.notin_(seen_ids))
            result = await db.execute(backfill_stmt)
            rows.extend(result.all())

    if not rows:
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
async def submit_swipe_results(
    body: SwipeSubmit,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit all swipe results at once — bulk update seen status."""
    uid = current_user.id
    now = datetime.now(timezone.utc)
    seen_count = 0
    unseen_count = 0

    for item in body.results:
        movie_id = uuid.UUID(item.movie_id)

        # Update user_movies.seen
        stmt = select(UserMovie).where(
            UserMovie.user_id == uid, UserMovie.movie_id == movie_id
        )
        result = await db.execute(stmt)
        um = result.scalar_one_or_none()
        if um:
            um.seen = item.seen
            um.updated_at = now
        else:
            logger.warning("UserMovie not found for user=%s movie=%s", uid, movie_id)
            continue

        # Insert swipe_results record
        sr = SwipeResult(user_id=uid, movie_id=movie_id, seen=item.seen)
        db.add(sr)

        if item.seen:
            seen_count += 1
        else:
            unseen_count += 1

    # Check if user has enough seen films to duel
    seen_unranked_stmt = (
        select(func.count())
        .select_from(UserMovie)
        .where(UserMovie.user_id == uid, UserMovie.seen.is_(True), UserMovie.battles == 0)
    )
    seen_unranked = (await db.execute(seen_unranked_stmt)).scalar() or 0

    # Also count total seen (ranked + unranked) — need at least 2 to duel
    total_seen_stmt = (
        select(func.count())
        .select_from(UserMovie)
        .where(UserMovie.user_id == uid, UserMovie.seen.is_(True))
    )
    total_seen = (await db.execute(total_seen_stmt)).scalar() or 0

    next_action = "duel" if (total_seen >= 10 and seen_unranked >= 3) else "swipe"

    # Check if pool needs expansion
    unknown_stmt = (
        select(func.count())
        .select_from(UserMovie)
        .where(UserMovie.user_id == uid, UserMovie.seen.is_(None))
    )
    unknown_count = (await db.execute(unknown_stmt)).scalar() or 0

    if unknown_count < 50:
        background_tasks.add_task(expand_pool, uid)

    return SwipeResponse(seen_count=seen_count, unseen_count=unseen_count, next_action=next_action)
