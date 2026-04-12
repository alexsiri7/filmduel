"""Tournament bracket API routes."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from backend.db import get_db
from backend.db_models import Movie, Tournament, TournamentMatch, User, UserMovie
from backend.routers.auth import get_current_user
from backend.schemas import (
    MovieSchema,
    TournamentCreate,
    TournamentListItem,
    TournamentMatchSchema,
    TournamentSchema,
)
from backend.services.curator import curate_tournament
from backend.services.tournament import (
    create_tournament_bracket,
    generate_seeded_bracket,
    get_filtered_ranked_films,
    submit_match_result,
    _num_rounds,
)

router = APIRouter(prefix="/api/tournaments", tags=["tournaments"])


# ── Response helpers ──────────────────────────────────────────────────


def _movie_schema(movie: Optional[Movie]) -> Optional[MovieSchema]:
    if movie is None:
        return None
    return MovieSchema(
        id=str(movie.id),
        trakt_id=movie.trakt_id,
        tmdb_id=movie.tmdb_id,
        imdb_id=movie.imdb_id,
        title=movie.title,
        year=movie.year,
        poster_url=movie.poster_url,
        overview=movie.overview,
    )


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
        llm_response=t.llm_response,
        created_at=t.created_at,
        completed_at=t.completed_at,
        matches=[_match_schema(m) for m in sorted_matches],
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
        .where(Tournament.id == tournament_id)
    )
    result = await db.execute(stmt)
    tournament = result.unique().scalars().first()
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    if tournament.user_id != user_id:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return tournament


# ── Endpoints ─────────────────────────────────────────────────────────


@router.get("/genres", response_model=list[str])
async def get_available_genres(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return distinct genres from user's seen films for tournament filtering."""
    stmt = (
        select(func.unnest(Movie.genres).label("genre"))
        .select_from(UserMovie)
        .join(Movie, UserMovie.movie_id == Movie.id)
        .where(
            UserMovie.user_id == current_user.id,
            UserMovie.seen.is_(True),
            UserMovie.battles >= 1,
            UserMovie.elo.isnot(None),
            Movie.genres.isnot(None),
        )
        .distinct()
        .order_by("genre")
    )
    result = await db.execute(stmt)
    return [row[0] for row in result.all()]


