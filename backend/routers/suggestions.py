"""Suggestions routes — AI-curated film recommendations."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from backend.config import get_settings
from backend.db import get_db
from backend.db_models import Suggestion, User, UserMovie
from backend.routers.auth import get_current_user
from backend.schemas import MovieSchema, SuggestionSchema, SuggestionsResponse
from backend.services.suggest import generate_suggestions, has_enough_ranked
from backend.services.trakt import TraktClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/suggestions", tags=["suggestions"])

STALE_HOURS = 24
MAX_REGENERATIONS_PER_DAY = 3


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
        ),
        reason=s.reason,
        generated_at=s.generated_at,
        dismissed_at=s.dismissed_at,
        added_to_watchlist_at=s.added_to_watchlist_at,
    )


async def _get_active_suggestions(
    user_id: uuid.UUID, db: AsyncSession
) -> list[Suggestion]:
    """Get non-dismissed suggestions for a user."""
    stmt = (
        select(Suggestion)
        .options(joinedload(Suggestion.movie))
        .where(
            Suggestion.user_id == user_id,
            Suggestion.dismissed_at.is_(None),
        )
        .order_by(Suggestion.generated_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.unique().scalars().all())


async def _create_suggestions(
    user_id: uuid.UUID, db: AsyncSession
) -> list[Suggestion]:
    """Generate new suggestions via AI and persist them."""
    picks = await generate_suggestions(user_id, db)
    if not picks:
        return []

    suggestions = []
    for pick in picks:
        s = Suggestion(
            user_id=user_id,
            movie_id=uuid.UUID(pick["movie_id"]),
            reason=pick["reason"],
            generated_at=datetime.now(timezone.utc),
        )
        db.add(s)
        suggestions.append(s)

    await db.flush()

    # Reload with movie relationships
    return await _get_active_suggestions(user_id, db)


@router.get("", response_model=SuggestionsResponse)
async def get_suggestions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return current suggestions. Generate if stale (>24h) or missing."""
    uid = current_user.id

    # Check if user has enough ranked films
    if not await has_enough_ranked(uid, db):
        return SuggestionsResponse(suggestions=[], status="not_enough_films")

    # Check existing non-dismissed suggestions
    active = await _get_active_suggestions(uid, db)

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
        new_suggestions = await _create_suggestions(uid, db)
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
async def regenerate_suggestions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Force regeneration. Rate-limited: 3 per day."""
    uid = current_user.id

    if not await has_enough_ranked(uid, db):
        return SuggestionsResponse(suggestions=[], status="not_enough_films")

    # Count regenerations in last 24h (by counting distinct generated_at timestamps)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    count_stmt = (
        select(func.count(func.distinct(Suggestion.generated_at)))
        .where(
            Suggestion.user_id == uid,
            Suggestion.generated_at > cutoff,
        )
    )
    result = await db.execute(count_stmt)
    regen_count = result.scalar() or 0

    if regen_count >= MAX_REGENERATIONS_PER_DAY:
        raise HTTPException(
            status_code=429,
            detail="You can regenerate suggestions up to 3 times per day.",
        )

    # Dismiss all existing suggestions
    active = await _get_active_suggestions(uid, db)
    now = datetime.now(timezone.utc)
    for s in active:
        s.dismissed_at = now

    try:
        new_suggestions = await _create_suggestions(uid, db)
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
async def dismiss_suggestion(
    suggestion_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark suggestion as dismissed."""
    stmt = (
        select(Suggestion)
        .options(joinedload(Suggestion.movie))
        .where(
            Suggestion.id == uuid.UUID(suggestion_id),
            Suggestion.user_id == current_user.id,
        )
    )
    result = await db.execute(stmt)
    suggestion = result.unique().scalar_one_or_none()

    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    suggestion.dismissed_at = datetime.now(timezone.utc)
    return _build_suggestion_schema(suggestion)


@router.post("/{suggestion_id}/watchlist", response_model=SuggestionSchema)
async def add_to_watchlist(
    suggestion_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark suggestion as added to watchlist and sync to Trakt."""
    stmt = (
        select(Suggestion)
        .options(joinedload(Suggestion.movie))
        .where(
            Suggestion.id == uuid.UUID(suggestion_id),
            Suggestion.user_id == current_user.id,
        )
    )
    result = await db.execute(stmt)
    suggestion = result.unique().scalar_one_or_none()

    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    suggestion.added_to_watchlist_at = datetime.now(timezone.utc)

    # Sync to Trakt watchlist in background
    trakt_id = suggestion.movie.trakt_id
    access_token = current_user.trakt_access_token
    settings = get_settings()

    async def _sync_trakt_watchlist():
        try:
            client = TraktClient(client_id=settings.TRAKT_CLIENT_ID, access_token=access_token)
            await client.add_to_watchlist(trakt_id)
        except Exception:
            logger.exception("Failed to sync watchlist to Trakt for movie %s", trakt_id)

    background_tasks.add_task(_sync_trakt_watchlist)

    return _build_suggestion_schema(suggestion)


@router.post("/{suggestion_id}/seen", response_model=SuggestionSchema)
async def mark_seen(
    suggestion_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark the suggested film as seen and dismiss the suggestion."""
    uid = current_user.id
    stmt = (
        select(Suggestion)
        .options(joinedload(Suggestion.movie))
        .where(
            Suggestion.id == uuid.UUID(suggestion_id),
            Suggestion.user_id == uid,
        )
    )
    result = await db.execute(stmt)
    suggestion = result.unique().scalar_one_or_none()

    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")

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
