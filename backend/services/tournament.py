"""Tournament bracket business logic."""

from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db_models import Duel, Tournament, TournamentMatch, UserMovie
from backend.services.curator import curate_tournament
from backend.services.elo import get_initial_elo, update_elo

logger = logging.getLogger(__name__)


# ── AI curation orchestration ────────────────────────────────────────


async def curate_and_select_films(
    user_movies: list[UserMovie],
    bracket_size: int,
    filter_type: Optional[str],
    filter_value: Optional[str],
    theme_hint: str,
) -> tuple[list[UserMovie], dict]:
    """Build candidates, call LLM curation, validate and return selected films.

    Returns (selected_user_movies_sorted_by_elo, llm_result_dict).
    Raises ValueError if LLM returns IDs not in the candidate pool.
    """
    candidate_pool = user_movies[:bracket_size * 3]
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
    if filter_type and filter_value:
        filter_context = f"{filter_type}: {filter_value}"

    llm_result = await curate_tournament(
        candidates=candidates,
        bracket_size=bracket_size,
        filter_context=filter_context,
        theme_hint=theme_hint,
    )

    candidate_ids = {str(um.movie_id) for um in candidate_pool}
    invalid_ids = set(llm_result["film_ids"]) - candidate_ids
    if invalid_ids:
        raise ValueError(f"AI selected films not in candidate pool: {invalid_ids}")

    film_id_set = set(llm_result["film_ids"])
    selected_ums = [um for um in candidate_pool if str(um.movie_id) in film_id_set]
    selected_ums.sort(key=lambda um: um.elo or 0, reverse=True)

    return selected_ums, llm_result


# ── Pure helpers ──────────────────────────────────────────────────────


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


# ── DB-dependent service functions ───────────────────────────────────


async def get_filtered_ranked_films(
    db: AsyncSession,
    user_id: uuid.UUID,
    filter_type: Optional[str] = None,
    filter_value: Optional[str] = None,
) -> list[UserMovie]:
    """Query ranked films with optional genre/decade filtering.

    Returns UserMovie list with .movie eagerly loaded, sorted by ELO desc.
    Raises ValueError for invalid decade format.
    """
    from sqlalchemy.orm import joinedload

    stmt = (
        select(UserMovie)
        .options(joinedload(UserMovie.movie))
        .where(
            UserMovie.user_id == user_id,
            UserMovie.seen.is_(True),
            UserMovie.battles >= 1,
            UserMovie.elo.isnot(None),
        )
    )
    result = await db.execute(stmt)
    user_movies = list(result.unique().scalars().all())

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
            raise ValueError("Invalid decade format")
        user_movies = [
            um for um in user_movies
            if um.movie.year and decade_start <= um.movie.year <= decade_start + 9
        ]

    user_movies.sort(key=lambda um: um.elo or 0, reverse=True)
    return user_movies


