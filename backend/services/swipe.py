"""Swipe session policy — which unknown films to show, and recording the answers."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Row, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db_models import Movie, SwipeResult, UserMovie
from backend.schemas import MediaType, SwipeResultItem
from backend.services.elo import ELITE_ELO, MID_ELO, STRONG_ELO, WEAK_ELO
from backend.services.quota import DailyQuota

logger = logging.getLogger(__name__)

SESSION_SIZE = 10
POOL_EXPANSION_THRESHOLD = 50

# Per-user daily cap on swipe_results rows (SEC-21, #589). A session is at most
# 10 cards, so this allows ~200 sessions/day while bounding 180-day retention growth.
MAX_SWIPES_PER_DAY = 2000


async def _count_swipes_since(
    db: AsyncSession, user_id: uuid.UUID, cutoff: datetime
) -> int:
    stmt = select(func.count()).where(
        SwipeResult.user_id == user_id,
        SwipeResult.created_at >= cutoff,
    )
    return (await db.execute(stmt)).scalar_one()


SWIPE_DAILY_QUOTA = DailyQuota(
    name="swipe_daily_cap",
    limit=MAX_SWIPES_PER_DAY,
    count_since=_count_swipes_since,
    message=f"Daily swipe limit reached ({MAX_SWIPES_PER_DAY} per 24 hours). Please try again later.",
)

RatingRange = tuple[float, float]

# (name, elo_low, elo_high, community_rating_low, community_rating_high)
# Movie.community_rating is Numeric(4,1), so the upper bounds carry a .9 tenth to
# reach the next band's lower bound without leaving a value unclassified.
BANDS = [
    ("elite", ELITE_ELO, 9999, 80, 100),
    ("strong", STRONG_ELO, ELITE_ELO - 1, 65, 79.9),
    ("mid", MID_ELO, STRONG_ELO - 1, 45, 64.9),
    ("weak", WEAK_ELO, MID_ELO - 1, 25, 44.9),
    ("poor", 0, WEAK_ELO - 1, 0, 24.9),
]
_MID_BAND = 2


def _elo_to_band_index(elo: int) -> int:
    """Map an ELO value to a band index (0=elite .. 4=poor)."""
    for i, (_, low, high, _, _) in enumerate(BANDS):
        if low <= elo <= high:
            return i
    return _MID_BAND


def _community_rating_range(band_index: int) -> RatingRange:
    """Return (low, high) community rating for a band index."""
    _, _, _, cr_low, cr_high = BANDS[band_index]
    return float(cr_low), float(cr_high)


def plan_card_mix(
    median_elo: float | None, session_size: int = SESSION_SIZE
) -> list[tuple[RatingRange | None, int]]:
    """Plan a session as (community-rating range, card count) parts.

    A user with no ranked films gets random rated films (range ``None``).
    Otherwise 60% of the cards come from the community-rating band matching the
    user's median ELO and 20% from each neighbouring band; at the elite and poor
    ends the missing neighbour clamps to the target band itself.
    """
    if median_elo is None:
        return [(None, session_size)]

    band_idx = _elo_to_band_index(int(median_elo))
    above_idx = max(0, band_idx - 1)
    below_idx = min(len(BANDS) - 1, band_idx + 1)
    side = session_size // 5
    return [
        (_community_rating_range(band_idx), session_size - 2 * side),
        (_community_rating_range(above_idx), side),
        (_community_rating_range(below_idx), side),
    ]


def _unknown_cards(user_id: uuid.UUID, media_type: MediaType) -> Select:
    """Films this user has not classified yet that have a poster."""
    return (
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
        .where(
            UserMovie.user_id == user_id,
            UserMovie.seen.is_(None),
            Movie.poster_url.isnot(None),
            Movie.media_type == media_type,
        )
    )


async def _median_elo(
    db: AsyncSession, user_id: uuid.UUID, media_type: MediaType
) -> float | None:
    stmt = (
        select(func.percentile_cont(0.5).within_group(UserMovie.elo))
        .join(Movie, UserMovie.movie_id == Movie.id)
        .where(
            UserMovie.user_id == user_id,
            UserMovie.elo.is_not(None),
            Movie.media_type == media_type,
        )
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _backfill(
    db: AsyncSession, base: Select, rows: list[Row], session_size: int
) -> list[Row]:
    """Top ``rows`` up to ``session_size`` with random unknown films not already chosen."""
    if len(rows) >= session_size:
        return rows
    stmt = base.order_by(func.random()).limit(session_size - len(rows))
    if rows:
        stmt = stmt.where(Movie.id.notin_([r.id for r in rows]))
    return rows + list((await db.execute(stmt)).all())


async def select_swipe_cards(
    db: AsyncSession, user_id: uuid.UUID, media_type: MediaType
) -> list[Row]:
    """Pick up to SESSION_SIZE unknown films, weighted towards the user's taste band."""
    median_elo = await _median_elo(db, user_id, media_type)
    # DEBUG, not INFO: user_id + preference data is behavioral personal data (SEC-15, #583).
    if median_elo is None:
        logger.debug("swipe_band_selection user_id=%s band=none (no ranked films)", user_id)
    else:
        logger.debug(
            "swipe_band_selection user_id=%s median_elo=%s band=%s",
            user_id,
            median_elo,
            BANDS[_elo_to_band_index(int(median_elo))][0],
        )

    base = _unknown_cards(user_id, media_type)
    rows: list[Row] = []
    for rating_range, limit in plan_card_mix(median_elo):
        if rating_range is None:
            in_range = Movie.community_rating.isnot(None)
        else:
            in_range = Movie.community_rating.between(*rating_range)
        stmt = base.where(in_range).order_by(func.random()).limit(limit)
        rows.extend((await db.execute(stmt)).all())

    # Clamped boundary bands repeat the target range, so parts can return the same film.
    rows = list({row.id: row for row in rows}.values())
    return await _backfill(db, base, rows, SESSION_SIZE)


