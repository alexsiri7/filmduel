"""Duel pair selection: least-dueled anchor, closest-rated challenger."""

from __future__ import annotations

import random

from sqlalchemy import Text, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from backend.db_models import Movie, UserMovie
from backend.services.elo import DEFAULT_ELO, get_initial_elo

CLOSEST_CANDIDATES = 5


def _effective_elo(um: UserMovie) -> float:
    """ELO the duel will be scored with: current ELO, else the seeded/default start."""
    return um.elo if um.elo is not None else get_initial_elo(um.seeded_elo)


async def select_pair(
    db: AsyncSession,
    uid,
    last_pair_ids: set[str] | None,
    media_type: str = "movie",
) -> tuple[UserMovie, UserMovie]:
    """Select a duel pair from all of the user's seen films.

    1. Anchor: a film with the fewest battles, ties broken at random.
    2. Challenger: a random pick among the CLOSEST_CANDIDATES films nearest the
       anchor's effective ELO, skipping the anchor's partner from the last pair
       unless it is the only other film.

    Selection runs in SQL, so only the anchor and at most CLOSEST_CANDIDATES
    challengers are loaded (SEC-12, #784).

    Raises ValueError if fewer than 2 seen films exist.
    """
    not_enough = ValueError(
        f"Need more seen {media_type}s to duel. Swipe to classify some {media_type}s first!"
    )
    seen_stmt = (
        select(UserMovie)
        .options(joinedload(UserMovie.movie))
        .join(Movie, UserMovie.movie_id == Movie.id)
        .where(
            UserMovie.user_id == uid,
            UserMovie.seen.is_(True),
            Movie.media_type == media_type,
        )
    )

    anchor_result = await db.execute(
        seen_stmt.order_by(UserMovie.battles, func.random()).limit(1)
    )
    anchor = anchor_result.unique().scalars().first()
    if anchor is None:
        raise not_enough

    # Fresh challengers sort ahead of the anchor's last partner, so the fetched
    # rows hold the closest fresh ones whenever any exist.
    stale_ids: set[str] = set()
    if last_pair_ids and str(anchor.movie_id) in last_pair_ids:
        stale_ids = last_pair_ids - {str(anchor.movie_id)}
    effective_elo = func.coalesce(UserMovie.elo, UserMovie.seeded_elo, DEFAULT_ELO)
    order_by = [func.abs(effective_elo - _effective_elo(anchor))]
    if stale_ids:
        order_by.insert(0, cast(UserMovie.movie_id, Text).in_(stale_ids))
    challenger_result = await db.execute(
        seen_stmt.where(UserMovie.movie_id != anchor.movie_id)
        .order_by(*order_by)
        .limit(CLOSEST_CANDIDATES)
    )
    nearest = list(challenger_result.unique().scalars().all())
    if not nearest:
        raise not_enough

    fresh = [f for f in nearest if str(f.movie_id) not in stale_ids]
    challenger = random.choice(fresh or nearest)
    return anchor, challenger
