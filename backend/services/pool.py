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

    # ── Movies ──────────────────────────────────────────────────────
    try:
        popular = await client.get_popular(limit=100)
    except Exception:
        logger.exception("Failed to fetch popular movies")
        popular = []
    try:
        trending = await client.get_trending(limit=100)
    except Exception:
        logger.exception("Failed to fetch trending movies")
        trending = []
    try:
        recommended = await client.get_recommendations(limit=100)
    except Exception:
        logger.exception("Failed to fetch recommendations")
        recommended = []
    try:
        watched = await client.get_user_watched(user.trakt_user_id)
    except Exception:
        logger.exception("Failed to fetch watch history for %s", user.trakt_user_id)
        watched = []
    try:
        ratings_list = await client.get_user_ratings(user.trakt_user_id)
    except Exception:
        logger.exception("Failed to fetch ratings for %s", user.trakt_user_id)
        ratings_list = []

    ratings_by_trakt_id: dict[int, int] = {
        r["trakt_id"]: r["rating"] for r in ratings_list
    }

    movie_pool: dict[int, dict] = {}
    seen_trakt_ids: set[int] = set()

    for movie in popular + trending + recommended:
        trakt_id = movie["ids"]["trakt"]
        if trakt_id not in movie_pool:
            movie_pool[trakt_id] = movie

    for movie in watched:
        trakt_id = movie["ids"]["trakt"]
        seen_trakt_ids.add(trakt_id)
        if trakt_id not in movie_pool:
            movie_pool[trakt_id] = movie

    await _upsert_pool(db, user, movie_pool, seen_trakt_ids, ratings_by_trakt_id, "movie", now)

    # ── TV Shows ────────────────────────────────────────────────────
    try:
        popular_shows = await client.get_popular_shows(limit=100)
    except Exception:
        logger.exception("Failed to fetch popular shows")
        popular_shows = []
    try:
        trending_shows = await client.get_trending_shows(limit=100)
    except Exception:
        logger.exception("Failed to fetch trending shows")
        trending_shows = []
    try:
        recommended_shows = await client.get_recommendations_shows(limit=100)
    except Exception:
        logger.exception("Failed to fetch show recommendations")
        recommended_shows = []
    try:
        watched_shows = await client.get_user_watched_shows(user.trakt_user_id)
    except Exception:
        logger.exception("Failed to fetch watched shows for %s", user.trakt_user_id)
        watched_shows = []
    try:
        show_ratings_list = await client.get_user_ratings_shows(user.trakt_user_id)
    except Exception:
        logger.exception("Failed to fetch show ratings for %s", user.trakt_user_id)
        show_ratings_list = []

    show_ratings_by_trakt_id: dict[int, int] = {
        r["trakt_id"]: r["rating"] for r in show_ratings_list
    }

    show_pool: dict[int, dict] = {}
    seen_show_trakt_ids: set[int] = set()

    for show in popular_shows + trending_shows + recommended_shows:
        trakt_id = show["ids"]["trakt"]
        if trakt_id not in show_pool:
            show_pool[trakt_id] = show

    for show in watched_shows:
        trakt_id = show["ids"]["trakt"]
        seen_show_trakt_ids.add(trakt_id)
        if trakt_id not in show_pool:
            show_pool[trakt_id] = show

    await _upsert_pool(db, user, show_pool, seen_show_trakt_ids, show_ratings_by_trakt_id, "show", now)

    # Update last_seen_at
    user.last_seen_at = now
    await db.flush()

    logger.info(
        "Pool sync complete for %s: %d movies + %d shows imported",
        user.trakt_username,
        len(movie_pool),
        len(show_pool),
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