@router.get("/pool-count")
async def get_pool_count(
    filter_type: Optional[str] = None,
    filter_value: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return number of ranked films matching the given filter."""
    try:
        user_movies = await get_filtered_ranked_films(
            db, current_user.id, filter_type, filter_value,
        )
    except ValueError:
        return {"count": 0}
    return {"count": len(user_movies)}


@router.post("", response_model=TournamentSchema)
async def create_tournament(
    body: TournamentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create and seed a new tournament bracket."""
    uid = current_user.id

    try:
        user_movies = await get_filtered_ranked_films(
            db, uid, body.filter_type, body.filter_value,
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid decade format")

    if len(user_movies) < 4:
        raise HTTPException(status_code=400, detail="Need at least 4 ranked films")
    if body.bracket_size > len(user_movies) * 4:
        raise HTTPException(
            status_code=400,
            detail=f"Bracket too large. Max {len(user_movies) * 4} for {len(user_movies)} films",
        )

    # AI curation or standard selection
    ai_name = None
    ai_tagline = None
    ai_theme_description = None
    ai_llm_response = None

    if body.ai_curated:
        candidate_pool = user_movies[: body.bracket_size * 3]
        candidates = [
            {
                "id": str(um.movie_id),
                "title": um.movie.title,
                "year": um.movie.year,
                "genres": um.movie.genres or [],
                "elo": um.elo,
                "battles": um.battles,
            }
            for um in candidate_pool
        ]

        filter_context = ""
        if body.filter_type and body.filter_value:
            filter_context = f"{body.filter_type}: {body.filter_value}"

        llm_result = await curate_tournament(
            candidates=candidates,
            bracket_size=body.bracket_size,
            filter_context=filter_context,
            theme_hint=body.name.strip() if body.name else "",
        )

        candidate_ids = {str(um.movie_id) for um in candidate_pool}
        invalid_ids = set(llm_result["film_ids"]) - candidate_ids
        if invalid_ids:
            raise HTTPException(
                status_code=500,
                detail=f"AI selected films not in candidate pool: {invalid_ids}",
            )

        film_id_set = set(llm_result["film_ids"])
        selected_ums = [um for um in candidate_pool if str(um.movie_id) in film_id_set]
        selected_ums.sort(key=lambda um: um.elo or 0, reverse=True)
        seeded_films = selected_ums

        ai_name = llm_result["name"]
        ai_tagline = llm_result.get("tagline")
        ai_theme_description = llm_result.get("theme_description")
        llm_result["_theme_hint"] = body.name.strip() if body.name else ""
        ai_llm_response = llm_result
    else:
        seeded_films = user_movies[: body.bracket_size]

    # Create tournament record
    tournament = Tournament(
        user_id=uid,
        name=ai_name if ai_name else body.name,
        filter_type=body.filter_type,
        filter_value=body.filter_value,
        bracket_size=body.bracket_size,
        status="active",
        tagline=ai_tagline,
        theme_description=ai_theme_description,
        is_ai_curated=body.ai_curated,
        llm_response=ai_llm_response,
    )
    db.add(tournament)
    await db.flush()

    await create_tournament_bracket(db, tournament.id, body.bracket_size, seeded_films)

    tournament = await _load_tournament(tournament.id, uid, db)
    return _tournament_schema(tournament)


@router.post("/{tournament_id}/regenerate", response_model=TournamentSchema)
async def regenerate_tournament(
    tournament_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-run LLM curation with same candidates. Max 3 regenerations."""
    uid = current_user.id
    tournament = await _load_tournament(tournament_id, uid, db)

    if not tournament.is_ai_curated:
        raise HTTPException(status_code=400, detail="Only AI-curated tournaments can be regenerated")

    played_matches = [
        m for m in tournament.matches
        if m.winner_movie_id is not None and not m.is_bye
    ]
    if played_matches:
        raise HTTPException(status_code=400, detail="Cannot regenerate after matches have been played")

    regen_count = 0
    if tournament.llm_response and isinstance(tournament.llm_response, dict):
        regen_count = tournament.llm_response.get("_regen_count", 0)
    if regen_count >= 3:
        raise HTTPException(status_code=400, detail="Maximum regeneration attempts (3) reached")

    try:
        user_movies = await get_filtered_ranked_films(
            db, uid, tournament.filter_type, tournament.filter_value,
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid decade format")

    candidate_pool = user_movies[: tournament.bracket_size * 3]
    candidates = [
        {
            "id": str(um.movie_id),
            "title": um.movie.title,
            "year": um.movie.year,
            "genres": um.movie.genres or [],
            "elo": um.elo,
            "battles": um.battles,
        }
        for um in candidate_pool
    ]

    filter_context = ""
    if tournament.filter_type and tournament.filter_value:
        filter_context = f"{tournament.filter_type}: {tournament.filter_value}"

    # Use original name as theme hint for regeneration
    original_hint = tournament.llm_response.get("_theme_hint", "") if tournament.llm_response else ""
    llm_result = await curate_tournament(
        candidates=candidates,
        bracket_size=tournament.bracket_size,
        filter_context=filter_context,
        theme_hint=original_hint,
    )

    candidate_ids = {str(um.movie_id) for um in candidate_pool}
    invalid_ids = set(llm_result["film_ids"]) - candidate_ids
    if invalid_ids:
        raise HTTPException(
            status_code=500,
            detail=f"AI selected films not in candidate pool: {invalid_ids}",
        )

    film_id_set = set(llm_result["film_ids"])
    selected_ums = [um for um in candidate_pool if str(um.movie_id) in film_id_set]
    selected_ums.sort(key=lambda um: um.elo or 0, reverse=True)

    # Delete existing matches
    from sqlalchemy import delete

    await db.execute(
        delete(TournamentMatch).where(TournamentMatch.tournament_id == tournament_id)
    )
    await db.flush()

    # Update tournament metadata
    t_stmt = select(Tournament).where(Tournament.id == tournament_id)
    t = (await db.execute(t_stmt)).scalar_one()
    llm_result["_regen_count"] = regen_count + 1
    t.name = llm_result["name"]
    t.tagline = llm_result.get("tagline")
    t.theme_description = llm_result.get("theme_description")
    t.llm_response = llm_result

    await create_tournament_bracket(db, tournament_id, tournament.bracket_size, selected_ums)

    tournament = await _load_tournament(tournament_id, uid, db)
    return _tournament_schema(tournament)


@router.get("", response_model=list[TournamentListItem])
async def list_tournaments(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all tournaments for the current user."""
    stmt = (
        select(Tournament)
        .options(joinedload(Tournament.matches))
        .where(Tournament.user_id == current_user.id)
        .order_by(Tournament.created_at.desc())
    )
    result = await db.execute(stmt)
    tournaments = result.unique().scalars().all()

    items = []
    for t in tournaments:
        if t.status == "completed":
            progress = "Completed"
        elif t.status == "abandoned":
            progress = "Abandoned"
        else:
            matches_by_round: dict[int, list[TournamentMatch]] = {}
            for m in t.matches:
                matches_by_round.setdefault(m.round, []).append(m)

            current_round = 1
            for rnd in sorted(matches_by_round.keys()):
                round_matches = matches_by_round[rnd]
                played = sum(1 for m in round_matches if m.winner_movie_id is not None)
                if played < len(round_matches):
                    current_round = rnd
                    total_in_round = len(round_matches)
                    break
            else:
                current_round = max(matches_by_round.keys()) if matches_by_round else 1
                played = 0
                total_in_round = 0

            progress = f"Round {current_round} \u2014 {played}/{total_in_round} matches played"

        items.append(
            TournamentListItem(
                id=str(t.id),
                name=t.name,
                bracket_size=t.bracket_size,
                status=t.status,
                created_at=t.created_at,
                progress=progress,
            )
        )

    return items


@router.get("/{tournament_id}", response_model=TournamentSchema)
async def get_tournament(
    tournament_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return full bracket state for a tournament."""
    tournament = await _load_tournament(tournament_id, current_user.id, db)
    return _tournament_schema(tournament)


@router.get("/{tournament_id}/next")
async def get_next_match(
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

    sorted_matches = sorted(tournament.matches, key=lambda m: (m.round, m.position))
    for match in sorted_matches:
        if (
            match.movie_a_id is not None
            and match.movie_b_id is not None
            and match.winner_movie_id is None
        ):
            return _match_schema(match)

    raise HTTPException(status_code=404, detail="No playable matches found")


class MatchResult(BaseModel):
    winner_movie_id: str


@router.post("/{tournament_id}/matches/{match_id}")
async def submit_match_result_endpoint(
    tournament_id: uuid.UUID,
    match_id: uuid.UUID,
    body: MatchResult,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit the result of a tournament match."""
    uid = current_user.id
    tournament = await _load_tournament(tournament_id, uid, db)

    winner_id = uuid.UUID(body.winner_movie_id)
    try:
        await submit_match_result(db, tournament, match_id, winner_id, uid)
    except ValueError as e:
        status = 400
        msg = str(e)
        if msg == "Match not found":
            status = 404
        raise HTTPException(status_code=status, detail=msg)

    tournament = await _load_tournament(tournament_id, uid, db)
    return _tournament_schema(tournament)


@router.delete("/{tournament_id}")
async def abandon_tournament(
    tournament_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Abandon a tournament (soft delete)."""
    uid = current_user.id

    stmt = select(Tournament).where(Tournament.id == tournament_id)
    result = await db.execute(stmt)
    tournament = result.scalar_one_or_none()
    if not tournament or tournament.user_id != uid:
        raise HTTPException(status_code=404, detail="Tournament not found")

    if tournament.status == "abandoned":
        raise HTTPException(status_code=400, detail="Tournament already abandoned")

    tournament.status = "abandoned"
    return {"status": "abandoned"}
