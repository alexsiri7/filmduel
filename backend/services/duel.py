"""Duel business logic — ELO updates, user_movie mutations, duel records.

Extracted from the router so the core logic is testable and not duplicated
between the inline handler and a background task.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db_models import Duel, UserMovie
from backend.schemas import DuelOutcome, DuelResult
from backend.services.elo import get_initial_elo, update_elo

logger = logging.getLogger(__name__)


async def apply_elo_result(
    db: AsyncSession,
    user_id: uuid.UUID,
    winner_id: uuid.UUID,
    loser_id: uuid.UUID,
    um_w: UserMovie,
    um_l: UserMovie,
    mode: str,
) -> Duel:
    """Compute ELO, mutate UserMovies, create+return Duel record."""
    now = datetime.now(timezone.utc)
    w_elo = um_w.elo if um_w.elo is not None else get_initial_elo(um_w.seeded_elo)
    l_elo = um_l.elo if um_l.elo is not None else get_initial_elo(um_l.seeded_elo)
    new_w, new_l = update_elo(w_elo, l_elo, um_w.battles, um_l.battles)

    um_w.elo = new_w
    um_l.elo = new_l
    um_w.battles += 1
    um_l.battles += 1
    um_w.last_dueled_at = now
    um_l.last_dueled_at = now
    um_w.updated_at = now
    um_l.updated_at = now

    duel = Duel(
        user_id=user_id,
        winner_movie_id=winner_id,
        loser_movie_id=loser_id,
        winner_elo_before=w_elo,
        loser_elo_before=l_elo,
        winner_elo_after=new_w,
        loser_elo_after=new_l,
        mode=mode,
    )
    db.add(duel)
    return duel


@dataclass
class ProcessDuelResult:
    """Internal result carrying both the API response and data needed by background tasks."""

    api_result: DuelResult
    new_elo_a: int | None
    new_elo_b: int | None


async def get_user_movie(
    db: AsyncSession, user_id: uuid.UUID, movie_id: uuid.UUID
) -> UserMovie:
    """Fetch an existing UserMovie or raise if not found."""
    stmt = select(UserMovie).where(
        UserMovie.user_id == user_id, UserMovie.movie_id == movie_id
    )
    result = await db.execute(stmt)
    um = result.scalar_one_or_none()
    if not um:
        raise ValueError("Movie not in your pool")
    return um


async def process_duel(
    db: AsyncSession,
    user_id: uuid.UUID,
    movie_a_id: uuid.UUID,
    movie_b_id: uuid.UUID,
    outcome: str,
    mode: str,
) -> ProcessDuelResult:
    """Run the full duel pipeline: ELO math, DB mutations, duel record.

    All writes happen on the provided session (committed by the caller /
    FastAPI dependency).  Returns a ``DuelResult`` ready to send to the client.
    """
    # ── Fetch / create user_movies ──────────────────────────────────
    um_a = await get_user_movie(db, user_id, movie_a_id)
    um_b = await get_user_movie(db, user_id, movie_b_id)

    um_a_seen_was_none = um_a.seen is None
    um_b_seen_was_none = um_b.seen is None

    # ── Pair type (before battles are incremented) ──────────────────
    if um_a.battles >= 1 and um_b.battles >= 1:
        pair_type = "ranked_vs_ranked"
    elif um_a.battles == 0 or um_b.battles == 0:
        pair_type = "ranked_vs_unranked"
    else:
        pair_type = "unknown"

    # ── ELO math + duel record ───────────────────────────────────────
    new_elo_a: int | None = um_a.elo
    new_elo_b: int | None = um_b.elo
    delta_a = 0
    delta_b = 0

    now = datetime.now(timezone.utc)

    if outcome in ("a_wins", "b_wins"):
        elo_a_before = um_a.elo if um_a.elo is not None else get_initial_elo(um_a.seeded_elo)
        elo_b_before = um_b.elo if um_b.elo is not None else get_initial_elo(um_b.seeded_elo)

        if outcome == "a_wins":
            winner_id, loser_id = movie_a_id, movie_b_id
            um_w, um_l = um_a, um_b
        else:
            winner_id, loser_id = movie_b_id, movie_a_id
            um_w, um_l = um_b, um_a

        um_a.seen = True
        um_b.seen = True
        duel = await apply_elo_result(db, user_id, winner_id, loser_id, um_w, um_l, mode)
        duel.pair_type = pair_type

        new_elo_a = um_a.elo
        new_elo_b = um_b.elo
        delta_a = new_elo_a - elo_a_before
        delta_b = new_elo_b - elo_b_before
    elif outcome == "a_only":
        if um_a_seen_was_none:
            um_a.seen = True
        um_b.seen = False
    elif outcome == "b_only":
        if um_b_seen_was_none:
            um_b.seen = True
        um_a.seen = False
    elif outcome == "neither":
        um_a.seen = False
        um_b.seen = False

    if outcome in ("a_only", "b_only", "neither"):
        um_a.updated_at = now
        um_b.updated_at = now
        duel = Duel(user_id=user_id, mode=mode, pair_type=pair_type)
        db.add(duel)

    logger.info(
        "duel_processed user_id=%s outcome=%s pair_type=%s elo_delta_a=%+d elo_delta_b=%+d",
        user_id, outcome, pair_type, delta_a, delta_b,
    )

    # ── next_action ─────────────────────────────────────────────────
    seen_unranked_stmt = select(func.count()).where(
        UserMovie.user_id == user_id,
        UserMovie.seen.is_(True),
        UserMovie.battles == 0,
    )
    seen_unranked_result = await db.execute(seen_unranked_stmt)
    seen_unranked = seen_unranked_result.scalar_one()

    total_seen_stmt = select(func.count()).where(
        UserMovie.user_id == user_id,
        UserMovie.seen.is_(True),
    )
    total_seen_result = await db.execute(total_seen_stmt)
    total_seen = total_seen_result.scalar_one()

    next_action = "swipe" if (seen_unranked < 3 or total_seen < 10) else "duel"

    logger.info(
        "duel_next_action user_id=%s next_action=%s seen_unranked=%d",
        user_id, next_action, seen_unranked,
    )

    return ProcessDuelResult(
        api_result=DuelResult(
            outcome=DuelOutcome(outcome),
            movie_a_elo_delta=delta_a,
            movie_b_elo_delta=delta_b,
            next_action=next_action,
        ),
        new_elo_a=new_elo_a,
        new_elo_b=new_elo_b,
    )
