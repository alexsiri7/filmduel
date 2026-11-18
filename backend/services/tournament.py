"""Tournament bracket business logic."""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Select, delete, exists, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from backend.db_models import Movie, Tournament, TournamentMatch, UserMovie
from backend.schemas import FilterType
from backend.services.curator import CurationError, curate_tournament
from backend.services.duel import apply_elo_result, lock_user_movie_pair
from backend.services.quota import DailyQuota
from backend.services.ranking import InvalidFilterError, ranked_user_movies_stmt

logger = logging.getLogger(__name__)

MAX_TOURNAMENTS_PER_DAY = 100
MAX_REGENERATIONS = 3


async def _count_tournaments_since(
    db: AsyncSession, user_id: uuid.UUID, cutoff: datetime
) -> int:
    result = await db.execute(
        select(func.count()).where(
            Tournament.user_id == user_id,
            Tournament.created_at >= cutoff,
        )
    )
    return result.scalar_one()


# Per-user daily creation cap: prevents database bloat DoS (SEC-03).
TOURNAMENT_DAILY_QUOTA = DailyQuota(
    name="tournament_daily_cap",
    limit=MAX_TOURNAMENTS_PER_DAY,
    count_since=_count_tournaments_since,
    message=f"Daily tournament creation limit reached ({MAX_TOURNAMENTS_PER_DAY} per 24 hours). Please try again later.",
)


class TournamentRuleError(Exception):
    """A tournament lifecycle rule refused the requested operation."""


# ── AI curation orchestration ────────────────────────────────────────


CANDIDATE_POOL_FACTOR = 3


async def curate_and_select_films(
    user_movies: list[UserMovie],
    bracket_size: int,
    filter_type: Optional[FilterType],
    filter_value: Optional[str],
    theme_hint: str,
) -> tuple[list[UserMovie], dict]:
    """Build candidates, call LLM curation, validate and return selected films.

    Returns (selected_user_movies_sorted_by_elo, llm_result_dict).
    Raises CurationError if the LLM selects films outside the candidate pool or
    too few to fill the bracket.
    """
    candidate_pool = user_movies[: bracket_size * CANDIDATE_POOL_FACTOR]
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
        raise CurationError(f"AI selected films not in candidate pool: {invalid_ids}")

    film_id_set = set(llm_result["film_ids"])
    selected_ums = [um for um in candidate_pool if str(um.movie_id) in film_id_set]
    selected_ums.sort(key=lambda um: um.elo or 0, reverse=True)

    if len(selected_ums) * 2 < bracket_size:
        raise CurationError(
            f"AI selected only {len(selected_ums)} usable films "
            f"for a {bracket_size} bracket"
        )

    return selected_ums, llm_result


@dataclass(frozen=True)
class CurationBookkeeping:
    """Server state stored beside the LLM reply in ``Tournament.llm_response``."""

    theme_hint: str = ""
    regen_count: int = 0

    @classmethod
    def read(cls, tournament: Tournament) -> CurationBookkeeping:
        stored = (
            tournament.llm_response if isinstance(tournament.llm_response, dict) else {}
        )
        return cls(
            theme_hint=stored.get("_theme_hint", ""),
            regen_count=stored.get("_regen_count", 0),
        )

    def next_regeneration(self) -> CurationBookkeeping:
        return CurationBookkeeping(self.theme_hint, self.regen_count + 1)

    def stamp(self, llm_result: dict) -> dict:
        llm_result["_theme_hint"] = self.theme_hint
        if self.regen_count:
            llm_result["_regen_count"] = self.regen_count
        return llm_result


def apply_curation(
    tournament: Tournament, llm_result: dict, bookkeeping: CurationBookkeeping
) -> None:
    """Copy the LLM's bracket metadata onto the tournament and store the reply."""
    tournament.name = llm_result["name"]
    tournament.tagline = llm_result.get("tagline")
    tournament.theme_description = llm_result.get("theme_description")
    tournament.llm_response = bookkeeping.stamp(llm_result)


# ── Pure helpers ──────────────────────────────────────────────────────


BRACKET_SIZES = (8, 16, 32, 64)


def max_bracket_size(pool_count: int) -> int | None:
    """Largest offerable bracket for a pool of ``pool_count`` ranked films.

    A bracket may not exceed 2x the pool: standard seeding pairs seed ``a``
    with seed ``bracket_size + 1 - a``, and the lower seed of every pairing
    falls in ``1..bracket_size / 2``. Below that ratio some pairing has no
    real film on either side and can never be played.
    """
    return max((s for s in BRACKET_SIZES if s <= 2 * pool_count), default=None)


def ensure_pool_fills_bracket(bracket_size: int, pool_size: int) -> None:
    """Reject a bracket the pool cannot half-fill.

    Below 2x the pool, standard seeding produces round-1 pairings with no real
    film on either side — matches nothing can ever win, so the tournament can
    never complete.
    """
    max_size = max_bracket_size(pool_size)
    if max_size is None:
        raise TournamentRuleError(
            f"Need at least {BRACKET_SIZES[0] // 2} ranked films"
        )
    if bracket_size > max_size:
        raise TournamentRuleError(
            f"Bracket too large. Max {max_size} for {pool_size} films"
        )


