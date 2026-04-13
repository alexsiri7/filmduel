"""Background pool expansion — fetch more movies/shows when the swipe pool runs low."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import sentry_sdk
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.db import async_session_factory
from backend.db_models import Movie, PoolExpansion, User, UserMovie
from backend.services.tmdb import backfill_posters, fetch_similar_films
from backend.services.trakt import TraktClient

logger = logging.getLogger(__name__)

EXPANSION_COOLDOWN = timedelta(days=7)
TARGET_ADDED = 100


async def expand_pool(user_id: uuid.UUID, media_type: str = "movie") -> int:
    """Expand a user's movie/show pool. Returns count of films added.

    Runs in a background task with its own DB session.
    """
    try:
        return await _expand_pool_inner(user_id, media_type)
    except Exception:
        logger.exception("Pool expansion failed for user %s", user_id)
        sentry_sdk.capture_exception()
        return 0


async def _expand_pool_inner(user_id: uuid.UUID, media_type: str = "movie") -> int:
    settings = get_settings()
    total_added = 0

    async with async_session_factory() as db:
        # Load user for Trakt credentials
        user = await db.get(User, user_id)
        if not user:
            logger.warning("expand_pool: user %s not found", user_id)
            return 0

        now = datetime.now(timezone.utc)
        cutoff = now - EXPANSION_COOLDOWN

        # Get recent expansion sources to skip
        recent_stmt = (
            select(PoolExpansion.source, PoolExpansion.source_key)
            .where(
                PoolExpansion.user_id == user_id,
                PoolExpansion.ran_at >= cutoff,
            )
        )
        result = await db.execute(recent_stmt)
        recent_keys: set[tuple[str, str | None]] = {
            (row.source, row.source_key) for row in result.all()
        }

        # Source A: Trakt personalized recommendations (highest quality)
        if total_added < TARGET_ADDED:
            added = await _expand_from_recommendations(
                db, user_id, user, settings, recent_keys, now, media_type
            )
            total_added += added

        # Source B: TMDB similar films from top-ranked items (movies only)
        if total_added < TARGET_ADDED and media_type == "movie":
            added = await _expand_from_similar(
                db, user_id, settings, recent_keys, now
            )
            total_added += added

        # Source C: Trakt anticipated
        if total_added < TARGET_ADDED and ("anticipated", media_type) not in recent_keys:
            added = await _expand_from_anticipated(
                db, user_id, user, settings, recent_keys, now, media_type
            )
            total_added += added

        # Source D: Deeper popular pages
        if total_added < TARGET_ADDED:
            added = await _expand_from_popular_pages(
                db, user_id, user, settings, recent_keys, now, media_type
            )
            total_added += added

        await db.commit()

    # Backfill poster URLs for newly added films (fresh session so commit is independent)
    if total_added > 0:
        async with async_session_factory() as poster_db:
            await backfill_posters(poster_db)

    logger.info(
        "Pool expansion complete for user %s: %d films added", user_id, total_added
    )
    return total_added


async def _expand_from_recommendations(
    db: AsyncSession,
    user_id: uuid.UUID,
    user: User,
    settings,
    recent_keys: set[tuple[str, str | None]],
    now: datetime,
    media_type: str = "movie",
) -> int:
    """Source A: Trakt personalized recommendations."""
    source_key = f"{media_type}_default"
    if ("trakt_recommendations", source_key) in recent_keys:
        return 0

    client = TraktClient(
        client_id=settings.TRAKT_CLIENT_ID,
        access_token=user.trakt_access_token,
    )
    try:
        if media_type == "show":
            recs = await client.get_recommendations_shows(limit=100)
        else:
            recs = await client.get_recommendations(limit=100)
    except Exception:
        logger.exception("Failed to fetch Trakt recommendations (%s)", media_type)
        return 0

    added = 0
    for item in recs:
        ok = await _upsert_film_from_trakt(db, user_id, item, now, media_type)
        if ok:
            added += 1

    db.add(PoolExpansion(
        user_id=user_id,
        source="trakt_recommendations",
        source_key=source_key,
        films_added=added,
        ran_at=now,
    ))
    await db.flush()
    return added


async def _expand_from_similar(
    db: AsyncSession,
    user_id: uuid.UUID,
    settings,
    recent_keys: set[tuple[str, str | None]],
    now: datetime,
) -> int:
    """Source A: TMDB recommendations from user's top-ranked films."""
    if not settings.TMDB_API_KEY:
        return 0

    # Get top 10 ranked films by ELO
    top_stmt = (
        select(UserMovie.movie_id, Movie.tmdb_id)
        .join(Movie, Movie.id == UserMovie.movie_id)
        .where(
            UserMovie.user_id == user_id,
            UserMovie.elo.isnot(None),
            Movie.tmdb_id.isnot(None),
        )
        .order_by(UserMovie.elo.desc())
        .limit(10)
    )
    result = await db.execute(top_stmt)
    top_movies = result.all()

    total = 0
    for row in top_movies:
        source_key = str(row.tmdb_id)
        if ("tmdb_similar", source_key) in recent_keys:
            continue

        recs = await fetch_similar_films(row.tmdb_id, settings.TMDB_API_KEY)
        added = 0
        for film in recs:
            ok = await _upsert_film_from_tmdb(db, user_id, film, settings)
            if ok:
                added += 1

        # Record expansion
        db.add(PoolExpansion(
            user_id=user_id,
            source="tmdb_similar",
            source_key=source_key,
            films_added=added,
            ran_at=now,
        ))
        total += added

        # Rate-limit TMDB calls
        await asyncio.sleep(0.3)

        if total >= TARGET_ADDED:
            break

    await db.flush()
    return total


