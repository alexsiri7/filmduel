"""Movie pool import — fetches movies from Trakt and populates the local DB."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update as sa_update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import async_session_factory
from backend.config import get_settings
from backend.db_models import Movie, User, UserMovie
from backend.services.elo import trakt_rating_to_seeded_elo
from backend.services.trakt import TraktClient
from backend.services.simkl import SimklClient

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
    update_set = {
        k: v for k, v in values.items() if k not in ("trakt_id", "media_type")
    }
    stmt = (
        insert(Movie.__table__)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["trakt_id", "media_type"],
            set_=update_set,
        )
    )
    return stmt


def build_simkl_movie_upsert(
    movie_data: dict, now: datetime, media_type: str = "movie"
):
    """Build a PostgreSQL INSERT...ON CONFLICT upsert for a SIMKL movie dict.

    Stores the SIMKL ID in both the trakt_id column (for compatibility) and
    the dedicated simkl_id column. Callers are responsible for imdb_id
    cross-reference deduplication before calling this.
    """
    ids = movie_data.get("ids", {})
    # SIMKL uses its own numeric ID; store in trakt_id column for now
    simkl_id = ids.get("simkl", 0)
    values = dict(
        trakt_id=simkl_id,
        simkl_id=simkl_id,
        media_type=media_type,
        imdb_id=ids.get("imdb"),
        tmdb_id=ids.get("tmdb"),
        title=movie_data.get("title", "Unknown"),
        year=movie_data.get("year"),
        genres=movie_data.get("genres"),
        overview=movie_data.get("overview"),
        runtime=movie_data.get("runtime"),
        community_rating=None,
        cached_at=now,
    )
    update_set = {
        k: v for k, v in values.items() if k not in ("trakt_id", "media_type")
    }
    stmt = (
        insert(Movie.__table__)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["trakt_id", "media_type"],
            set_=update_set,
        )
    )
    return stmt


async def _safe_fetch(coro_func, *args, **kwargs) -> list:
    """Call an async function, returning [] on failure."""
    try:
        return await coro_func(*args, **kwargs)
    except Exception:
        logger.exception("Failed to fetch: %s", coro_func.__name__)
        return []


async def _fetch_trakt_pool(
    user: User, settings, media_type: str
) -> tuple[dict[int, dict], set[int], dict[int, int]]:
    """Fetch pool data from Trakt for a given media type."""
    client = TraktClient(
        client_id=settings.TRAKT_CLIENT_ID,
        access_token=user.trakt_access_token,
    )

    popular = await _safe_fetch(
        client.get_popular, limit=100, media_type=media_type
    )
    trending = await _safe_fetch(
        client.get_trending, limit=100, media_type=media_type
    )
    recommended = await _safe_fetch(
        client.get_recommendations, limit=100, media_type=media_type
    )
    watched = await _safe_fetch(
        client.get_user_watched, user.trakt_user_id, media_type=media_type
    )
    ratings_list = await _safe_fetch(
        client.get_user_ratings, user.trakt_user_id, media_type=media_type
    )

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

    return pool, seen_trakt_ids, ratings_by_trakt_id


async def _fetch_simkl_pool(
    user: User, settings, media_type: str
) -> tuple[dict[int, dict], set[int], dict[int, int]]:
    """Fetch pool data from SIMKL for a given media type."""
    client = SimklClient(
        client_id=settings.SIMKL_CLIENT_ID,
        access_token=user.simkl_access_token,
    )

    popular = await _safe_fetch(
        client.get_popular, limit=100, media_type=media_type
    )
    trending = await _safe_fetch(
        client.get_trending, limit=100, media_type=media_type
    )
    watched = await _safe_fetch(
        client.get_user_watched, media_type=media_type
    )
    ratings_list = await _safe_fetch(
        client.get_user_ratings, media_type=media_type
    )

    ratings_by_id: dict[int, int] = {
        r["simkl_id"]: r["rating"] for r in ratings_list
    }

    pool: dict[int, dict] = {}
    seen_ids: set[int] = set()

    for item in popular + trending:
        simkl_id = item.get("ids", {}).get("simkl", 0)
        if simkl_id and simkl_id not in pool:
            pool[simkl_id] = item

    for item in watched:
        simkl_id = item.get("ids", {}).get("simkl", 0)
        if simkl_id:
            seen_ids.add(simkl_id)
            if simkl_id not in pool:
                pool[simkl_id] = item

    return pool, seen_ids, ratings_by_id


async def populate_movie_pool(user: User, db: AsyncSession) -> None:
    """Fetch movies and shows from Trakt/SIMKL and populate the user's pool.

    Called on login/session start. Throttled to once per hour.
    """
    now = datetime.now(timezone.utc)
    last_seen = user.last_seen_at
    if last_seen and last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    if last_seen and (now - last_seen) < SYNC_COOLDOWN:
        logger.info("Skipping pool sync user_id=%s — synced recently", user.id)
        return

    settings = get_settings()
    has_trakt = bool(user.trakt_user_id and user.trakt_access_token_enc)
    has_simkl = bool(user.simkl_user_id and user.simkl_access_token_enc)

    for media_type in ("movie", "show"):
        if has_trakt:
            pool, seen_trakt_ids, ratings_by_trakt_id = await _fetch_trakt_pool(
                user, settings, media_type
            )
            await _upsert_pool(
                db, user, pool, seen_trakt_ids, ratings_by_trakt_id, media_type, now
            )

        if has_simkl:
            pool, seen_ids, ratings_by_id = await _fetch_simkl_pool(
                user, settings, media_type
            )
            await _upsert_simkl_pool(
                db, user, pool, seen_ids, ratings_by_id, media_type, now
            )

    # Update last_seen_at
    user.last_seen_at = now
    await db.flush()

    logger.info(
        "Pool sync complete user_id=%s",
        user.id,
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

        stmt = (
            insert(UserMovie.__table__)
            .values(
                user_id=user.id,
                movie_id=movie_uuid,
                seen=seen,
                elo=None,
                seeded_elo=seeded_elo,
                battles=0,
                trakt_rating=rating,
                updated_at=now,
            )
            .on_conflict_do_update(
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
        )
        await db.execute(stmt)

    await db.flush()


async def _upsert_simkl_pool(
    db: AsyncSession,
    user: User,
    pool: dict[int, dict],
    seen_ids: set[int],
    ratings_by_id: dict[int, int],
    media_type: str,
    now: datetime,
) -> None:
    """Upsert a pool of SIMKL movies or shows into the DB.

    Uses IMDB cross-reference where possible to avoid duplicates with
    Trakt-sourced movies.
    """
    if not pool:
        return

    # First pass: check for existing movies by imdb_id to avoid duplicates
    imdb_to_simkl: dict[str, int] = {}
    for simkl_id, item_data in pool.items():
        imdb_id = item_data.get("ids", {}).get("imdb")
        if imdb_id:
            imdb_to_simkl[imdb_id] = simkl_id

    # Find existing movies by imdb_id
    existing_by_imdb: dict[str, tuple] = {}
    if imdb_to_simkl:
        result = await db.execute(
            select(Movie.id, Movie.trakt_id, Movie.imdb_id).where(
                Movie.imdb_id.in_(list(imdb_to_simkl.keys())),
                Movie.media_type == media_type,
            )
        )
        for row in result.all():
            existing_by_imdb[row.imdb_id] = (row.id, row.trakt_id)

    # Upsert movies — skip those already in DB via imdb cross-ref
    simkl_id_to_movie_uuid: dict[int, uuid.UUID] = {}
    for simkl_id, item_data in pool.items():
        imdb_id = item_data.get("ids", {}).get("imdb")
        if imdb_id and imdb_id in existing_by_imdb:
            # Movie already exists (from Trakt or prior import) — record the SIMKL ID
            movie_uuid = existing_by_imdb[imdb_id][0]
            simkl_id_to_movie_uuid[simkl_id] = movie_uuid
            # Persist the simkl_id on the matched movie row if not set
            await db.execute(
                sa_update(Movie.__table__)
                .where(Movie.__table__.c.id == movie_uuid)
                .values(simkl_id=simkl_id)
            )
            continue

        # New movie — insert using SIMKL ID in trakt_id column
        stmt = build_simkl_movie_upsert(item_data, now, media_type)
        await db.execute(stmt)

    await db.flush()

    # Map remaining SIMKL IDs to movie UUIDs
    remaining_ids = [sid for sid in pool if sid not in simkl_id_to_movie_uuid]
    if remaining_ids:
        result = await db.execute(
            select(Movie.id, Movie.trakt_id).where(
                Movie.trakt_id.in_(remaining_ids),
                Movie.media_type == media_type,
            )
        )
        for row in result.all():
            simkl_id_to_movie_uuid[row.trakt_id] = row.id

    # Upsert user_movies
    for simkl_id in pool:
        movie_uuid = simkl_id_to_movie_uuid.get(simkl_id)
        if not movie_uuid:
            continue

        seen = True if simkl_id in seen_ids else None
        rating = ratings_by_id.get(simkl_id)
        seeded_elo = trakt_rating_to_seeded_elo(rating) if rating is not None else None

        stmt = (
            insert(UserMovie.__table__)
            .values(
                user_id=user.id,
                movie_id=movie_uuid,
                seen=seen,
                elo=None,
                seeded_elo=seeded_elo,
                battles=0,
                trakt_rating=rating,  # column reused for provider-agnostic rating (rename deferred)
                updated_at=now,
            )
            .on_conflict_do_update(
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
        )
        await db.execute(stmt)

    await db.flush()


async def sync_pool_background(user_id, force: bool = False) -> None:
    """Run pool sync in a background task with its own DB session."""
    try:
        async with async_session_factory() as session:
            user = await session.get(User, user_id)
            if user:
                if force:
                    user.last_seen_at = datetime.now(timezone.utc) - timedelta(hours=2)
                    await session.flush()
                await populate_movie_pool(user, session)
                await session.commit()
    except Exception:
        logger.exception("Background pool sync failed for user %s", user_id)
