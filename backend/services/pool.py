"""Movie pool import — fetches movies from Trakt and populates the local DB."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.db_models import Movie, User, UserMovie
from backend.services.elo import trakt_rating_to_seeded_elo
from backend.services.trakt import TraktClient

logger = logging.getLogger(__name__)

SYNC_COOLDOWN = timedelta(hours=1)


def build_movie_upsert(movie_data: dict, now: datetime, media_type: str = "movie"):
    """Build a PostgreSQL INSERT...ON CONFLICT upsert for a Trakt movie dict."""
    ids = movie_data.get("ids", {})
    trakt_rating = movie_data.get("rating", 0)
    community_rating = round(trakt_rating * 10, 1) if trakt_rating else None
    values = dict(
        trakt_id=ids["trakt"],
        media_type=media_type,
        imdb_id=ids.get("imdb"),
        tmdb_id=ids.get("tmdb"),
        title=movie_data.get("title", "Unknown"),
        year=movie_data.get("year"),
        genres=movie_data.get("genres"),
        overview=movie_data.get("overview"),
        runtime=movie_data.get("runtime"),
        community_rating=community_rating,
        cached_at=now,
    )
    update_set = {k: v for k, v in values.items() if k not in ("trakt_id", "media_type")}
    stmt = insert(Movie.__table__).values(**values).on_conflict_do_update(
        index_elements=["trakt_id", "media_type"],
        set_=update_set,
    )
    return stmt


async def _safe_fetch(coro_func, *args, **kwargs) -> list:
    """Call an async function, returning [] on failure."""
    try:
        return await coro_func(*args, **kwargs)
    except Exception:
        logger.exception("Failed to fetch from Trakt: %s", coro_func.__name__)
        return []


async def populate_movie_pool(user: User, db: AsyncSession) -> None:
    """Fetch movies and shows from Trakt and populate the user's pool.

    Called on login/session start. Throttled to once per hour.
    """
    now = datetime.now(timezone.utc)
    last_seen = user.last_seen_at
    if last_seen and last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    if last_seen and (now - last_seen) < SYNC_COOLDOWN:
        logger.info("Skipping pool sync for %s — synced recently", user.trakt_username)
        return

    settings = get_settings()
    client = TraktClient(
        client_id=settings.TRAKT_CLIENT_ID,
        access_token=user.trakt_access_token,
    )

    for media_type in ("movie", "show"):
        popular = await _safe_fetch(client.get_popular, limit=100, media_type=media_type)
        trending = await _safe_fetch(client.get_trending, limit=100, media_type=media_type)
        recommended = await _safe_fetch(client.get_recommendations, limit=100, media_type=media_type)
        watched = await _safe_fetch(client.get_user_watched, user.trakt_user_id, media_type=media_type)
        ratings_list = await _safe_fetch(client.get_user_ratings, user.trakt_user_id, media_type=media_type)

        ratings_by_trakt_id: dict[int, int] = {
            r["trakt_id"]: r["rating"] for r in ratings_list
        }

        pool: dict[int, dict] = {}
        seen_trakt_ids: set[int] = set()

        for item in popular + trending + recommended:
            trakt_id = item["ids"]["trakt"]
            if trakt_id not in pool:
                pool[trakt_id] = item

        for item in watched:
            trakt_id = item["ids"]["trakt"]
            seen_trakt_ids.add(trakt_id)
            if trakt_id not in pool:
                pool[trakt_id] = item

        await _upsert_pool(db, user, pool, seen_trakt_ids, ratings_by_trakt_id, media_type, now)

    # Update last_seen_at
    user.last_seen_at = now
    await db.flush()

    logger.info(
        "Pool sync complete for %s",
        user.trakt_username,
    )


async def _upsert_pool(
    db: AsyncSession,
    user: User,
    pool: dict[int, dict],
    seen_trakt_ids: set[int],
    ratings_by_trakt_id: dict[int, int],
    media_type: str,
    now: datetime,
) -> None:
    """Upsert a pool of movies or shows into the DB."""
    if not pool:
        return

    # Upsert movies/shows into the movies table
    for item_data in pool.values():
        stmt = build_movie_upsert(item_data, now, media_type)
        await db.execute(stmt)

    await db.flush()

    trakt_ids = list(pool.keys())
    result = await db.execute(
        select(Movie.id, Movie.trakt_id).where(
            Movie.trakt_id.in_(trakt_ids),
            Movie.media_type == media_type,
        )
    )
    uuid_map: dict[int, str] = {row.trakt_id: row.id for row in result.all()}

    for trakt_id, item_data in pool.items():
        movie_uuid = uuid_map.get(trakt_id)
        if not movie_uuid:
            continue

        seen = True if trakt_id in seen_trakt_ids else None
        rating = ratings_by_trakt_id.get(trakt_id)
        seeded_elo = trakt_rating_to_seeded_elo(rating) if rating is not None else None

        stmt = insert(UserMovie.__table__).values(
            user_id=user.id,
            movie_id=movie_uuid,
            seen=seen,
            elo=None,
            seeded_elo=seeded_elo,
            battles=0,
            trakt_rating=rating,
            updated_at=now,
        ).on_conflict_do_update(
            index_elements=["user_id", "movie_id"],
            set_={
                "seen": seen if seen is True else UserMovie.__table__.c.seen,
                "seeded_elo": seeded_elo
                if seeded_elo is not None
                else UserMovie.__table__.c.seeded_elo,
                "trakt_rating": rating
                if rating is not None
                else UserMovie.__table__.c.trakt_rating,
                "updated_at": now,
            },
        )
        await db.execute(stmt)

    await db.flush()