async def create_tournament_bracket(
    db: AsyncSession,
    tournament_id: uuid.UUID,
    bracket_size: int,
    seeded_films: list[UserMovie],
) -> None:
    """Create all bracket matches for a tournament.

    Creates round 1 matches (with bye handling), empty matches for
    subsequent rounds, and propagates bye winners into round 2.
    """
    actual_films = len(seeded_films)
    num_byes = bracket_size - actual_films
    pairings = generate_seeded_bracket(bracket_size)
    num_rounds = _num_rounds(bracket_size)
    now = datetime.now(timezone.utc)

    # Round 1 matches with seeded pairings (including byes)
    for position, (seed_a, seed_b) in enumerate(pairings):
        has_a = seed_a <= actual_films
        has_b = seed_b <= actual_films

        if has_a and has_b:
            match = TournamentMatch(
                tournament_id=tournament_id,
                round=1,
                position=position,
                movie_a_id=seeded_films[seed_a - 1].movie_id,
                movie_b_id=seeded_films[seed_b - 1].movie_id,
            )
        elif has_a and not has_b:
            match = TournamentMatch(
                tournament_id=tournament_id,
                round=1,
                position=position,
                movie_a_id=seeded_films[seed_a - 1].movie_id,
                movie_b_id=None,
                winner_movie_id=seeded_films[seed_a - 1].movie_id,
                is_bye=True,
                played_at=now,
            )
        elif has_b and not has_a:
            match = TournamentMatch(
                tournament_id=tournament_id,
                round=1,
                position=position,
                movie_a_id=seeded_films[seed_b - 1].movie_id,
                movie_b_id=None,
                winner_movie_id=seeded_films[seed_b - 1].movie_id,
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

    # Empty matches for subsequent rounds
    for round_num in range(2, num_rounds + 1):
        matches_in_round = bracket_size // (2 ** round_num)
        for position in range(matches_in_round):
            match = TournamentMatch(
                tournament_id=tournament_id,
                round=round_num,
                position=position,
            )
            db.add(match)

    await db.flush()

    # Propagate bye winners to round 2 slots
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


def validate_match(tournament: Tournament, match_id: uuid.UUID, winner_id: uuid.UUID) -> uuid.UUID:
    """Validate a match is playable. Returns the loser_id.

    Raises ValueError on validation failure.
    """
    if tournament.status != "active":
        raise ValueError("Tournament is not active")

    match = next((m for m in tournament.matches if m.id == match_id), None)
    if not match:
        raise ValueError("Match not found")
    if match.winner_movie_id is not None:
        raise ValueError("Match already played")
    if winner_id not in (match.movie_a_id, match.movie_b_id):
        raise ValueError("Winner must be one of the two movies")

    return match.movie_b_id if winner_id == match.movie_a_id else match.movie_a_id


async def record_match_winner(
    db: AsyncSession,
    tournament_id: uuid.UUID,
    bracket_size: int,
    match_id: uuid.UUID,
    winner_id: uuid.UUID,
    loser_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    """Record match result: set winner, propagate, ELO update, duel record.

    All on the caller's session — no background tasks, no connection pool issues.
    Frontend does optimistic updates so the user doesn't wait.
    """
    now = datetime.now(timezone.utc)

    # Mark winner + propagate
    match_obj = (await db.execute(
        select(TournamentMatch).where(TournamentMatch.id == match_id)
    )).scalar_one()
    match_obj.winner_movie_id = winner_id
    match_obj.played_at = now

    round_num = match_obj.round
    num_rounds = _num_rounds(bracket_size)

    if round_num < num_rounds:
        next_pos = match_obj.position // 2
        next_match = (await db.execute(
            select(TournamentMatch).where(
                TournamentMatch.tournament_id == tournament_id,
                TournamentMatch.round == round_num + 1,
                TournamentMatch.position == next_pos,
            )
        )).scalar_one()
        if match_obj.position % 2 == 0:
            next_match.movie_a_id = winner_id
        else:
            next_match.movie_b_id = winner_id

    if round_num == num_rounds:
        t = (await db.execute(
            select(Tournament).where(Tournament.id == tournament_id)
        )).scalar_one()
        t.champion_movie_id = winner_id
        t.status = "completed"
        t.completed_at = now

    # ELO update + duel record (same session, 2 extra queries)
    um_w = (await db.execute(
        select(UserMovie).where(UserMovie.user_id == user_id, UserMovie.movie_id == winner_id)
    )).scalar_one()
    um_l = (await db.execute(
        select(UserMovie).where(UserMovie.user_id == user_id, UserMovie.movie_id == loser_id)
    )).scalar_one()

    w_elo = um_w.elo if um_w.elo is not None else get_initial_elo(um_w.seeded_elo)
    l_elo = um_l.elo if um_l.elo is not None else get_initial_elo(um_l.seeded_elo)
    new_w, new_l = update_elo(w_elo, l_elo, um_w.battles, um_l.battles)

    um_w.elo = new_w
    um_l.elo = new_l
    um_w.battles += 1
    um_l.battles += 1
    um_w.last_dueled_at = now
    um_l.last_dueled_at = now
    um_w.updated_at = now
    um_l.updated_at = now

    duel = Duel(
        user_id=user_id,
        winner_movie_id=winner_id,
        loser_movie_id=loser_id,
        winner_elo_before=w_elo,
        loser_elo_before=l_elo,
        winner_elo_after=new_w,
        loser_elo_after=new_l,
        mode="tournament",
    )
    db.add(duel)
    await db.flush()

    match_obj.duel_id = duel.id
    await db.flush()