@dataclass(frozen=True)
class SwipeTally:
    seen: int
    unseen: int
    skipped: int


async def count_unresolved(
    db: AsyncSession, user_id: uuid.UUID, movie_ids: set[uuid.UUID]
) -> int:
    """How many of these films are still unresolved, i.e. would get a swipe row."""
    stmt = select(func.count()).where(
        UserMovie.user_id == user_id,
        UserMovie.movie_id.in_(movie_ids),
        UserMovie.seen.is_(None),
    )
    return (await db.execute(stmt)).scalar_one()


async def record_swipes(
    db: AsyncSession, user_id: uuid.UUID, results: list[SwipeResultItem]
) -> SwipeTally:
    """Apply seen/unseen answers to the user's still-unresolved films."""
    now = datetime.now(timezone.utc)
    seen_count = unseen_count = skipped = 0

    # Collapse repeated movie_ids so one batch writes at most one row per movie.
    seen_by_movie = {item.movie_id: item.seen for item in results}

    for movie_id, seen in seen_by_movie.items():
        # Only unresolved rows are accepted (SEC-21, #589): a resolved movie is
        # skipped rather than rejected, because a duel or mark-seen in another tab
        # can legitimately resolve a served card before this batch lands, and the
        # counts in the response already make partial application visible.
        stmt = select(UserMovie).where(
            UserMovie.user_id == user_id,
            UserMovie.movie_id == movie_id,
            UserMovie.seen.is_(None),
        )
        um = (await db.execute(stmt)).scalar_one_or_none()
        if um is None:
            skipped += 1
            continue
        um.seen = seen
        um.updated_at = now
        db.add(SwipeResult(user_id=user_id, movie_id=movie_id, seen=seen))

        if seen:
            seen_count += 1
        else:
            unseen_count += 1

    return SwipeTally(seen=seen_count, unseen=unseen_count, skipped=skipped)


async def pool_needs_expansion(
    db: AsyncSession, user_id: uuid.UUID, media_type: MediaType
) -> bool:
    """True when fewer than POOL_EXPANSION_THRESHOLD films are left to classify."""
    stmt = (
        select(func.count())
        .select_from(UserMovie)
        .join(Movie, UserMovie.movie_id == Movie.id)
        .where(
            UserMovie.user_id == user_id,
            UserMovie.seen.is_(None),
            Movie.media_type == media_type,
        )
    )
    unknown_count = (await db.execute(stmt)).scalar() or 0
    if unknown_count >= POOL_EXPANSION_THRESHOLD:
        return False
    logger.info(
        "swipe_pool_low user_id=%s unknown_count=%d triggering_expansion",
        user_id,
        unknown_count,
    )
    return True
