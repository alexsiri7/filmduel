"""Duel submission routes."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import get_db
from backend.models import (
    Duel,
    DuelSubmit,
    DuelResult,
    UserMovie,
)
from backend.routers.auth import get_current_user_id
from backend.services.elo import outcome_to_scores, update_elo

router = APIRouter(prefix="/api/duels", tags=["duels"])


@router.post("", response_model=DuelResult)
async def submit_duel(
    body: DuelSubmit,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Submit the result of a duel and update ELO ratings."""
    uid = uuid.UUID(user_id)
    movie_a_id = uuid.UUID(body.movie_a_id)
    movie_b_id = uuid.UUID(body.movie_b_id)
    outcome = body.outcome.value

    # Fetch or create user_movie rows
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

    old_elo_a = um_a.elo
    old_elo_b = um_b.elo

    # Update seen status based on outcome
    if outcome == "a_only":
        um_a.seen = True
        um_b.seen = False
    elif outcome == "b_only":
        um_a.seen = False
        um_b.seen = True
    elif outcome in ("a_wins", "b_wins"):
        um_a.seen = True
        um_b.seen = True
    # "neither" — both unseen, leave seen as-is or set False
    elif outcome == "neither":
        um_a.seen = False
        um_b.seen = False

    # Calculate new ELO
    score_a, score_b = outcome_to_scores(outcome)
    if outcome == "neither":
        new_elo_a, new_elo_b = old_elo_a, old_elo_b
    else:
        new_elo_a, new_elo_b = update_elo(old_elo_a, old_elo_b, score_a)

    delta_a = new_elo_a - old_elo_a
    delta_b = new_elo_b - old_elo_b

    # Update user_movie records
    um_a.elo = new_elo_a
    um_a.battles += 1
    um_a.last_dueled_at = datetime.now(timezone.utc)
    um_a.updated_at = datetime.now(timezone.utc)

    um_b.elo = new_elo_b
    um_b.battles += 1
    um_b.last_dueled_at = datetime.now(timezone.utc)
    um_b.updated_at = datetime.now(timezone.utc)

    # Record duel history
    winner_id = None
    loser_id = None
    w_elo_before = None
    l_elo_before = None
    w_elo_after = None
    l_elo_after = None

    if outcome in ("a_wins", "a_only"):
        winner_id = movie_a_id
        loser_id = movie_b_id
        w_elo_before = old_elo_a
        l_elo_before = old_elo_b
        w_elo_after = new_elo_a
        l_elo_after = new_elo_b
    elif outcome in ("b_wins", "b_only"):
        winner_id = movie_b_id
        loser_id = movie_a_id
        w_elo_before = old_elo_b
        l_elo_before = old_elo_a
        w_elo_after = new_elo_b
        l_elo_after = new_elo_a

    duel = Duel(
        user_id=uid,
        winner_movie_id=winner_id,
        loser_movie_id=loser_id,
        winner_elo_before=w_elo_before,
        loser_elo_before=l_elo_before,
        winner_elo_after=w_elo_after,
        loser_elo_after=l_elo_after,
    )
    db.add(duel)

    return DuelResult(
        outcome=body.outcome,
        movie_a_elo_delta=delta_a,
        movie_b_elo_delta=delta_b,
    )
