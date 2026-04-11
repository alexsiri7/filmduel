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


async def populate_movie_pool(user: User, db: AsyncSession) -> None:
    """Fetch movies from Trakt and populate the user's movie pool.

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

    # Fetch all sources concurrently-ish (serial to respect Trakt rate limits)
    popular = await client.get_popular(limit=100)
    trending = await client.get_trending(limit=100)
    watched = await client.get_user_watched(user.trakt_username)
    ratings_list = await client.get_user_ratings(user.trakt_username)

    # Build ratings lookup: trakt_id -> rating (1-10)
    ratings_by_trakt_id: dict[int, int] = {
        r["trakt_id"]: r["rating"] for r in ratings_list
    }

    # Collect all unique movies, tracking their source
    # movie_data keyed by trakt_id -> (movie_dict, seen)
    movie_pool: dict[int, dict] = {}
    seen_trakt_ids: set[int] = set()

    for movie in popular + trending:
        trakt_id = movie["ids"]["trakt"]
        if trakt_id not in movie_pool:
            movie_pool[trakt_id] = movie

    for movie in watched:
        trakt_id = movie["ids"]["trakt"]
        seen_trakt_ids.add(trakt_id)
        if trakt_id not in movie_pool:
            movie_pool[trakt_id] = movie

    if not movie_pool:
        logger.info("No movies fetched for %s", user.trakt_username)
        return

    # Upsert movies into the movies table
    for movie_data in movie_pool.values():
        ids = movie_data.get("ids", {})
        stmt = insert(Movie.__table__).values(
            trakt_id=ids["trakt"],
            imdb_id=ids.get("imdb"),
            tmdb_id=ids.get("tmdb"),
            title=movie_data.get("title", "Unknown"),
            year=movie_data.get("year"),
            genres=movie_data.get("genres"),
            overview=movie_data.get("overview"),
            runtime=movie_data.get("runtime"),
            cached_at=now,
        ).on_conflict_do_update(
            index_elements=["trakt_id"],
            set_={
                "imdb_id": ids.get("imdb"),
                "tmdb_id": ids.get("tmdb"),
                "title": movie_data.get("title", "Unknown"),
                "year": movie_data.get("year"),
                "genres": movie_data.get("genres"),
                "overview": movie_data.get("overview"),
                "runtime": movie_data.get("runtime"),
                "cached_at": now,
            },
        )
        await db.execute(stmt)

    await db.flush()

    # Fetch all movie rows we just upserted to get their UUIDs
    trakt_ids = list(movie_pool.keys())
    result = await db.execute(
        select(Movie.id, Movie.trakt_id).where(Movie.trakt_id.in_(trakt_ids))
    )
    movie_uuid_map: dict[int, str] = {row.trakt_id: row.id for row in result.all()}

    # Upsert user_movies
    for trakt_id, movie_data in movie_pool.items():
        movie_uuid = movie_uuid_map.get(trakt_id)
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
                # Update seen if we now know they watched it
                "seen": seen if seen is True else UserMovie.__table__.c.seen,
                # Update seeded_elo and rating if we have new data
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

    # Update last_seen_at
    user.last_seen_at = now
    await db.flush()

    logger.info(
        "Pool sync complete for %s: %d movies imported",
        user.trakt_username,
        len(movie_pool),
    )
