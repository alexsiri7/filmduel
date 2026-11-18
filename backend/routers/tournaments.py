"""Tournament bracket API routes."""

from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from typing import Iterator, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from backend.db import acquire_quota_lock_nowait, get_db
from backend.rate_limit import count_ai_curation_attempt, limiter
from backend.db_models import Movie, Tournament, TournamentMatch, User, UserMovie
from backend.routers.auth import get_current_user, require_ai_consent, require_consent
from backend.services.sync import sync_ratings_background
from backend.schemas import (
    FilterType,
    MediaType,
    MovieSchema,
    TournamentCreate,
    TournamentListItem,
    TournamentMatchSchema,
    TournamentSchema,
)
from backend.services.ranking import InvalidFilterError, ranked_user_movies_stmt
from backend.services.curator import CurationError
from backend.services.quota import enforce_daily_quota
from backend.services.tournament import (
    CANDIDATE_POOL_FACTOR,
    TOURNAMENT_DAILY_QUOTA,
    CurationBookkeeping,
    TournamentRuleError,
    apply_curation,
    count_filtered_ranked_films,
    create_tournament_bracket,
    curate_and_select_films,
    delete_bracket,
    ensure_can_abandon,
    ensure_can_regenerate,
    ensure_pool_fills_bracket,
    get_filtered_ranked_films,
    max_bracket_size,
    next_playable_match,
    progress_label,
    record_match_winner,
    validate_match,
)

router = APIRouter(prefix="/api/tournaments", tags=["tournaments"])
logger = logging.getLogger(__name__)


# ── Response helpers ──────────────────────────────────────────────────


def _movie_schema(movie: Movie | None) -> MovieSchema | None:
    if movie is None:
        return None
    return MovieSchema.from_model(movie)


def _match_schema(m: TournamentMatch) -> TournamentMatchSchema:
    return TournamentMatchSchema(
        id=str(m.id),
        round=m.round,
        position=m.position,
        movie_a=_movie_schema(m.movie_a),
        movie_b=_movie_schema(m.movie_b),
        winner_movie_id=str(m.winner_movie_id) if m.winner_movie_id else None,
        is_bye=m.is_bye,
        played_at=m.played_at,
    )


def _tournament_schema(t: Tournament) -> TournamentSchema:
    sorted_matches = sorted(t.matches, key=lambda m: (m.round, m.position))
    return TournamentSchema(
        id=str(t.id),
        name=t.name,
        filter_type=t.filter_type,
        filter_value=t.filter_value,
        bracket_size=t.bracket_size,
        status=t.status,
        champion_movie_id=str(t.champion_movie_id) if t.champion_movie_id else None,
        tagline=t.tagline,
        theme_description=t.theme_description,
        is_ai_curated=t.is_ai_curated,
        created_at=t.created_at,
        completed_at=t.completed_at,
        matches=[_match_schema(m) for m in sorted_matches],
    )


@contextmanager
def _rule_errors_as_400() -> Iterator[None]:
    try:
        yield
    except TournamentRuleError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def _candidate_pool(
    db: AsyncSession,
    user_id: uuid.UUID,
    filter_type: Optional[FilterType],
    filter_value: Optional[str],
    media_type: str,
    bracket_size: int,
) -> list[UserMovie]:
    """The films a bracket of ``bracket_size`` is seeded or curated from.

    The capped length answers the pool-size rule exactly as the full count
    would: it is at least 24, and a pool of 3x the bracket fills it.
    """
    try:
        user_movies = await get_filtered_ranked_films(
            db,
            user_id,
            filter_type,
            filter_value,
            media_type=media_type,
            limit=bracket_size * CANDIDATE_POOL_FACTOR,
        )
    except InvalidFilterError:
        raise HTTPException(status_code=400, detail="Invalid decade format")
    with _rule_errors_as_400():
        ensure_pool_fills_bracket(bracket_size, len(user_movies))
    return user_movies


async def _curate(
    request: Request,
    user_movies: list[UserMovie],
    bracket_size: int,
    filter_type: Optional[FilterType],
    filter_value: Optional[str],
    theme_hint: str,
) -> tuple[list[UserMovie], dict]:
    # Spend the attempt before the LLM call so failures count (SEC-10, #782).
    count_ai_curation_attempt(request)
    try:
        return await curate_and_select_films(
            user_movies=user_movies,
            bracket_size=bracket_size,
            filter_type=filter_type,
            filter_value=filter_value,
            theme_hint=theme_hint,
        )
    except CurationError as e:
        logger.error("AI curation failed: %s", e)
        raise HTTPException(
            status_code=500, detail="AI curation failed. Please try again."
        )


