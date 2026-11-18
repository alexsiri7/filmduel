"""Duel business logic — ELO updates, user_movie mutations, duel records.

Extracted from the router so the core logic is testable and not duplicated
between the inline handler and a background task.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import assert_never

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db_models import Duel, Movie, UserMovie
from backend.schemas import DuelMode, DuelOutcome, DuelResult
from backend.services.elo import effective_elo, update_elo

logger = logging.getLogger(__name__)

MIN_SEEN_UNRANKED = 3
MIN_TOTAL_SEEN = 10


def should_suggest_swipe(seen_unranked: int, total_seen: int) -> bool:
    """Return True if the user needs more swipes before dueling."""
    return seen_unranked < MIN_SEEN_UNRANKED or total_seen < MIN_TOTAL_SEEN


async def compute_next_action(
    db: AsyncSession, user_id: uuid.UUID, media_type: str
) -> str:
    """Determine whether user should swipe or duel next, scoped by media_type."""
    seen_unranked_stmt = (
        select(func.count())
        .select_from(UserMovie)
        .join(Movie, UserMovie.movie_id == Movie.id)
        .where(
            UserMovie.user_id == user_id,
            UserMovie.seen.is_(True),
            UserMovie.battles == 0,
            Movie.media_type == media_type,
        )
    )
    seen_unranked = (await db.execute(seen_unranked_stmt)).scalar_one()

    total_seen_stmt = (
        select(func.count())
        .select_from(UserMovie)
        .join(Movie, UserMovie.movie_id == Movie.id)
        .where(
            UserMovie.user_id == user_id,
            UserMovie.seen.is_(True),
            Movie.media_type == media_type,
        )
    )
    total_seen = (await db.execute(total_seen_stmt)).scalar_one()

    return "swipe" if should_suggest_swipe(seen_unranked, total_seen) else "duel"


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
    w_elo = effective_elo(um_w)
    l_elo = effective_elo(um_l)
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
    new_elo_a: float | None
    new_elo_b: float | None


@dataclass(frozen=True)
class OutcomeEffect:
    """What a duel outcome decided beyond the seen flags it already applied."""

    pair_type: str
    winner_and_loser: tuple[UserMovie, UserMovie] | None = None


def apply_outcome(
    um_a: UserMovie, um_b: UserMovie, outcome: DuelOutcome, now: datetime
) -> OutcomeEffect:
    """Apply an outcome's seen-flag rules to the pair and classify the duel.

    A decisive outcome names the winner and loser for the caller to rate;
    the others only touch seen flags. Films with battles are never marked
    unseen, so a skip cannot hide a ranked film.
    """
    ranked = um_a.battles >= 1 and um_b.battles >= 1
    pair_type = "ranked_vs_ranked" if ranked else "ranked_vs_unranked"

    match outcome:
        case DuelOutcome.a_wins | DuelOutcome.b_wins:
            um_a.seen = True
            um_b.seen = True
            if outcome == DuelOutcome.a_wins:
                return OutcomeEffect(pair_type, (um_a, um_b))
            return OutcomeEffect(pair_type, (um_b, um_a))
        case DuelOutcome.a_only:
            _mark_only_one_seen(seen=um_a, other=um_b)
        case DuelOutcome.b_only:
            _mark_only_one_seen(seen=um_b, other=um_a)
        case DuelOutcome.neither:
            _mark_unseen_unless_ranked(um_a)
            _mark_unseen_unless_ranked(um_b)
        case _:
            assert_never(outcome)

    um_a.updated_at = now
    um_b.updated_at = now
    return OutcomeEffect(pair_type)


def _mark_only_one_seen(*, seen: UserMovie, other: UserMovie) -> None:
    if seen.seen is None:
        seen.seen = True
    _mark_unseen_unless_ranked(other)


def _mark_unseen_unless_ranked(um: UserMovie) -> None:
    if um.battles == 0:
        um.seen = False


async def get_user_movie(
    db: AsyncSession,
    user_id: uuid.UUID,
    movie_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> UserMovie:
    """Fetch an existing UserMovie or raise if not found."""
    stmt = select(UserMovie).where(
        UserMovie.user_id == user_id, UserMovie.movie_id == movie_id
    )
    if for_update:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    um = result.scalar_one_or_none()
    if not um:
        raise ValueError("Movie not in your pool")
    return um


async def lock_user_movie_pair(
    db: AsyncSession,
    user_id: uuid.UUID,
    movie_a_id: uuid.UUID,
    movie_b_id: uuid.UUID,
) -> tuple[UserMovie, UserMovie]:
    """Lock both UserMovie rows FOR UPDATE, returned in argument order.

    The rows are always locked in UUID order, so concurrent writers over the
    same pair cannot deadlock whichever way round they name it.
    """
    first_id, second_id = sorted([movie_a_id, movie_b_id])
    um_first = await get_user_movie(db, user_id, first_id, for_update=True)
    um_second = await get_user_movie(db, user_id, second_id, for_update=True)
    return (um_first, um_second) if first_id == movie_a_id else (um_second, um_first)


async def _media_type(db: AsyncSession, movie_id: uuid.UUID) -> str:
    row = await db.execute(select(Movie.media_type).where(Movie.id == movie_id))
    return row.scalar_one_or_none() or "movie"


async def _record_duel(
    db: AsyncSession,
    user_id: uuid.UUID,
    effect: OutcomeEffect,
    outcome: DuelOutcome,
    mode: DuelMode,
) -> Duel:
    """Rate a decided duel, or record a skip by its outcome alone."""
    if effect.winner_and_loser is None:
        duel = Duel(user_id=user_id, mode=mode.value, outcome=outcome.value)
        db.add(duel)
    else:
        um_w, um_l = effect.winner_and_loser
        duel = await apply_elo_result(
            db, user_id, um_w.movie_id, um_l.movie_id, um_w, um_l, mode.value
        )
    duel.pair_type = effect.pair_type
    return duel


def _elo_delta(before: float, after: float | None) -> int:
    """Rating change as the client displays it; a never-rated film did not move."""
    return 0 if after is None else round(after) - round(before)


async def process_duel(
    db: AsyncSession,
    user_id: uuid.UUID,
    movie_a_id: uuid.UUID,
    movie_b_id: uuid.UUID,
    outcome: DuelOutcome,
    mode: DuelMode,
    *,
    pair_token_digest: str | None = None,
) -> ProcessDuelResult:
    """Run the full duel pipeline: ELO math, DB mutations, duel record.

    All writes happen on the provided session (committed by the caller /
    FastAPI dependency).  Returns a ``DuelResult`` ready to send to the client.
    """
    um_a, um_b = await lock_user_movie_pair(db, user_id, movie_a_id, movie_b_id)
    # Ownership is confirmed by the lock above, so um_a.movie_id is trusted.
    media_type = await _media_type(db, um_a.movie_id)
    elo_a_before, elo_b_before = effective_elo(um_a), effective_elo(um_b)

    effect = apply_outcome(um_a, um_b, outcome, datetime.now(timezone.utc))
    duel = await _record_duel(db, user_id, effect, outcome, mode)
    duel.pair_token_digest = pair_token_digest
    delta_a = _elo_delta(elo_a_before, um_a.elo)
    delta_b = _elo_delta(elo_b_before, um_b.elo)

    # DEBUG, not INFO: user_id + preference data is behavioral personal data (SEC-15, #583).
    logger.debug(
        "duel_processed user_id=%s outcome=%s pair_type=%s elo_delta_a=%+d elo_delta_b=%+d",
        user_id,
        outcome.value,
        effect.pair_type,
        delta_a,
        delta_b,
    )

    next_action = await compute_next_action(db, user_id, media_type)
    logger.debug("duel_next_action user_id=%s next_action=%s", user_id, next_action)

    return ProcessDuelResult(
        api_result=DuelResult(
            outcome=outcome,
            movie_a_elo_delta=delta_a,
            movie_b_elo_delta=delta_b,
            next_action=next_action,
        ),
        new_elo_a=um_a.elo,
        new_elo_b=um_b.elo,
    )
