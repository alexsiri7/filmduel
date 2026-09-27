"""Duel pair selection: least-dueled anchor, closest-rated challenger."""

from __future__ import annotations

import random

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from backend.db_models import Movie, UserMovie
from backend.services.elo import get_initial_elo

CLOSEST_CANDIDATES = 5


def _effective_elo(um: UserMovie) -> int:
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

    Raises ValueError if fewer than 2 seen films exist.
    """
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
    seen_result = await db.execute(seen_stmt)
    seen_films = list(seen_result.unique().scalars().all())

    if len(seen_films) < 2:
        raise ValueError(
            f"Need more seen {media_type}s to duel. Swipe to classify some {media_type}s first!"
        )

    fewest = min(f.battles for f in seen_films)
    anchor = random.choice([f for f in seen_films if f.battles == fewest])

    candidates = [f for f in seen_films if f.movie_id != anchor.movie_id]
    if last_pair_ids and str(anchor.movie_id) in last_pair_ids:
        fresh = [f for f in candidates if str(f.movie_id) not in last_pair_ids]
        if fresh:
            candidates = fresh

    anchor_elo = _effective_elo(anchor)
    candidates.sort(key=lambda f: abs(_effective_elo(f) - anchor_elo))
    challenger = random.choice(candidates[:CLOSEST_CANDIDATES])
    return anchor, challenger
