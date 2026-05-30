"""Suggestions routes — AI-curated film recommendations."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from backend.config import get_settings
from backend.db import async_session_factory, get_db
from backend.rate_limit import limiter
from backend.db_models import Movie, Suggestion, User, UserMovie
from backend.routers.auth import ensure_fresh_token, get_current_user
from backend.schemas import (
    MediaType,
    MovieSchema,
    SuggestionSchema,
    SuggestionsResponse,
)
from backend.services.suggest import generate_suggestions, has_enough_ranked
from backend.services.trakt import TraktClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/suggestions", tags=["suggestions"])

STALE_HOURS = 24
MAX_REGENERATIONS_PER_DAY = 3


async def _get_user_suggestion(
    db: AsyncSession, suggestion_id: str, user_id: uuid.UUID
) -> Suggestion:
    try:
        sid = uuid.UUID(suggestion_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid suggestion ID")
    stmt = (
        select(Suggestion)
        .options(joinedload(Suggestion.movie))
        .where(
            Suggestion.id == sid,
            Suggestion.user_id == user_id,
        )
    )
    result = await db.execute(stmt)
    suggestion = result.unique().scalar_one_or_none()
    if suggestion is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    return suggestion


def _build_suggestion_schema(s: Suggestion) -> SuggestionSchema:
    m = s.movie
    return SuggestionSchema(
        id=str(s.id),
        movie=MovieSchema(
            id=str(m.id),
            trakt_id=m.trakt_id,
            tmdb_id=m.tmdb_id,
            imdb_id=m.imdb_id,
            title=m.title,
            year=m.year,
            poster_url=m.poster_url,
            overview=m.overview,
            media_type=m.media_type,
        ),
        reason=s.reason,
        generated_at=s.generated_at,
        dismissed_at=s.dismissed_at,
        added_to_watchlist_at=s.added_to_watchlist_at,
    )


async def _get_active_suggestions(
    user_id: uuid.UUID, db: AsyncSession, media_type: str = "movie"
) -> list[Suggestion]:
    """Get non-dismissed suggestions for a user, filtered by media_type."""
    stmt = (
        select(Suggestion)
        .options(joinedload(Suggestion.movie))
        .join(Suggestion.movie)
        .where(
            Suggestion.user_id == user_id,
            Suggestion.dismissed_at.is_(None),
            Movie.poster_url.isnot(None),
            Movie.media_type == media_type,
        )
        .order_by(Suggestion.generated_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.unique().scalars().all())


async def _create_suggestions(
    user_id: uuid.UUID, db: AsyncSession, media_type: str = "movie"
) -> list[Suggestion]:
    """Generate new suggestions via AI and persist them."""
    picks = await generate_suggestions(user_id, db, media_type=media_type)
    if not picks:
        return []

    suggestions = []
    for pick in picks:
        try:
            movie_id = uuid.UUID(pick["movie_id"])
        except ValueError:
            logger.warning(
                "AI returned malformed movie_id: %s — skipping", pick.get("movie_id")
            )
            continue
        s = Suggestion(
            user_id=user_id,
            movie_id=movie_id,
            reason=pick["reason"],
            generated_at=datetime.now(timezone.utc),
        )
        db.add(s)
        suggestions.append(s)

    await db.flush()

    # Reload with movie relationships
    return await _get_active_suggestions(user_id, db, media_type)


def _require_consent(user: User) -> None:
    if not user.privacy_policy_accepted:
        raise HTTPException(
            status_code=403,
            detail="Privacy policy consent required to use AI suggestions",
        )


@router.get("", response_model=SuggestionsResponse)
@limiter.limit("10/minute")
async def get_suggestions(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    media_type: MediaType = Query(default="movie"),
):
    """Return current suggestions. Generate if stale (>24h) or missing."""
    uid = current_user.id

    _require_consent(current_user)

    # Check if user has enough ranked films
    if not await has_enough_ranked(uid, db, media_type=media_type):
        return SuggestionsResponse(suggestions=[], status="not_enough_films")

    # Check existing non-dismissed suggestions
    active = await _get_active_suggestions(uid, db, media_type)

    if active:
        # Check freshness
        newest = max(s.generated_at for s in active)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=STALE_HOURS)
        if newest > cutoff:
            return SuggestionsResponse(
                suggestions=[_build_suggestion_schema(s) for s in active],
                status="ready",
            )

    # Stale or none — generate new
    try:
        new_suggestions = await _create_suggestions(uid, db, media_type)
        if not new_suggestions:
            return SuggestionsResponse(suggestions=[], status="no_candidates")
        return SuggestionsResponse(
            suggestions=[_build_suggestion_schema(s) for s in new_suggestions],
            status="ready",
        )
    except ValueError as e:
        # LLM_API_KEY not configured
        raise HTTPException(status_code=503, detail=str(e))
    except Exception:
        logger.exception("Failed to generate suggestions for user %s", uid)
        raise HTTPException(
            status_code=500,
            detail="Failed to generate suggestions. Please try again later.",
        )


@router.post("/regenerate", response_model=SuggestionsResponse)
@limiter.limit("3/day")
async def regenerate_suggestions(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    media_type: MediaType = Query(default="movie"),
):
    """Force regeneration. Rate-limited: 3 per day."""
    uid = current_user.id

    _require_consent(current_user)

    if not await has_enough_ranked(uid, db, media_type=media_type):
        return SuggestionsResponse(suggestions=[], status="not_enough_films")

    # Count regenerations in last 24h (by counting distinct generated_at timestamps)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    count_stmt = select(func.count(func.distinct(Suggestion.generated_at))).where(
        Suggestion.user_id == uid,
        Suggestion.generated_at > cutoff,
    )
    result = await db.execute(count_stmt)
    regen_count = result.scalar() or 0

    if regen_count >= MAX_REGENERATIONS_PER_DAY:
        raise HTTPException(
            status_code=429,
            detail="You can regenerate suggestions up to 3 times per day.",
        )

    # Dismiss all existing suggestions
    active = await _get_active_suggestions(uid, db, media_type)
    now = datetime.now(timezone.utc)
    for s in active:
        s.dismissed_at = now

    try:
        new_suggestions = await _create_suggestions(uid, db, media_type)
        if not new_suggestions:
            return SuggestionsResponse(suggestions=[], status="not_enough_films")
        return SuggestionsResponse(
            suggestions=[_build_suggestion_schema(s) for s in new_suggestions],
            status="ready",
        )
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception:
        logger.exception("Failed to regenerate suggestions for user %s", uid)
        raise HTTPException(
            status_code=500,
            detail="Failed to generate suggestions. Please try again later.",
        )


@router.post("/{suggestion_id}/dismiss", response_model=SuggestionSchema)
@limiter.limit("60/minute")
async def dismiss_suggestion(
    request: Request,
    suggestion_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark suggestion as dismissed."""
    suggestion = await _get_user_suggestion(db, suggestion_id, current_user.id)

    suggestion.dismissed_at = datetime.now(timezone.utc)
    return _build_suggestion_schema(suggestion)


