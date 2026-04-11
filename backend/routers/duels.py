"""Duel submission routes."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import async_session_factory, get_db
from backend.models import (
    Duel,
    DuelSubmit,
    DuelResult,
    Movie,
    User,
    UserMovie,
)
from backend.routers.auth import get_current_user
from backend.services.elo import outcome_to_scores, update_elo
from backend.services.sync import sync_post_duel

router = APIRouter(prefix="/api/duels", tags=["duels"])


async def _sync_ratings_background(
    user_id: uuid.UUID,
    movie_a_id: uuid.UUID,
    new_elo_a: int,
    movie_b_id: uuid.UUID,
    new_elo_b: int,
) -> None:
    """Background task: sync post-duel ELO ratings to Trakt.

    Opens its own DB session so it doesn't depend on the request session.
    """
    async with async_session_factory() as session:
        # Fetch user's access token
        user_stmt = select(User.trakt_access_token).where(User.id == user_id)
        result = await session.execute(user_stmt)
        access_token = result.scalar_one_or_none()
        if not access_token:
            return

        # Fetch trakt_ids for both movies
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
    """Submit the result of a duel and update ELO ratings."""
    uid = current_user.id
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

    # Sync both films' ratings to Trakt asynchronously after a_wins/b_wins
    if outcome in ("a_wins", "b_wins"):
        background_tasks.add_task(
            _sync_ratings_background,
            uid,
            movie_a_id,
            new_elo_a,
            movie_b_id,
            new_elo_b,
        )

    return DuelResult(
        outcome=body.outcome,
        movie_a_elo_delta=delta_a,
        movie_b_elo_delta=delta_b,
    )
