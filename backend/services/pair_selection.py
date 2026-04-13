"""Duel pair selection algorithm with quality band matching."""

from __future__ import annotations

import random

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from backend.db_models import UserMovie

# ---------------------------------------------------------------------------
# Quality band helpers
# ---------------------------------------------------------------------------

BAND_ORDER = ["elite", "strong", "mid", "weak", "poor"]


def elo_to_band(elo: int | None) -> str:
    if elo is None:
        return "mid"
    if elo >= 1300:
        return "elite"
    if elo >= 1100:
        return "strong"
    if elo >= 900:
        return "mid"
    if elo >= 700:
        return "weak"
    return "poor"


def community_rating_to_band(rating: float | None) -> str:
    if rating is None:
        return "mid"
    if rating >= 80:
        return "elite"
    if rating >= 65:
        return "strong"
    if rating >= 45:
        return "mid"
    if rating >= 25:
        return "weak"
    return "poor"


def bands_adjacent(band_a: str, band_b: str) -> bool:
    ia = BAND_ORDER.index(band_a)
    ib = BAND_ORDER.index(band_b)
    return abs(ia - ib) <= 1


def _film_band(um: UserMovie) -> str:
    """Determine quality band for a UserMovie.

    Ranked films (battles >= 1) use ELO; unranked use community_rating.
    """
    if um.battles >= 1:
        return elo_to_band(um.elo)
    return community_rating_to_band(
        float(um.movie.community_rating) if um.movie.community_rating is not None else None
    )


# ---------------------------------------------------------------------------
# Pair selection
# ---------------------------------------------------------------------------


async def select_pair(
    db: AsyncSession,
    uid,
    last_pair_ids: set[str] | None,
) -> tuple[UserMovie, UserMovie]:
    """Select a duel pair from seen films with quality band matching.

    1. Pick anchor (film A) weighted by settlement: 1/(battles+1).
    2. Determine anchor's band.
    3. Filter candidates to same band, then adjacent, then full pool.
    4. For ranked-vs-ranked: 70% close matches, 30% wide matches.

    Raises ValueError if fewer than 2 seen films exist.
    """

    # All seen films
    seen_stmt = (
        select(UserMovie)
        .options(joinedload(UserMovie.movie))
        .where(
            UserMovie.user_id == uid,
            UserMovie.seen.is_(True),
        )
    )
    seen_result = await db.execute(seen_stmt)
    seen_films = list(seen_result.unique().scalars().all())

    if len(seen_films) < 2:
        raise ValueError("Need more seen films to duel. Swipe to classify some movies first!")

    # Split into anchors (ranked, battles >= 1) and full pool
    anchor_pool = [f for f in seen_films if f.battles >= 1 and f.elo is not None]

    # Bootstrap: no anchors yet — pick two seen films by settlement weight
    if len(anchor_pool) == 0:
        return _pick_bootstrap_pair(seen_films, last_pair_ids)

    # Normal: anchor + challenger from band-filtered pool
    for _ in range(5):
        anchor = _weighted_sample(anchor_pool)
        anchor_band = elo_to_band(anchor.elo)

        # Build candidate pool excluding anchor
        all_candidates = [f for f in seen_films if f.movie_id != anchor.movie_id]
        if not all_candidates:
            break

        # Band filter: same band first, then adjacent, then full pool
        candidates = _band_filtered_candidates(anchor_band, all_candidates)

        # Match distance variation for ranked-vs-ranked
        challenger = _pick_challenger(anchor, candidates)

        # Anti-repeat
        pair_ids = {str(anchor.movie_id), str(challenger.movie_id)}
        if last_pair_ids is None or pair_ids != last_pair_ids:
            return anchor, challenger

    # Fallback after retries
    return anchor, challenger  # type: ignore


def _band_filtered_candidates(
    anchor_band: str,
    candidates: list[UserMovie],
) -> list[UserMovie]:
    """Filter candidates by quality band: same > adjacent > all."""
    # Same band
    same = [f for f in candidates if _film_band(f) == anchor_band]
    if same:
        return same

    # Adjacent bands (±1 step)
    adjacent = [f for f in candidates if bands_adjacent(anchor_band, _film_band(f))]
    if adjacent:
        return adjacent

    # Full pool fallback
    return candidates


def _pick_challenger(anchor: UserMovie, candidates: list[UserMovie]) -> UserMovie:
    """Pick challenger with match distance variation for ranked-vs-ranked pairs.

    - 70%: prefer close matches (ELO diff < 150), sample from top 10
    - 30%: prefer wide matches (ELO diff > 300)
    Falls back to settlement-weighted sample if filters produce nothing.
    """
    # Separate ranked candidates (both anchor and candidate have battles >= 1)
    ranked = [f for f in candidates if f.battles >= 1 and f.elo is not None]

    if ranked and anchor.elo is not None:
        roll = random.random()
        if roll < 0.70:
            # Close match: sort by abs ELO diff, take top 10
            ranked_sorted = sorted(ranked, key=lambda f: abs(f.elo - anchor.elo))
            close = [f for f in ranked_sorted[:10] if abs(f.elo - anchor.elo) < 150]
            if close:
                return _weighted_sample(close)
            # If no close matches in top 10, use top 10 anyway
            return _weighted_sample(ranked_sorted[:10])
        else:
            # Wide match: ELO diff > 300
            wide = [f for f in ranked if abs(f.elo - anchor.elo) > 300]
            if wide:
                return _weighted_sample(wide)

    # Default: settlement-weighted from full candidate pool
    return _weighted_sample(candidates)


def _pick_bootstrap_pair(
    seen_films: list[UserMovie],
    last_pair_ids: set[str] | None,
) -> tuple[UserMovie, UserMovie]:
    """Bootstrap: pick two seen films when no anchors exist."""
    for _ in range(5):
        a, b = random.sample(seen_films, 2)
        pair_ids = {str(a.movie_id), str(b.movie_id)}
        if last_pair_ids is None or pair_ids != last_pair_ids:
            return a, b
    return a, b  # type: ignore


def _weighted_sample(films: list[UserMovie]) -> UserMovie:
    """Sample one film weighted by settlement: 1/(battles+1)."""
    weights = [1.0 / (f.battles + 1) for f in films]
    return random.choices(films, weights=weights, k=1)[0]