def ensure_can_regenerate(tournament: Tournament) -> None:
    if tournament.status != "active":
        raise TournamentRuleError("Tournament is not active")
    if not tournament.is_ai_curated:
        raise TournamentRuleError("Only AI-curated tournaments can be regenerated")
    if any(m.winner_movie_id is not None and not m.is_bye for m in tournament.matches):
        raise TournamentRuleError("Cannot regenerate after matches have been played")
    if CurationBookkeeping.read(tournament).regen_count >= MAX_REGENERATIONS:
        raise TournamentRuleError(
            f"Maximum regeneration attempts ({MAX_REGENERATIONS}) reached"
        )


def ensure_can_abandon(tournament: Tournament) -> None:
    if tournament.status == "abandoned":
        raise TournamentRuleError("Tournament already abandoned")
    if tournament.status == "completed":
        raise TournamentRuleError("Cannot abandon a completed tournament")


def next_playable_match(tournament: Tournament) -> TournamentMatch | None:
    """The earliest unplayed match with both slots filled, in bracket order."""
    for match in sorted(tournament.matches, key=lambda m: (m.round, m.position)):
        if (
            match.movie_a_id is not None
            and match.movie_b_id is not None
            and match.winner_movie_id is None
        ):
            return match
    return None


def progress_label(tournament: Tournament) -> str:
    """Human-readable progress for the tournament list."""
    if tournament.status == "completed":
        return "Completed"
    if tournament.status == "abandoned":
        return "Abandoned"

    matches_by_round: dict[int, list[TournamentMatch]] = {}
    for m in tournament.matches:
        matches_by_round.setdefault(m.round, []).append(m)

    for rnd in sorted(matches_by_round):
        round_matches = matches_by_round[rnd]
        played = sum(1 for m in round_matches if m.winner_movie_id is not None)
        if played < len(round_matches):
            return f"Round {rnd} \u2014 {played}/{len(round_matches)} matches played"

    # All matches played (shouldn't normally reach here for active tournaments)
    last_round = max(matches_by_round, default=1)
    return f"Round {last_round} \u2014 0/0 matches played"


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
            (1, 16),
            (8, 9),
            (4, 13),
            (5, 12),
            (2, 15),
            (7, 10),
            (3, 14),
            (6, 11),
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


def _filtered_ranked_stmt(
    user_id: uuid.UUID,
    filter_type: Optional[FilterType],
    filter_value: Optional[str],
    media_type: str,
) -> Select:
    """Ranked films of this media_type, narrowed by an optional genre/decade.

    Genre matches case-insensitively. Raises InvalidFilterError for invalid decade format.
    """
    stmt = ranked_user_movies_stmt(user_id, media_type)
    if filter_type == "genre" and filter_value:
        genres = func.unnest(Movie.genres).table_valued("name").render_derived(
            name="genre"
        )
        stmt = stmt.where(
            exists(
                select(literal_column("1"))
                .select_from(genres)
                .where(func.lower(genres.c.name) == filter_value.lower())
            )
        )
    elif filter_type == "decade" and filter_value:
        decade_str = filter_value.rstrip("s")
        try:
            decade_start = int(decade_str)
        except ValueError:
            raise InvalidFilterError("Invalid decade format")
        stmt = stmt.where(Movie.year.between(decade_start, decade_start + 9))
    return stmt


