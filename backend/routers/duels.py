"""Duel submission routes."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import async_session_factory, get_db
from backend.db_models import Duel, Movie, User, UserMovie
from backend.schemas import DuelSubmit, DuelResult
from backend.routers.auth import get_current_user
from backend.services.elo import get_initial_elo, update_elo
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
    async with async_session_factory() as session:
        user_stmt = select(User.trakt_access_token).where(User.id == user_id)
        result = await session.execute(user_stmt)
        access_token = result.scalar_one_or_none()
        if not access_token:
            return
        movies_stmt = select(Movie.id, Movie.trakt_id).where(
            Movie.id.in_([movie_a_id, movie_b_id])
        )
        result = await session.execute(movies_stmt)
        trakt_map = {row.id: row.trakt_id for row in result.all()}
    movie_ratings = []
    if movie_a_id in trakt_map:
        movie_ratings.append((trakt_map[movie_a_id], new_elo_a))
    if movie_b_id in trakt_map:
        movie_ratings.append((trakt_map[movie_b_id], new_elo_b))
    if movie_ratings:
        await sync_post_duel(access_token, movie_ratings)


@router.post("", response_model=DuelResult)
async def submit_duel(
    body: DuelSubmit,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    uid = current_user.id
    movie_a_id = uuid.UUID(body.movie_a_id)
    movie_b_id = uuid.UUID(body.movie_b_id)
    outcome = body.outcome.value
    mode = body.mode

    async def get_or_create_user_movie(mid: uuid.UUID) -> UserMovie:
        stmt = select(UserMovie).where(
            UserMovie.user_id == uid, UserMovie.movie_id == mid
        )
        result = await db.execute(stmt)
        um = result.scalar_one_or_none()
        if not um:
            um = UserMovie(user_id=uid, movie_id=mid)
            db.add(um)
            await db.flush()
        return um

    um_a = await get_or_create_user_movie(movie_a_id)
    um_b = await get_or_create_user_movie(movie_b_id)

    # Compute pair_type before battles are incremented
    if um_a.battles >= 1 and um_b.battles >= 1:
        pair_type = "ranked_vs_ranked"
    elif um_a.battles == 0 or um_b.battles == 0:
        pair_type = "ranked_vs_unranked"
    else:
        pair_type = "unknown"

    new_elo_a: int | None = um_a.elo
    new_elo_b: int | None = um_b.elo
    delta_a = 0
    delta_b = 0

    if outcome in ("a_wins", "b_wins"):
        # Both films become Ranked: seen=True, elo initialized, battles incremented
        um_a.seen = True
        um_b.seen = True

        # Initialize ELO for first-time ranked films (elo is NULL, battles=0)
        elo_a = um_a.elo if um_a.elo is not None else get_initial_elo(um_a.seeded_elo)
        elo_b = um_b.elo if um_b.elo is not None else get_initial_elo(um_b.seeded_elo)

        if outcome == "a_wins":
            new_elo_a, new_elo_b = update_elo(
                elo_a, elo_b, um_a.battles, um_b.battles
            )
        else:  # b_wins
            new_elo_b, new_elo_a = update_elo(
                elo_b, elo_a, um_b.battles, um_a.battles
            )

        delta_a = new_elo_a - elo_a
        delta_b = new_elo_b - elo_b

        um_a.elo = new_elo_a
        um_b.elo = new_elo_b
        um_a.battles += 1
        um_b.battles += 1
        um_a.last_dueled_at = datetime.now(timezone.utc)
        um_b.last_dueled_at = datetime.now(timezone.utc)
        um_a.updated_at = datetime.now(timezone.utc)
        um_b.updated_at = datetime.now(timezone.utc)

    elif outcome == "a_only":
        # A -> seen (if was unknown/null), B -> unseen (never gets ELO)
        if um_a.seen is None:
            um_a.seen = True
        um_b.seen = False
        um_a.updated_at = datetime.now(timezone.utc)
        um_b.updated_at = datetime.now(timezone.utc)

    elif outcome == "b_only":
        # B -> seen (if was unknown/null), A -> unseen (never gets ELO)
        if um_b.seen is None:
            um_b.seen = True
        um_a.seen = False
        um_a.updated_at = datetime.now(timezone.utc)
        um_b.updated_at = datetime.now(timezone.utc)

    elif outcome == "neither":
        # Both -> unseen
        um_a.seen = False
        um_b.seen = False
        um_a.updated_at = datetime.now(timezone.utc)
        um_b.updated_at = datetime.now(timezone.utc)

    # Build duel record
    winner_id = loser_id = None
    w_elo_before = l_elo_before = w_elo_after = l_elo_after = None
    if outcome == "a_wins":
        winner_id, loser_id = movie_a_id, movie_b_id
        w_elo_before, l_elo_before = elo_a, elo_b
        w_elo_after, l_elo_after = new_elo_a, new_elo_b
    elif outcome == "b_wins":
        winner_id, loser_id = movie_b_id, movie_a_id
        w_elo_before, l_elo_before = elo_b, elo_a
        w_elo_after, l_elo_after = new_elo_b, new_elo_a

    duel = Duel(
        user_id=uid,
        winner_movie_id=winner_id,
        loser_movie_id=loser_id,
        winner_elo_before=w_elo_before,
        loser_elo_before=l_elo_before,
        winner_elo_after=w_elo_after,
        loser_elo_after=l_elo_after,
        mode=mode,
        pair_type=pair_type,
    )
    db.add(duel)

    # Fire background Trakt sync only for ranking outcomes
    if outcome in ("a_wins", "b_wins"):
        background_tasks.add_task(
            _sync_ratings_background, uid, movie_a_id, new_elo_a, movie_b_id, new_elo_b,
        )

    # Compute next_action: if fewer than 3 seen-but-unranked films, suggest swipe
    seen_unranked_stmt = select(func.count()).where(
        UserMovie.user_id == uid,
        UserMovie.seen.is_(True),
        UserMovie.battles == 0,
    )
    seen_unranked_result = await db.execute(seen_unranked_stmt)
    seen_unranked = seen_unranked_result.scalar_one()
    next_action = "swipe" if seen_unranked < 3 else "duel"

    return DuelResult(
        outcome=body.outcome,
        movie_a_elo_delta=delta_a,
        movie_b_elo_delta=delta_b,
        next_action=next_action,
    )
