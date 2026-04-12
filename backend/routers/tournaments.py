"""Tournament bracket API routes."""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from backend.db import get_db
from backend.db_models import Duel, Movie, Tournament, TournamentMatch, User, UserMovie
from backend.routers.auth import get_current_user
from backend.schemas import (
    MovieSchema,
    TournamentCreate,
    TournamentListItem,
    TournamentMatchSchema,
    TournamentSchema,
)
from backend.services.curator import curate_tournament
from backend.services.elo import get_initial_elo, update_elo

router = APIRouter(prefix="/api/tournaments", tags=["tournaments"])


# ── Helpers ────────────────────────────────────────────────────────────


def generate_seeded_bracket(n: int) -> list[tuple[int, int]]:
    """Generate standard tournament seeding for n participants.

    Returns list of (seed_a, seed_b) tuples for round 1.
    Seeds are 1-indexed.
    """
    if n == 2:
        return [(1, 2)]
    if n == 4:
        return [(1, 4), (2, 3)]
    if n == 8:
        return [(1, 8), (4, 5), (2, 7), (3, 6)]
    if n == 16:
        return [
            (1, 16), (8, 9), (4, 13), (5, 12),
            (2, 15), (7, 10), (3, 14), (6, 11),
        ]
    if n == 32:
        top = generate_seeded_bracket(16)
        return [(a, 33 - a) for a, _ in top] + [(b, 33 - b) for _, b in top]
    if n == 64:
        top = generate_seeded_bracket(32)
        return [(a, 65 - a) for a, _ in top] + [(b, 65 - b) for _, b in top]
    raise ValueError(f"Unsupported bracket size: {n}")


def _num_rounds(bracket_size: int) -> int:
    return int(math.log2(bracket_size))


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
    # Sort matches by round then position for consistent output
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


# ── Endpoints ──────────────────────────────────────────────────────────