async def _load_tournament(
    tournament_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> Tournament:
    """Load a tournament with all matches and movie relationships."""
    stmt = (
        select(Tournament)
        .options(
            joinedload(Tournament.matches).joinedload(TournamentMatch.movie_a),
            joinedload(Tournament.matches).joinedload(TournamentMatch.movie_b),
            joinedload(Tournament.matches).joinedload(TournamentMatch.winner_movie),
        )
        .where(Tournament.id == tournament_id, Tournament.user_id == user_id)
    )
    result = await db.execute(stmt)
    tournament = result.unique().scalars().first()
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return tournament


# ── Endpoints ─────────────────────────────────────────────────────────


@router.get("/genres", response_model=list[str])
@limiter.limit("30/minute")
async def get_available_genres(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    media_type: MediaType = Query(default="movie"),
):
    """Return distinct genres from user's seen films for tournament filtering."""
    stmt = (
        ranked_user_movies_stmt(current_user.id, media_type)
        .with_only_columns(func.unnest(Movie.genres).label("genre"))
        .where(Movie.genres.isnot(None))
        .distinct()
        .order_by("genre")
    )
    result = await db.execute(stmt)
    return [row[0] for row in result.all()]


@router.get("/pool-count")
@limiter.limit("30/minute")
async def get_pool_count(
    request: Request,
    filter_type: FilterType | None = Query(default=None),
    filter_value: str | None = Query(default=None, max_length=200),
    media_type: MediaType = Query(default="movie"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return number of ranked films matching the given filter."""
    try:
        count = await count_filtered_ranked_films(
            db,
            current_user.id,
            filter_type,
            filter_value,
            media_type=media_type,
        )
    except InvalidFilterError:
        raise HTTPException(status_code=400, detail="Invalid decade format")
    return {"count": count, "max_bracket_size": max_bracket_size(count)}


@router.post("", response_model=TournamentSchema)
@limiter.limit("10/minute")
async def create_tournament(
    request: Request,
    body: TournamentCreate,
    current_user: User = Depends(require_consent),
    db: AsyncSession = Depends(get_db),
):
    """Create and seed a new tournament bracket."""
    uid = current_user.id

    if body.ai_curated:
        require_ai_consent(current_user)

    # Non-blocking (AUD-01): the request goes on to an LLM call.
    await enforce_daily_quota(db, TOURNAMENT_DAILY_QUOTA, uid, nowait=True)
    user_movies = await _candidate_pool(
        db, uid, body.filter_type, body.filter_value, body.media_type, body.bracket_size
    )

    tournament = Tournament(
        user_id=uid,
        name=body.name,
        filter_type=body.filter_type,
        filter_value=body.filter_value,
        media_type=body.media_type,
        bracket_size=body.bracket_size,
        status="active",
        is_ai_curated=body.ai_curated,
    )
    if body.ai_curated:
        theme_hint = body.name.strip() if body.name else ""
        seeded_films, llm_result = await _curate(
            request,
            user_movies,
            body.bracket_size,
            body.filter_type,
            body.filter_value,
            theme_hint,
        )
        apply_curation(tournament, llm_result, CurationBookkeeping(theme_hint))
        # An empty AI name falls back to the one the user typed.
        tournament.name = tournament.name or body.name
    else:
        seeded_films = user_movies[: body.bracket_size]
    db.add(tournament)
    await db.flush()

    await create_tournament_bracket(db, tournament.id, body.bracket_size, seeded_films)

    tournament = await _load_tournament(tournament.id, uid, db)
    return _tournament_schema(tournament)


@router.post("/{tournament_id}/regenerate", response_model=TournamentSchema)
@limiter.limit("10/minute")
async def regenerate_tournament(
    tournament_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-run LLM curation with same candidates, up to MAX_REGENERATIONS times."""
    uid = current_user.id

    # Lock this tournament before reading _regen_count so a parallel regenerate
    # cannot read the same count and both re-curate (SEC-02, #570). The scope is
    # shared with submit_match_result_endpoint and abandon_tournament so a match
    # recorded during curation cannot be wiped by the match delete below (#692).
    # Non-blocking (AUD-01): a queued waiter would hold a pooled connection
    # through the LLM call.
    await acquire_quota_lock_nowait(db, "tournament_status", tournament_id)

    tournament = await _load_tournament(tournament_id, uid, db)

    # Enforce consent before revealing any business-logic details
    require_ai_consent(current_user)

    with _rule_errors_as_400():
        ensure_can_regenerate(tournament)

    user_movies = await _candidate_pool(
        db,
        uid,
        tournament.filter_type,
        tournament.filter_value,
        tournament.media_type,
        tournament.bracket_size,
    )

    bookkeeping = CurationBookkeeping.read(tournament)
    selected_ums, llm_result = await _curate(
        request,
        user_movies,
        tournament.bracket_size,
        tournament.filter_type,
        tournament.filter_value,
        bookkeeping.theme_hint,
    )

    await delete_bracket(db, tournament_id)
    apply_curation(tournament, llm_result, bookkeeping.next_regeneration())
    await create_tournament_bracket(
        db, tournament_id, tournament.bracket_size, selected_ums
    )

    tournament = await _load_tournament(tournament_id, uid, db)
    return _tournament_schema(tournament)


@router.get("", response_model=list[TournamentListItem])
@limiter.limit("30/minute")
async def list_tournaments(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all tournaments for the current user."""
    stmt = (
        select(Tournament)
        .options(joinedload(Tournament.matches))
        .where(Tournament.user_id == current_user.id)
        .order_by(Tournament.created_at.desc())
        .limit(100)  # safety cap — prevents unbounded result sets per user
    )
    result = await db.execute(stmt)
    tournaments = result.unique().scalars().all()

    return [
        TournamentListItem(
            id=str(t.id),
            name=t.name,
            bracket_size=t.bracket_size,
            status=t.status,
            created_at=t.created_at,
            progress=progress_label(t),
        )
        for t in tournaments
    ]


@router.get("/{tournament_id}", response_model=TournamentSchema)
@limiter.limit("30/minute")
async def get_tournament(
    request: Request,
    tournament_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return full bracket state for a tournament."""
    tournament = await _load_tournament(tournament_id, current_user.id, db)
    return _tournament_schema(tournament)


@router.get("/{tournament_id}/next")
@limiter.limit("30/minute")
async def get_next_match(
    request: Request,
    tournament_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the next unplayed match in the tournament."""
    tournament = await _load_tournament(tournament_id, current_user.id, db)

    if tournament.status == "completed":
        raise HTTPException(status_code=404, detail="Tournament is complete")
    if tournament.status == "abandoned":
        raise HTTPException(status_code=404, detail="Tournament is abandoned")

    match = next_playable_match(tournament)
    if match is None:
        raise HTTPException(status_code=404, detail="No playable matches found")
    return _match_schema(match)


class MatchResult(BaseModel):
    winner_movie_id: str


@router.post("/{tournament_id}/matches/{match_id}")
@limiter.limit("60/minute")
async def submit_match_result_endpoint(
    request: Request,
    tournament_id: uuid.UUID,
    match_id: uuid.UUID,
    body: MatchResult,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_consent),
    db: AsyncSession = Depends(get_db),
):
    """Submit a tournament match result."""
    uid = current_user.id

    # Serialize against abandon_tournament (SEC-19, #587) and regenerate (#692):
    # held until get_db commits, so the status validate_match reads cannot be
    # flipped underneath the bracket write. Non-blocking (AUD-01, SEC-02):
    # regenerate holds this lock across an LLM call, so a queued waiter would
    # pin a pooled connection for up to LLM_TIMEOUT_SECONDS.
    await acquire_quota_lock_nowait(db, "tournament_status", tournament_id)

    tournament = await _load_tournament(tournament_id, uid, db)
    try:
        winner_id = uuid.UUID(body.winner_movie_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid winner_movie_id")

    with _rule_errors_as_400():
        loser_id = validate_match(tournament, match_id, winner_id)

    new_winner_elo, new_loser_elo = await record_match_winner(
        db,
        tournament_id,
        tournament.bracket_size,
        match_id,
        winner_id,
        loser_id,
        uid,
    )

    # Same fire-and-forget rating sync a regular duel gets (FD-040)
    background_tasks.add_task(
        sync_ratings_background,
        uid,
        winner_id,
        new_winner_elo,
        loser_id,
        new_loser_elo,
    )

    tournament = await _load_tournament(tournament_id, uid, db)
    return _tournament_schema(tournament)


@router.delete("/{tournament_id}")
@limiter.limit("10/minute")
async def abandon_tournament(
    request: Request,
    tournament_id: uuid.UUID,
    current_user: User = Depends(require_consent),
    db: AsyncSession = Depends(get_db),
):
    """Abandon a tournament (soft delete)."""
    uid = current_user.id

    # Same lock as submit_match_result_endpoint (SEC-19, #587), taken before
    # the read so a match result that just completed the bracket is visible.
    # Non-blocking for the same reason (AUD-01, SEC-02).
    await acquire_quota_lock_nowait(db, "tournament_status", tournament_id)

    stmt = select(Tournament).where(Tournament.id == tournament_id)
    result = await db.execute(stmt)
    tournament = result.scalar_one_or_none()
    if not tournament or tournament.user_id != uid:
        raise HTTPException(status_code=404, detail="Tournament not found")

    with _rule_errors_as_400():
        ensure_can_abandon(tournament)

    tournament.status = "abandoned"
    return {"status": "abandoned"}