async def get_filtered_ranked_films(
    db: AsyncSession,
    user_id: uuid.UUID,
    filter_type: Optional[FilterType] = None,
    filter_value: Optional[str] = None,
    *,
    media_type: str,
    limit: int,
) -> list[UserMovie]:
    """Return the top ``limit`` ranked films matching an optional genre/decade.

    Returns UserMovie list with .movie eagerly loaded, sorted by ELO desc.
    Raises InvalidFilterError for invalid decade format.
    """
    stmt = (
        _filtered_ranked_stmt(user_id, filter_type, filter_value, media_type)
        .options(joinedload(UserMovie.movie))
        .order_by(UserMovie.elo.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.unique().scalars().all())


async def count_filtered_ranked_films(
    db: AsyncSession,
    user_id: uuid.UUID,
    filter_type: Optional[FilterType] = None,
    filter_value: Optional[str] = None,
    *,
    media_type: str,
) -> int:
    """Count the ranked films matching an optional genre/decade.

    Raises InvalidFilterError for invalid decade format.
    """
    stmt = _filtered_ranked_stmt(
        user_id, filter_type, filter_value, media_type
    ).with_only_columns(func.count())
    result = await db.execute(stmt)
    return result.scalar() or 0


async def delete_bracket(db: AsyncSession, tournament_id: uuid.UUID) -> None:
    await db.execute(
        delete(TournamentMatch).where(TournamentMatch.tournament_id == tournament_id)
    )
    await db.flush()


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
    if actual_films * 2 < bracket_size:
        raise ValueError(
            f"Bracket size {bracket_size} needs at least {bracket_size // 2} films, "
            f"got {actual_films}"
        )
    num_byes = bracket_size - actual_films
    pairings = generate_seeded_bracket(bracket_size)
    num_rounds = _num_rounds(bracket_size)
    now = datetime.now(timezone.utc)

    logger.info(
        "bracket_created tournament_id=%s bracket_size=%d num_films=%d num_byes=%d num_rounds=%d",
        tournament_id,
        bracket_size,
        actual_films,
        num_byes,
        num_rounds,
    )

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
        matches_in_round = bracket_size // (2**round_num)
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
        r1_stmt = select(TournamentMatch).where(
            TournamentMatch.tournament_id == tournament_id,
            TournamentMatch.round == 1,
            TournamentMatch.is_bye.is_(True),
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
            _advance_winner_to_next_round(
                next_match_obj, bye_match.winner_movie_id, bye_match.position
            )

        await db.flush()


def _advance_winner_to_next_round(
    next_match: TournamentMatch,
    winner_movie_id: uuid.UUID,
    current_position: int,
) -> None:
    if current_position % 2 == 0:
        next_match.movie_a_id = winner_movie_id
    else:
        next_match.movie_b_id = winner_movie_id


def validate_match(
    tournament: Tournament, match_id: uuid.UUID, winner_id: uuid.UUID
) -> uuid.UUID:
    """Validate a match is playable. Returns the loser_id.

    Raises TournamentRuleError on validation failure.
    """
    if tournament.status != "active":
        raise TournamentRuleError("Tournament is not active")

    match = next((m for m in tournament.matches if m.id == match_id), None)
    if not match:
        raise TournamentRuleError("Match not found")
    if match.winner_movie_id is not None:
        raise TournamentRuleError("Match already played")
    if match.movie_a_id is None or match.movie_b_id is None:
        raise TournamentRuleError("Match is not ready to play")
    if winner_id not in (match.movie_a_id, match.movie_b_id):
        raise TournamentRuleError("Winner must be one of the two movies")

    return match.movie_b_id if winner_id == match.movie_a_id else match.movie_a_id


async def record_match_winner(
    db: AsyncSession,
    tournament_id: uuid.UUID,
    bracket_size: int,
    match_id: uuid.UUID,
    winner_id: uuid.UUID,
    loser_id: uuid.UUID,
    user_id: uuid.UUID,
) -> tuple[float, float]:
    """Record match result: set winner, propagate, ELO update, duel record.

    All on the caller's session — no background tasks, no connection pool issues.
    Frontend does optimistic updates so the user doesn't wait.

    Returns the winner's and loser's new ELO ratings as plain ints, which the
    caller uses to schedule the provider rating sync on a fresh session.
    """
    now = datetime.now(timezone.utc)

    # Mark winner + propagate (lock row to prevent double-submit)
    match_obj = (
        await db.execute(
            select(TournamentMatch)
            .where(TournamentMatch.id == match_id)
            .with_for_update()
        )
    ).scalar_one()
    if match_obj.winner_movie_id is not None:
        raise TournamentRuleError("Match already played")
    match_obj.winner_movie_id = winner_id
    match_obj.played_at = now

    logger.debug(
        "match_result tournament_id=%s match_id=%s winner=%s round=%d",
        tournament_id,
        match_id,
        winner_id,
        match_obj.round,
    )

    round_num = match_obj.round
    num_rounds = _num_rounds(bracket_size)

    if round_num < num_rounds:
        next_pos = match_obj.position // 2
        next_match = (
            await db.execute(
                select(TournamentMatch).where(
                    TournamentMatch.tournament_id == tournament_id,
                    TournamentMatch.round == round_num + 1,
                    TournamentMatch.position == next_pos,
                )
            )
        ).scalar_one()
        _advance_winner_to_next_round(next_match, winner_id, match_obj.position)

    if round_num == num_rounds:
        t = (
            await db.execute(select(Tournament).where(Tournament.id == tournament_id))
        ).scalar_one()
        t.champion_movie_id = winner_id
        t.status = "completed"
        t.completed_at = now
        logger.debug(
            "champion_crowned tournament_id=%s champion=%s", tournament_id, winner_id
        )

    # ELO update + duel record (same session, 2 extra queries)
    um_w, um_l = await lock_user_movie_pair(db, user_id, winner_id, loser_id)

    duel = await apply_elo_result(
        db, user_id, winner_id, loser_id, um_w, um_l, "tournament"
    )
    duel.pair_type = "ranked_vs_ranked"
    await db.flush()

    match_obj.duel_id = duel.id
    await db.flush()

    return um_w.elo, um_l.elo