@router.get("/genres", response_model=list[str])
async def get_available_genres(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return distinct genres from user's seen films for tournament filtering."""
    uid = current_user.id
    stmt = (
        select(func.unnest(Movie.genres).label("genre"))
        .select_from(UserMovie)
        .join(Movie, UserMovie.movie_id == Movie.id)
        .where(
            UserMovie.user_id == uid,
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
    uid = current_user.id
    stmt = (
        select(UserMovie)
        .options(joinedload(UserMovie.movie))
        .where(
            UserMovie.user_id == uid,
            UserMovie.seen.is_(True),
            UserMovie.battles >= 1,
            UserMovie.elo.isnot(None),
        )
    )
    result = await db.execute(stmt)
    user_movies = result.unique().scalars().all()

    if filter_type == "genre" and filter_value:
        genre_lower = filter_value.lower()
        user_movies = [
            um for um in user_movies
            if um.movie.genres and any(g.lower() == genre_lower for g in um.movie.genres)
        ]
    elif filter_type == "decade" and filter_value:
        decade_str = filter_value.rstrip("s")
        try:
            decade_start = int(decade_str)
        except ValueError:
            return {"count": 0}
        user_movies = [
            um for um in user_movies
            if um.movie.year and decade_start <= um.movie.year <= decade_start + 9
        ]

    return {"count": len(user_movies)}


@router.post("", response_model=TournamentSchema)
async def create_tournament(
    body: TournamentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create and seed a new tournament bracket."""
    uid = current_user.id

    # 1. Query user's ranked films
    stmt = (
        select(UserMovie)
        .options(joinedload(UserMovie.movie))
        .where(
            UserMovie.user_id == uid,
            UserMovie.seen.is_(True),
            UserMovie.battles >= 1,
            UserMovie.elo.isnot(None),
        )
    )
    result = await db.execute(stmt)
    user_movies = result.unique().scalars().all()

    # 2. Filter by genre or decade if requested
    if body.filter_type == "genre" and body.filter_value:
        genre_lower = body.filter_value.lower()
        user_movies = [
            um for um in user_movies
            if um.movie.genres and any(g.lower() == genre_lower for g in um.movie.genres)
        ]
    elif body.filter_type == "decade" and body.filter_value:
        # Parse decade: "1990s" -> 1990, or just "1990" -> 1990
        decade_str = body.filter_value.rstrip("s")
        try:
            decade_start = int(decade_str)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid decade format")
        user_movies = [
            um for um in user_movies
            if um.movie.year and decade_start <= um.movie.year <= decade_start + 9
        ]

    # 3. Validate enough films (minimum 4, max bracket = 4x pool)
    if len(user_movies) < 4:
        raise HTTPException(
            status_code=400,
            detail="Need at least 4 ranked films",
        )
    if body.bracket_size > len(user_movies) * 4:
        raise HTTPException(
            status_code=400,
            detail=f"Bracket too large. Max {len(user_movies) * 4} for {len(user_movies)} films",
        )

    # 4. Sort by ELO descending
    user_movies.sort(key=lambda um: um.elo or 0, reverse=True)

    # 5. AI curation or standard selection
    ai_name = None
    ai_tagline = None
    ai_theme_description = None
    ai_llm_response = None

    if body.ai_curated:
        # Build candidate list: cap at bracket_size * 3
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

        # Validate returned film_ids are all in candidate list
        candidate_ids = {str(um.movie_id) for um in candidate_pool}
        invalid_ids = set(llm_result["film_ids"]) - candidate_ids
        if invalid_ids:
            raise HTTPException(
                status_code=500,
                detail=f"AI selected films not in candidate pool: {invalid_ids}",
            )

        # Build seeded_films from LLM selection, ordered by ELO for seeding
        film_id_set = set(llm_result["film_ids"])
        selected_ums = [um for um in candidate_pool if str(um.movie_id) in film_id_set]
        # Re-sort by ELO descending for proper seeding
        selected_ums.sort(key=lambda um: um.elo or 0, reverse=True)
        seeded_films = selected_ums

        ai_name = llm_result["name"]
        ai_tagline = llm_result.get("tagline")
        ai_theme_description = llm_result.get("theme_description")
        llm_result["_theme_hint"] = body.name.strip() if body.name else ""
        ai_llm_response = llm_result
    else:
        seeded_films = user_movies[: body.bracket_size]

    actual_films = len(seeded_films)
    num_byes = body.bracket_size - actual_films

    # 6. Generate seeded bracket pairings
    pairings = generate_seeded_bracket(body.bracket_size)

    # 7. Create tournament record
    tournament_name = ai_name if ai_name else body.name
    tournament = Tournament(
        user_id=uid,
        name=tournament_name,
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

    # 7. Create round 1 matches with seeded pairings (including byes)
    num_rounds = _num_rounds(body.bracket_size)
    now = datetime.now(timezone.utc)

    for position, (seed_a, seed_b) in enumerate(pairings):
        # Seeds beyond actual_films have no film — that side is a bye
        has_a = seed_a <= actual_films
        has_b = seed_b <= actual_films

        if has_a and has_b:
            # Normal match — both films present
            match = TournamentMatch(
                tournament_id=tournament.id,
                round=1,
                position=position,
                movie_a_id=seeded_films[seed_a - 1].movie_id,
                movie_b_id=seeded_films[seed_b - 1].movie_id,
            )
        elif has_a and not has_b:
            # Bye: seed_a advances automatically
            match = TournamentMatch(
                tournament_id=tournament.id,
                round=1,
                position=position,
                movie_a_id=seeded_films[seed_a - 1].movie_id,
                movie_b_id=None,
                winner_movie_id=seeded_films[seed_a - 1].movie_id,
                is_bye=True,
                played_at=now,
            )
        elif has_b and not has_a:
            # Bye: seed_b advances automatically
            match = TournamentMatch(
                tournament_id=tournament.id,
                round=1,
                position=position,
                movie_a_id=seeded_films[seed_b - 1].movie_id,
                movie_b_id=None,
                winner_movie_id=seeded_films[seed_b - 1].movie_id,
                is_bye=True,
                played_at=now,
            )
        else:
            # Both seeds missing — shouldn't happen with valid bracket sizes
            match = TournamentMatch(
                tournament_id=tournament.id,
                round=1,
                position=position,
            )
        db.add(match)

    # 8. Create empty matches for subsequent rounds
    for round_num in range(2, num_rounds + 1):
        matches_in_round = body.bracket_size // (2**round_num)
        for position in range(matches_in_round):
            match = TournamentMatch(
                tournament_id=tournament.id,
                round=round_num,
                position=position,
            )
            db.add(match)

    await db.flush()

    # 9. Propagate bye winners to round 2 slots
    if num_byes > 0:
        # Re-fetch round 1 matches to propagate winners
        r1_stmt = (
            select(TournamentMatch)
            .where(
                TournamentMatch.tournament_id == tournament.id,
                TournamentMatch.round == 1,
                TournamentMatch.is_bye.is_(True),
            )
        )
        r1_result = await db.execute(r1_stmt)
        bye_matches = r1_result.scalars().all()

        for bye_match in bye_matches:
            next_pos = bye_match.position // 2
            next_round_stmt = select(TournamentMatch).where(
                TournamentMatch.tournament_id == tournament.id,
                TournamentMatch.round == 2,
                TournamentMatch.position == next_pos,
            )
            next_match_obj = (await db.execute(next_round_stmt)).scalar_one()
            if bye_match.position % 2 == 0:
                next_match_obj.movie_a_id = bye_match.winner_movie_id
            else:
                next_match_obj.movie_b_id = bye_match.winner_movie_id

        await db.flush()

    # Reload the tournament with all relationships
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

    # Check no matches have been played (excluding byes)
    played_matches = [
        m for m in tournament.matches
        if m.winner_movie_id is not None and not m.is_bye
    ]
    if played_matches:
        raise HTTPException(status_code=400, detail="Cannot regenerate after matches have been played")

    # Track regeneration count in llm_response
    regen_count = 0
    if tournament.llm_response and isinstance(tournament.llm_response, dict):
        regen_count = tournament.llm_response.get("_regen_count", 0)
    if regen_count >= 3:
        raise HTTPException(status_code=400, detail="Maximum regeneration attempts (3) reached")

    # Rebuild candidate list from user's ranked films with same filters
    stmt = (
        select(UserMovie)
        .options(joinedload(UserMovie.movie))
        .where(
            UserMovie.user_id == uid,
            UserMovie.seen.is_(True),
            UserMovie.battles >= 1,
            UserMovie.elo.isnot(None),
        )
    )
    result = await db.execute(stmt)
    user_movies = result.unique().scalars().all()

    if tournament.filter_type == "genre" and tournament.filter_value:
        genre_lower = tournament.filter_value.lower()
        user_movies = [
            um for um in user_movies
            if um.movie.genres and any(g.lower() == genre_lower for g in um.movie.genres)
        ]
    elif tournament.filter_type == "decade" and tournament.filter_value:
        decade_str = tournament.filter_value.rstrip("s")
        try:
            decade_start = int(decade_str)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid decade format")
        user_movies = [
            um for um in user_movies
            if um.movie.year and decade_start <= um.movie.year <= decade_start + 9
        ]

    user_movies.sort(key=lambda um: um.elo or 0, reverse=True)
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

    # Validate returned film_ids
    candidate_ids = {str(um.movie_id) for um in candidate_pool}
    invalid_ids = set(llm_result["film_ids"]) - candidate_ids
    if invalid_ids:
        raise HTTPException(
            status_code=500,
            detail=f"AI selected films not in candidate pool: {invalid_ids}",
        )

    # Build new seeded films
    film_id_set = set(llm_result["film_ids"])
    selected_ums = [um for um in candidate_pool if str(um.movie_id) in film_id_set]
    selected_ums.sort(key=lambda um: um.elo or 0, reverse=True)
    actual_films = len(selected_ums)

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

    # Recreate bracket
    pairings = generate_seeded_bracket(tournament.bracket_size)
    num_rounds = _num_rounds(tournament.bracket_size)
    now = datetime.now(timezone.utc)
    num_byes = tournament.bracket_size - actual_films

    for position, (seed_a, seed_b) in enumerate(pairings):
        has_a = seed_a <= actual_films
        has_b = seed_b <= actual_films

        if has_a and has_b:
            match = TournamentMatch(
                tournament_id=tournament_id,
                round=1,
                position=position,
                movie_a_id=selected_ums[seed_a - 1].movie_id,
                movie_b_id=selected_ums[seed_b - 1].movie_id,
            )
        elif has_a and not has_b:
            match = TournamentMatch(
                tournament_id=tournament_id,
                round=1,
                position=position,
                movie_a_id=selected_ums[seed_a - 1].movie_id,
                movie_b_id=None,
                winner_movie_id=selected_ums[seed_a - 1].movie_id,
                is_bye=True,
                played_at=now,
            )
        elif has_b and not has_a:
            match = TournamentMatch(
                tournament_id=tournament_id,
                round=1,
                position=position,
                movie_a_id=selected_ums[seed_b - 1].movie_id,
                movie_b_id=None,
                winner_movie_id=selected_ums[seed_b - 1].movie_id,
                is_bye=True,
                played_at=now,
            )
        else:
            match = TournamentMatch(
                tournament_id=tournament_id,
                round=1,
                position=position,
            )
        db.add(match)

    for round_num in range(2, num_rounds + 1):
        matches_in_round = tournament.bracket_size // (2**round_num)
        for position in range(matches_in_round):
            match = TournamentMatch(
                tournament_id=tournament_id,
                round=round_num,
                position=position,
            )
            db.add(match)

    await db.flush()

    # Propagate bye winners to round 2
    if num_byes > 0:
        r1_stmt = (
            select(TournamentMatch)
            .where(
                TournamentMatch.tournament_id == tournament_id,
                TournamentMatch.round == 1,
                TournamentMatch.is_bye.is_(True),
            )
        )
        r1_result = await db.execute(r1_stmt)
        bye_matches = r1_result.scalars().all()

        for bye_match in bye_matches:
            next_pos = bye_match.position // 2
            next_round_stmt = select(TournamentMatch).where(
                TournamentMatch.tournament_id == tournament_id,
                TournamentMatch.round == 2,
                TournamentMatch.position == next_pos,
            )
            next_match_obj = (await db.execute(next_round_stmt)).scalar_one()
            if bye_match.position % 2 == 0:
                next_match_obj.movie_a_id = bye_match.winner_movie_id
            else:
                next_match_obj.movie_b_id = bye_match.winner_movie_id

        await db.flush()

    # Reload and return
    tournament = await _load_tournament(tournament_id, uid, db)
    return _tournament_schema(tournament)


@router.get("", response_model=list[TournamentListItem])
async def list_tournaments(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all tournaments for the current user."""
    uid = current_user.id

    stmt = (
        select(Tournament)
        .options(joinedload(Tournament.matches))
        .where(Tournament.user_id == uid)
        .order_by(Tournament.created_at.desc())
    )
    result = await db.execute(stmt)
    tournaments = result.unique().scalars().all()

    items = []
    for t in tournaments:
        # Calculate progress
        if t.status == "completed":
            progress = "Completed"
        elif t.status == "abandoned":
            progress = "Abandoned"
        else:
            # Find current round: earliest round with unfinished matches
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

    # Find first match in earliest incomplete round with both movies set
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
async def submit_match_result(
    tournament_id: uuid.UUID,
    match_id: uuid.UUID,
    body: MatchResult,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit the result of a tournament match."""
    uid = current_user.id
    tournament = await _load_tournament(tournament_id, uid, db)

    if tournament.status != "active":
        raise HTTPException(status_code=400, detail="Tournament is not active")

    # Find the match
    match = None
    for m in tournament.matches:
        if m.id == match_id:
            match = m
            break
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    if match.winner_movie_id is not None:
        raise HTTPException(status_code=400, detail="Match already played")

    winner_id = uuid.UUID(body.winner_movie_id)
    if winner_id not in (match.movie_a_id, match.movie_b_id):
        raise HTTPException(status_code=400, detail="Winner must be one of the two movies")

    loser_id = match.movie_b_id if winner_id == match.movie_a_id else match.movie_a_id

    # Fetch user_movies for ELO update
    stmt_winner = select(UserMovie).where(
        UserMovie.user_id == uid, UserMovie.movie_id == winner_id
    )
    stmt_loser = select(UserMovie).where(
        UserMovie.user_id == uid, UserMovie.movie_id == loser_id
    )
    um_winner = (await db.execute(stmt_winner)).scalar_one()
    um_loser = (await db.execute(stmt_loser)).scalar_one()

    winner_elo_before = um_winner.elo if um_winner.elo is not None else get_initial_elo(um_winner.seeded_elo)
    loser_elo_before = um_loser.elo if um_loser.elo is not None else get_initial_elo(um_loser.seeded_elo)

    new_winner_elo, new_loser_elo = update_elo(
        winner_elo_before, loser_elo_before, um_winner.battles, um_loser.battles
    )

    # Update ELO on user_movies
    now = datetime.now(timezone.utc)
    um_winner.elo = new_winner_elo
    um_loser.elo = new_loser_elo
    um_winner.battles += 1
    um_loser.battles += 1
    um_winner.last_dueled_at = now
    um_loser.last_dueled_at = now
    um_winner.updated_at = now
    um_loser.updated_at = now

    # Create a real Duel record
    duel = Duel(
        user_id=uid,
        winner_movie_id=winner_id,
        loser_movie_id=loser_id,
        winner_elo_before=winner_elo_before,
        loser_elo_before=loser_elo_before,
        winner_elo_after=new_winner_elo,
        loser_elo_after=new_loser_elo,
        mode="tournament",
    )
    db.add(duel)
    await db.flush()

    # Update match
    # Re-fetch the match directly to avoid stale state from joinedload
    match_stmt = select(TournamentMatch).where(TournamentMatch.id == match_id)
    match_obj = (await db.execute(match_stmt)).scalar_one()
    match_obj.winner_movie_id = winner_id
    match_obj.duel_id = duel.id
    match_obj.played_at = now

    round_num = match_obj.round
    num_rounds = _num_rounds(tournament.bracket_size)

    # Immediately propagate winner to the next round slot
    if round_num < num_rounds:
        next_pos = match_obj.position // 2
        next_round_stmt = select(TournamentMatch).where(
            TournamentMatch.tournament_id == tournament_id,
            TournamentMatch.round == round_num + 1,
            TournamentMatch.position == next_pos,
        )
        next_match_obj = (await db.execute(next_round_stmt)).scalar_one()
        if match_obj.position % 2 == 0:
            next_match_obj.movie_a_id = winner_id
        else:
            next_match_obj.movie_b_id = winner_id

    # Check if this was the final match — crown champion
    if round_num == num_rounds:
        tournament_stmt = select(Tournament).where(Tournament.id == tournament_id)
        t = (await db.execute(tournament_stmt)).scalar_one()
        t.champion_movie_id = winner_id
        t.status = "completed"
        t.completed_at = now

    await db.flush()

    # Reload and return updated tournament
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

    # Verify ownership
    stmt = select(Tournament).where(Tournament.id == tournament_id)
    result = await db.execute(stmt)
    tournament = result.scalar_one_or_none()
    if not tournament or tournament.user_id != uid:
        raise HTTPException(status_code=404, detail="Tournament not found")

    if tournament.status == "abandoned":
        raise HTTPException(status_code=400, detail="Tournament already abandoned")

    tournament.status = "abandoned"
    return {"status": "abandoned"}