async def _expand_from_anticipated(
    db: AsyncSession,
    user_id: uuid.UUID,
    user: User,
    settings,
    recent_keys: set[tuple[str, str | None]],
    now: datetime,
    media_type: str = "movie",
) -> int:
    """Source C: Trakt anticipated movies/shows."""
    client = TraktClient(
        client_id=settings.TRAKT_CLIENT_ID,
        access_token=user.trakt_access_token,
    )
    endpoint = "/shows/anticipated" if media_type == "show" else "/movies/anticipated"
    item_key = "show" if media_type == "show" else "movie"
    try:
        async with client._client() as http:
            resp = await http.get(
                endpoint,
                params={"limit": 100, "extended": "full"},
                timeout=15.0,
            )
            resp.raise_for_status()
            items = resp.json()
    except Exception:
        logger.exception("Failed to fetch anticipated %ss", media_type)
        return 0

    added = 0
    for item in items:
        data = item.get(item_key, item)
        ok = await _upsert_film_from_trakt(db, user_id, data, now, media_type)
        if ok:
            added += 1

    db.add(PoolExpansion(
        user_id=user_id,
        source="anticipated",
        source_key=media_type,
        films_added=added,
        ran_at=now,
    ))
    await db.flush()
    return added


async def _expand_from_popular_pages(
    db: AsyncSession,
    user_id: uuid.UUID,
    user: User,
    settings,
    recent_keys: set[tuple[str, str | None]],
    now: datetime,
    media_type: str = "movie",
) -> int:
    """Source D: Deeper pages of Trakt popular movies/shows."""
    client = TraktClient(
        client_id=settings.TRAKT_CLIENT_ID,
        access_token=user.trakt_access_token,
    )
    endpoint = "/shows/popular" if media_type == "show" else "/movies/popular"
    source = f"popular_page_N_{media_type}"
    total = 0
    for page in range(2, 6):
        source_key = str(page)
        if (source, source_key) in recent_keys:
            continue

        try:
            async with client._client() as http:
                resp = await http.get(
                    endpoint,
                    params={"page": page, "limit": 100, "extended": "full"},
                    timeout=15.0,
                )
                resp.raise_for_status()
                items = resp.json()
        except Exception:
            logger.exception("Failed to fetch popular %s page %d", media_type, page)
            continue

        added = 0
        for item_data in items:
            ok = await _upsert_film_from_trakt(db, user_id, item_data, now, media_type)
            if ok:
                added += 1

        db.add(PoolExpansion(
            user_id=user_id,
            source=source,
            source_key=source_key,
            films_added=added,
            ran_at=now,
        ))
        total += added

        if total >= TARGET_ADDED:
            break

    await db.flush()
    return total