@router.post("/{suggestion_id}/watchlist", response_model=SuggestionSchema)
@limiter.limit("30/minute")
async def add_to_watchlist(
    request: Request,
    suggestion_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark suggestion as added to watchlist and sync to Trakt."""
    suggestion = await _get_user_suggestion(db, suggestion_id, current_user.id)

    suggestion.added_to_watchlist_at = datetime.now(timezone.utc)

    # Sync to Trakt watchlist in background
    trakt_id = suggestion.movie.trakt_id
    user_id = current_user.id
    settings = get_settings()

    async def _sync_trakt_watchlist():
        try:
            async with async_session_factory() as session:
                result = await session.execute(select(User).where(User.id == user_id))
                user = result.scalar_one_or_none()
                if not user or not user.trakt_access_token:
                    return
                user = await ensure_fresh_token(user, session)
                await session.commit()
                access_token = user.trakt_access_token
            client = TraktClient(
                client_id=settings.TRAKT_CLIENT_ID, access_token=access_token
            )
            await client.add_to_watchlist(trakt_id)
        except Exception:
            logger.exception("Failed to sync watchlist to Trakt for movie %s", trakt_id)

    background_tasks.add_task(_sync_trakt_watchlist)

    return _build_suggestion_schema(suggestion)


@router.post("/{suggestion_id}/seen", response_model=SuggestionSchema)
@limiter.limit("60/minute")
async def mark_seen(
    request: Request,
    suggestion_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark the suggested film as seen and dismiss the suggestion."""
    uid = current_user.id
    suggestion = await _get_user_suggestion(db, suggestion_id, uid)

    # Update user_movies.seen = true
    um_stmt = select(UserMovie).where(
        UserMovie.user_id == uid,
        UserMovie.movie_id == suggestion.movie_id,
    )
    um = (await db.execute(um_stmt)).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if um:
        um.seen = True
        um.updated_at = now
    else:
        # Create user_movie if it doesn't exist
        um = UserMovie(user_id=uid, movie_id=suggestion.movie_id, seen=True)
        db.add(um)

    suggestion.dismissed_at = now
    return _build_suggestion_schema(suggestion)
