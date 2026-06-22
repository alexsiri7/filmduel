"""Duel submission routes."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import async_session_factory, get_db
from backend.rate_limit import limiter
from backend.db_models import Movie, User
from backend.schemas import DuelSubmit, DuelResult
from backend.routers.auth import get_admin_user, get_current_user, ensure_fresh_token
from backend.services.duel import process_duel
from backend.utils.tokens import decode_pair_token
from backend.services.retention import purge_old_duels as _purge_old_duels
from backend.services.sync import sync_post_duel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/duels", tags=["duels"])


async def _sync_ratings_background(
    user_id: uuid.UUID,
    movie_a_id: uuid.UUID,
    new_elo_a: int,
    movie_b_id: uuid.UUID,
    new_elo_b: int,
) -> None:
    """Fire-and-forget Trakt rating sync after a duel with a winner."""
    try:
        async with async_session_factory() as session:
            user_stmt = select(User).where(User.id == user_id)
            result = await session.execute(user_stmt)
            user = result.scalar_one_or_none()
            if (
                not user
                or not user.trakt_access_token
                or not user.sync_ratings_to_trakt
            ):
                return
            user = await ensure_fresh_token(user, session)
            await session.commit()
            access_token = user.trakt_access_token
            movies_stmt = select(Movie.id, Movie.trakt_id, Movie.media_type).where(
                Movie.id.in_([movie_a_id, movie_b_id])
            )
            result = await session.execute(movies_stmt)
            rows = result.all()
            trakt_map = {row.id: row.trakt_id for row in rows}
            # Both movies in a duel are the same media_type
            media_type = rows[0].media_type if rows else "movie"
        movie_ratings = []
        if movie_a_id in trakt_map:
            movie_ratings.append((trakt_map[movie_a_id], new_elo_a))
        if movie_b_id in trakt_map:
            movie_ratings.append((trakt_map[movie_b_id], new_elo_b))
        if movie_ratings:
            await sync_post_duel(access_token, movie_ratings, media_type)
    except Exception:
        logger.exception(
            "Background rating sync failed for user %s (token refresh or sync error)",
            user_id,
        )


@router.post("", response_model=DuelResult)
@limiter.limit("60/minute")
async def submit_duel(
    request: Request,
    body: DuelSubmit,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    uid = current_user.id
    movie_a_id = body.movie_a_id
    movie_b_id = body.movie_b_id
    outcome = body.outcome.value
    mode = body.mode.value

    logger.info(
        "duel_submitted user_id=%s movie_a=%s movie_b=%s outcome=%s mode=%s",
        uid,
        movie_a_id,
        movie_b_id,
        outcome,
        mode,
    )

    # Validate pair token before anything else
    token_ids = decode_pair_token(body.pair_token)
    submitted_ids = {str(movie_a_id), str(movie_b_id)}
    if token_ids is None or token_ids != submitted_ids:
        raise HTTPException(status_code=400, detail="Invalid pair token")

    try:
        result = await process_duel(db, uid, movie_a_id, movie_b_id, outcome, mode)
    except ValueError:
        logger.warning("Invalid duel submission for user %s", uid)
        raise HTTPException(status_code=400, detail="Invalid duel submission")

    # Trakt sync in background (fire-and-forget)
    if (
        outcome in ("a_wins", "b_wins")
        and result.new_elo_a is not None
        and result.new_elo_b is not None
    ):
        background_tasks.add_task(
            _sync_ratings_background,
            uid,
            movie_a_id,
            result.new_elo_a,
            movie_b_id,
            result.new_elo_b,
        )

    return result.api_result


@router.delete("/admin/purge-old-records", status_code=200)
async def purge_old_duels(
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    count = await _purge_old_duels(db)
    logger.info("purge_old_duels count=%d triggered_by=%s", count, current_user.id)
    return {"purged": count}