async def _upsert_film_from_trakt(
    db: AsyncSession,
    user_id: uuid.UUID,
    movie_data: dict,
    now: datetime,
    media_type: str = "movie",
) -> bool:
    """Upsert a Trakt movie/show dict into movies + user_movies. Returns True if new user_movie created."""
    ids = movie_data.get("ids", {})
    trakt_id = ids.get("trakt")
    if not trakt_id:
        return False

    trakt_rating = movie_data.get("rating", 0)
    community_rating = round(trakt_rating * 10, 1) if trakt_rating else None

    stmt = insert(Movie.__table__).values(
        trakt_id=trakt_id,
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
    ).on_conflict_do_update(
        index_elements=["trakt_id", "media_type"],
        set_={
            "imdb_id": ids.get("imdb"),
            "tmdb_id": ids.get("tmdb"),
            "title": movie_data.get("title", "Unknown"),
            "year": movie_data.get("year"),
            "genres": movie_data.get("genres"),
            "overview": movie_data.get("overview"),
            "runtime": movie_data.get("runtime"),
            "community_rating": community_rating,
            "cached_at": now,
        },
    )
    await db.execute(stmt)
    await db.flush()

    result = await db.execute(
        select(Movie.id).where(Movie.trakt_id == trakt_id, Movie.media_type == media_type)
    )
    movie_uuid = result.scalar_one_or_none()
    if not movie_uuid:
        return False

    um_stmt = insert(UserMovie.__table__).values(
        user_id=user_id,
        movie_id=movie_uuid,
        seen=None,
        elo=None,
        battles=0,
        updated_at=now,
    ).on_conflict_do_nothing(
        index_elements=["user_id", "movie_id"],
    )
    result = await db.execute(um_stmt)
    return result.rowcount > 0


async def _upsert_film_from_tmdb(
    db: AsyncSession,
    user_id: uuid.UUID,
    film: dict,
    settings,
) -> bool:
    """Upsert a TMDB-sourced film. Looks up trakt_id via existing DB or Trakt search API."""
    tmdb_id = film.get("tmdb_id")
    if not tmdb_id:
        return False

    now = datetime.now(timezone.utc)

    # Check if we already have this movie by tmdb_id
    existing = await db.execute(
        select(Movie.id, Movie.trakt_id).where(Movie.tmdb_id == tmdb_id)
    )
    row = existing.first()

    if row:
        # Movie exists, just ensure user_movie
        um_stmt = insert(UserMovie.__table__).values(
            user_id=user_id,
            movie_id=row.id,
            seen=None,
            elo=None,
            battles=0,
            updated_at=now,
        ).on_conflict_do_nothing(
            index_elements=["user_id", "movie_id"],
        )
        result = await db.execute(um_stmt)
        return result.rowcount > 0

    # Need trakt_id — look up via Trakt search API
    trakt_id = await _lookup_trakt_id(tmdb_id, settings)
    if not trakt_id:
        return False

    # Upsert the movie (TMDB expansion is movies-only, so media_type="movie")
    stmt = insert(Movie.__table__).values(
        trakt_id=trakt_id,
        media_type="movie",
        tmdb_id=tmdb_id,
        title=film.get("title", "Unknown"),
        year=film.get("year"),
        genres=film.get("genres"),
        overview=film.get("overview"),
        cached_at=now,
    ).on_conflict_do_update(
        index_elements=["trakt_id", "media_type"],
        set_={
            "tmdb_id": tmdb_id,
            "title": film.get("title", "Unknown"),
            "year": film.get("year"),
            "genres": film.get("genres"),
            "overview": film.get("overview"),
            "cached_at": now,
        },
    )
    await db.execute(stmt)
    await db.flush()

    movie_result = await db.execute(
        select(Movie.id).where(Movie.trakt_id == trakt_id, Movie.media_type == "movie")
    )
    movie_uuid = movie_result.scalar_one_or_none()
    if not movie_uuid:
        return False

    um_stmt = insert(UserMovie.__table__).values(
        user_id=user_id,
        movie_id=movie_uuid,
        seen=None,
        elo=None,
        battles=0,
        updated_at=now,
    ).on_conflict_do_nothing(
        index_elements=["user_id", "movie_id"],
    )
    result = await db.execute(um_stmt)
    return result.rowcount > 0


async def _lookup_trakt_id(tmdb_id: int, settings) -> int | None:
    """Look up a Trakt movie ID from a TMDB ID using the Trakt search API."""
    try:
        async with httpx.AsyncClient(
            base_url="https://api.trakt.tv",
            headers={
                "Content-Type": "application/json",
                "trakt-api-version": "2",
                "trakt-api-key": settings.TRAKT_CLIENT_ID,
            },
        ) as client:
            resp = await client.get(
                f"/search/tmdb/{tmdb_id}",
                params={"type": "movie"},
                timeout=10.0,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            if data and len(data) > 0:
                movie = data[0].get("movie", {})
                return movie.get("ids", {}).get("trakt")
    except Exception:
        logger.warning("Trakt search failed for tmdb_id=%d", tmdb_id)
    return None
