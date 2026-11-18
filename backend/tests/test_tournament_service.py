"""Tests for tournament service pure functions and bracket logic."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from backend.db_models import Tournament, TournamentMatch
from backend.services.tournament import (
    MAX_REGENERATIONS,
    CurationBookkeeping,
    TournamentRuleError,
    _num_rounds,
    apply_curation,
    count_filtered_ranked_films,
    create_tournament_bracket,
    curate_and_select_films,
    ensure_can_abandon,
    ensure_can_regenerate,
    ensure_pool_fills_bracket,
    generate_seeded_bracket,
    get_filtered_ranked_films,
    max_bracket_size,
    next_playable_match,
    progress_label,
    validate_match,
)


class TestGetFilteredRankedFilmsSignature:
    """media_type must stay required and keyword-only.

    A default here is what let regeneration silently draw show tournaments from
    the movie pool; a reintroduced default has to fail loudly, not quietly.
    """

    def test_omitting_media_type_raises(self):
        with pytest.raises(TypeError):
            get_filtered_ranked_films(MagicMock(), uuid.uuid4(), None, None)

    def test_passing_media_type_positionally_raises(self):
        with pytest.raises(TypeError):
            get_filtered_ranked_films(MagicMock(), uuid.uuid4(), None, None, "movie")

    def test_omitting_limit_raises(self):
        with pytest.raises(TypeError):
            get_filtered_ranked_films(
                MagicMock(), uuid.uuid4(), None, None, media_type="movie"
            )


def _db_returning(user_movies=(), count=0):
    db = AsyncMock()
    result = MagicMock()
    result.unique.return_value.scalars.return_value.all.return_value = list(user_movies)
    result.scalar.return_value = count
    db.execute.return_value = result
    return db


def _compiled(db):
    return db.execute.await_args.args[0].compile(dialect=postgresql.dialect())


class TestGetFilteredRankedFilmsQuery:
    """Filtering, ordering and the limit run in SQL, not over the whole library."""

    @pytest.mark.asyncio
    async def test_orders_by_elo_desc_and_limits(self):
        films = [MagicMock(), MagicMock()]
        db = _db_returning(films)

        result = await get_filtered_ranked_films(
            db, uuid.uuid4(), media_type="show", limit=24
        )

        assert result == films
        compiled = _compiled(db)
        sql = str(compiled)
        assert "ORDER BY user_movies.elo DESC" in sql
        assert "LIMIT" in sql
        assert 24 in compiled.params.values()
        assert "show" in compiled.params.values()

    @pytest.mark.asyncio
    async def test_genre_matches_case_insensitively_in_sql(self):
        db = _db_returning()

        await get_filtered_ranked_films(
            db, uuid.uuid4(), "genre", "Science-Fiction", media_type="movie", limit=24
        )

        compiled = _compiled(db)
        sql = str(compiled)
        assert "EXISTS (SELECT 1" in sql
        assert "unnest(movies.genres) AS genre(name)" in sql
        assert "lower(genre.name) = " in sql
        assert "science-fiction" in compiled.params.values()

    @pytest.mark.asyncio
    async def test_decade_filters_year_range_in_sql(self):
        db = _db_returning()

        await get_filtered_ranked_films(
            db, uuid.uuid4(), "decade", "1990s", media_type="movie", limit=24
        )

        compiled = _compiled(db)
        assert "movies.year BETWEEN " in str(compiled)
        assert {1990, 1999} <= set(compiled.params.values())

    @pytest.mark.asyncio
    async def test_invalid_decade_raises_before_querying(self):
        db = _db_returning()

        with pytest.raises(ValueError, match="Invalid decade format"):
            await get_filtered_ranked_films(
                db, uuid.uuid4(), "decade", "abc", media_type="movie", limit=24
            )
        db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_count_uses_the_same_filters(self):
        db = _db_returning(count=7)

        count = await count_filtered_ranked_films(
            db, uuid.uuid4(), "genre", "Drama", media_type="movie"
        )

        assert count == 7
        compiled = _compiled(db)
        sql = str(compiled)
        assert sql.startswith("SELECT count(*)")
        assert "unnest(movies.genres)" in sql
        assert "drama" in compiled.params.values()


class TestGenerateSeededBracket:
    def test_bracket_size_8(self):
        result = generate_seeded_bracket(8)
        assert len(result) == 4
        # Standard 8-team seeding: 1v8, 4v5, 2v7, 3v6
        assert result == [(1, 8), (4, 5), (2, 7), (3, 6)]

    def test_bracket_size_16(self):
        result = generate_seeded_bracket(16)
        assert len(result) == 8
        # First match is always 1 vs 16
        assert result[0] == (1, 16)
        # All seeds 1-16 appear exactly once
        seeds = set()
        for a, b in result:
            seeds.add(a)
            seeds.add(b)
        assert seeds == set(range(1, 17))

    def test_bracket_size_32(self):
        result = generate_seeded_bracket(32)
        assert len(result) == 16
        # First match is always 1 vs 32
        assert result[0] == (1, 32)
        # All seeds 1-32 appear exactly once
        seeds = set()
        for a, b in result:
            seeds.add(a)
            seeds.add(b)
        assert seeds == set(range(1, 33))

    def test_bracket_size_2(self):
        assert generate_seeded_bracket(2) == [(1, 2)]

    def test_bracket_size_4(self):
        assert generate_seeded_bracket(4) == [(1, 4), (2, 3)]

    def test_bracket_size_64(self):
        result = generate_seeded_bracket(64)
        assert len(result) == 32
        seeds = set()
        for a, b in result:
            seeds.add(a)
            seeds.add(b)
        assert seeds == set(range(1, 65))

    def test_unsupported_size(self):
        with pytest.raises(ValueError, match="Unsupported bracket size"):
            generate_seeded_bracket(12)


class TestNumRounds:
    def test_size_2(self):
        assert _num_rounds(2) == 1

    def test_size_4(self):
        assert _num_rounds(4) == 2

    def test_size_8(self):
        assert _num_rounds(8) == 3

    def test_size_16(self):
        assert _num_rounds(16) == 4

    def test_size_32(self):
        assert _num_rounds(32) == 5

    def test_size_64(self):
        assert _num_rounds(64) == 6


# ---------------------------------------------------------------------------
# create_tournament_bracket — bye handling
# ---------------------------------------------------------------------------


def _make_seeded_film(movie_id=None, elo=1000):
    """Create a mock UserMovie for seeding tests."""
    um = MagicMock()
    um.movie_id = movie_id or uuid.uuid4()
    um.elo = elo
    return um


class TestCreateTournamentBracketWithByes:
    @pytest.mark.asyncio
    async def test_bracket_5_films_in_8_slots_creates_correct_matches(self):
        """5 films in an 8-slot bracket should create 4 round-1 matches and 3 byes."""
        tournament_id = uuid.uuid4()
        films = [_make_seeded_film(elo=1500 - i * 100) for i in range(5)]
        added_objects = []

        db = AsyncMock()
        db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

        # Mock the round-2 match lookup for bye propagation
        round2_matches = {}
        for pos in range(4):
            m = MagicMock()
            m.movie_a_id = None
            m.movie_b_id = None
            round2_matches[pos] = m

        async def fake_execute(stmt):
            stmt_str = str(stmt)
            result = MagicMock()
            if "round" in stmt_str and "is_bye" in stmt_str:
                # Return bye matches from round 1
                bye_matches = [
                    obj for obj in added_objects if getattr(obj, "is_bye", False)
                ]
                result.scalars.return_value.all.return_value = bye_matches
                return result
            # Round 2 position lookup
            for pos in range(4):
                if f"position == {pos}" in stmt_str or True:
                    pass
            result.scalar_one.return_value = round2_matches.get(0, MagicMock())
            return result

        db.execute = fake_execute

        await create_tournament_bracket(db, tournament_id, 8, films)

        from backend.db_models import TournamentMatch

        round1_matches = [
            obj
            for obj in added_objects
            if isinstance(obj, TournamentMatch) and obj.round == 1
        ]
        assert len(round1_matches) == 4

        bye_matches = [m for m in round1_matches if m.is_bye]
        real_matches = [m for m in round1_matches if not getattr(m, "is_bye", False)]
        assert len(bye_matches) == 3
        assert len(real_matches) == 1

    @pytest.mark.asyncio
    async def test_bracket_8_films_no_byes(self):
        """8 films in an 8-slot bracket should have zero byes."""
        tournament_id = uuid.uuid4()
        films = [_make_seeded_film() for _ in range(8)]
        added_objects = []

        db = AsyncMock()
        db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

        await create_tournament_bracket(db, tournament_id, 8, films)

        from backend.db_models import TournamentMatch

        round1_matches = [
            obj
            for obj in added_objects
            if isinstance(obj, TournamentMatch) and obj.round == 1
        ]
        bye_matches = [m for m in round1_matches if getattr(m, "is_bye", False)]
        assert len(bye_matches) == 0
        assert len(round1_matches) == 4

    @pytest.mark.asyncio
    async def test_bye_winner_has_correct_movie_id(self):
        """Bye match winner_movie_id should equal the present film's movie_id."""
        tournament_id = uuid.uuid4()
        films = [_make_seeded_film() for _ in range(5)]
        added_objects = []

        db = AsyncMock()
        db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

        # Simple mock for flush and execute (bye propagation queries)
        round2_mock = MagicMock()
        round2_mock.movie_a_id = None
        round2_mock.movie_b_id = None

        async def fake_execute(stmt):
            result = MagicMock()
            stmt_str = str(stmt)
            if "is_bye" in stmt_str:
                bye_matches = [
                    obj for obj in added_objects if getattr(obj, "is_bye", False)
                ]
                result.scalars.return_value.all.return_value = bye_matches
            else:
                result.scalar_one.return_value = round2_mock
            return result

        db.execute = fake_execute

        await create_tournament_bracket(db, tournament_id, 8, films)

        from backend.db_models import TournamentMatch

        bye_matches = [
            obj
            for obj in added_objects
            if isinstance(obj, TournamentMatch) and getattr(obj, "is_bye", False)
        ]
        for bm in bye_matches:
            assert bm.winner_movie_id is not None
            assert bm.winner_movie_id == bm.movie_a_id


# ---------------------------------------------------------------------------
# max_bracket_size — the 2x-pool invariant that keeps every pairing playable
# ---------------------------------------------------------------------------


class TestMaxBracketSize:
    def test_offerable_sizes_match_the_api_schema(self):
        """The cap may only ever return a size TournamentCreate accepts."""
        from typing import get_args

        from backend.schemas import TournamentCreate
        from backend.services.tournament import BRACKET_SIZES

        annotation = TournamentCreate.model_fields["bracket_size"].annotation
        assert get_args(annotation) == BRACKET_SIZES

    @pytest.mark.parametrize(
        "pool_count,expected",
        [(3, None), (4, 8), (7, 8), (8, 16), (9, 16), (16, 32), (32, 64), (64, 64)],
    )
    def test_largest_offerable_bracket(self, pool_count, expected):
        assert max_bracket_size(pool_count) == expected


class TestCreateTournamentBracketRejectsUnplayableBrackets:
    """A pool below half the bracket makes some pairing have no film at all."""

    @pytest.mark.asyncio
    async def test_rejects_pool_below_half_the_bracket(self):
        db = AsyncMock()
        db.add = MagicMock()

        with pytest.raises(ValueError, match="needs at least 4 films"):
            await create_tournament_bracket(
                db, uuid.uuid4(), 8, [_make_seeded_film() for _ in range(3)]
            )

        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_accepts_pool_at_exactly_half_the_bracket(self):
        """Every round-1 pairing still holds one real film at the boundary."""
        tournament_id = uuid.uuid4()
        films = [_make_seeded_film() for _ in range(4)]
        added_objects = []

        db = AsyncMock()
        db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

        round2_mock = MagicMock()
        round2_mock.movie_a_id = None
        round2_mock.movie_b_id = None

        async def fake_execute(stmt):
            result = MagicMock()
            if "is_bye" in str(stmt):
                result.scalars.return_value.all.return_value = [
                    obj for obj in added_objects if getattr(obj, "is_bye", False)
                ]
            else:
                result.scalar_one.return_value = round2_mock
            return result

        db.execute = fake_execute

        await create_tournament_bracket(db, tournament_id, 8, films)

        from backend.db_models import TournamentMatch

        round1_matches = [
            obj
            for obj in added_objects
            if isinstance(obj, TournamentMatch) and obj.round == 1
        ]
        assert len(round1_matches) == 4
        assert all(m.winner_movie_id is not None for m in round1_matches)


class TestCurateAndSelectFilmsRejectsThinSelections:
    @pytest.mark.asyncio
    async def test_duplicate_film_ids_collapsing_below_half_raise(self):
        """The LLM can name 8 ids that dedupe to 3 — the bracket would be unplayable."""
        films = [_make_seeded_film() for _ in range(8)]
        for um in films:
            um.movie.title = "Film"
            um.movie.year = 2000
            um.movie.genres = []
        chosen = [str(um.movie_id) for um in films[:3]]

        with patch(
            "backend.services.tournament.curate_tournament",
            new_callable=AsyncMock,
            return_value={"name": "T", "film_ids": chosen * 3},
        ):
            with pytest.raises(ValueError, match="only 3 usable films"):
                await curate_and_select_films(films, 8, None, None, "")


# ---------------------------------------------------------------------------
# validate_match
# ---------------------------------------------------------------------------


class TestValidateMatch:
    def test_rejects_already_played_match(self):
        """Should raise ValueError for a match that already has a winner."""
        match_id = uuid.uuid4()
        winner_id = uuid.uuid4()
        loser_id = uuid.uuid4()

        match = MagicMock()
        match.id = match_id
        match.movie_a_id = winner_id
        match.movie_b_id = loser_id
        match.winner_movie_id = winner_id  # already played

        tournament = MagicMock()
        tournament.status = "active"
        tournament.matches = [match]

        with pytest.raises(ValueError, match="already played"):
            validate_match(tournament, match_id, winner_id)

    def test_rejects_winner_not_in_match(self):
        """Should raise ValueError if winner_id is not movie_a or movie_b."""
        match_id = uuid.uuid4()
        movie_a = uuid.uuid4()
        movie_b = uuid.uuid4()
        wrong_winner = uuid.uuid4()

        match = MagicMock()
        match.id = match_id
        match.movie_a_id = movie_a
        match.movie_b_id = movie_b
        match.winner_movie_id = None

        tournament = MagicMock()
        tournament.status = "active"
        tournament.matches = [match]

        with pytest.raises(ValueError, match="must be one of"):
            validate_match(tournament, match_id, wrong_winner)

    def test_returns_loser_id(self):
        """Should return the loser_id when validation passes."""
        match_id = uuid.uuid4()
        movie_a = uuid.uuid4()
        movie_b = uuid.uuid4()

        match = MagicMock()
        match.id = match_id
        match.movie_a_id = movie_a
        match.movie_b_id = movie_b
        match.winner_movie_id = None

        tournament = MagicMock()
        tournament.status = "active"
        tournament.matches = [match]

        loser = validate_match(tournament, match_id, movie_a)
        assert loser == movie_b

    def test_rejects_match_with_an_unfilled_slot(self):
        """A future-round match whose second slot is empty is not playable yet."""
        match_id = uuid.uuid4()
        movie_a = uuid.uuid4()

        match = MagicMock()
        match.id = match_id
        match.movie_a_id = movie_a
        match.movie_b_id = None
        match.winner_movie_id = None

        tournament = MagicMock()
        tournament.status = "active"
        tournament.matches = [match]

        with pytest.raises(ValueError, match="not ready to play"):
            validate_match(tournament, match_id, movie_a)

    def test_rejects_inactive_tournament(self):
        """Should raise ValueError for a non-active tournament."""
        tournament = MagicMock()
        tournament.status = "completed"
        tournament.matches = []

        with pytest.raises(ValueError, match="not active"):
            validate_match(tournament, uuid.uuid4(), uuid.uuid4())


# ---------------------------------------------------------------------------
# TournamentSchema field exposure regression
# ---------------------------------------------------------------------------


class TestTournamentSchemaFields:
    def test_tournament_schema_does_not_expose_llm_response(self):
        """TournamentSchema must not surface internal LLM metadata."""
        from backend.schemas import TournamentSchema

        assert "llm_response" not in TournamentSchema.model_fields, (
            "llm_response must not be part of the public TournamentSchema"
        )


# ---------------------------------------------------------------------------
# record_match_winner — propagation and tournament completion
# ---------------------------------------------------------------------------


def _locked_movie_id(stmt):
    """The movie_id a UserMovie row-lock select targets, or None for other queries."""
    from backend.db_models import UserMovie

    if stmt.column_descriptions[0]["entity"] is not UserMovie:
        return None
    return stmt.compile().params["movie_id_1"]


class TestRecordMatchWinner:
    @pytest.mark.asyncio
    async def test_propagates_winner_to_next_round(self):
        """record_match_winner should propagate the winner into the next round match."""
        from backend.services.tournament import record_match_winner

        tournament_id = uuid.uuid4()
        match_id = uuid.uuid4()
        winner_id = uuid.uuid4()
        loser_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # Round 1 match (position 0) — should propagate to round 2
        match_obj = MagicMock()
        match_obj.winner_movie_id = None
        match_obj.round = 1
        match_obj.position = 0
        match_obj.id = match_id

        # Next round match (round 2, position 0)
        next_match = MagicMock()
        next_match.movie_a_id = None
        next_match.movie_b_id = None

        # Winner and loser UserMovies
        um_w = MagicMock()
        um_w.elo = 1000
        um_w.seeded_elo = None
        um_w.battles = 5
        um_l = MagicMock()
        um_l.elo = 1000
        um_l.seeded_elo = None
        um_l.battles = 5
        user_movies = {winner_id: um_w, loser_id: um_l}

        call_count = 0

        async def fake_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            stmt_str = str(stmt)
            if "with_for_update" in stmt_str.lower() or call_count == 1:
                # First call: match row lock
                if call_count <= 1:
                    result.scalar_one.return_value = match_obj
                    return result
            if call_count == 2:
                # Second call: next round match lookup
                result.scalar_one.return_value = next_match
                return result
            movie_id = _locked_movie_id(stmt)
            if movie_id is not None:
                result.scalar_one.return_value = user_movies[movie_id]
                return result
            result.scalar_one.return_value = MagicMock()
            return result

        db = AsyncMock()
        db.execute = fake_execute

        with patch(
            "backend.services.tournament.apply_elo_result",
            new_callable=AsyncMock,
        ) as mock_elo:
            mock_elo.return_value = MagicMock(id=uuid.uuid4())
            await record_match_winner(
                db, tournament_id, 4, match_id, winner_id, loser_id, user_id
            )

        # Winner propagated to next round (position 0 is even → movie_a)
        assert next_match.movie_a_id == winner_id
        assert match_obj.winner_movie_id == winner_id

    @pytest.mark.asyncio
    async def test_completes_tournament_on_final_match(self):
        """record_match_winner sets champion and status='completed' on the final round."""
        from backend.services.tournament import record_match_winner

        tournament_id = uuid.uuid4()
        match_id = uuid.uuid4()
        winner_id = uuid.uuid4()
        loser_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # Final round match (round 1 of a 2-player bracket)
        match_obj = MagicMock()
        match_obj.winner_movie_id = None
        match_obj.round = 1  # _num_rounds(2) == 1, so this is the final
        match_obj.position = 0
        match_obj.id = match_id

        # Tournament object for completion
        tournament_obj = MagicMock()
        tournament_obj.champion_movie_id = None
        tournament_obj.status = "active"
        tournament_obj.completed_at = None

        um_w = MagicMock()
        um_w.elo = 1000
        um_w.seeded_elo = None
        um_w.battles = 5
        um_l = MagicMock()
        um_l.elo = 1000
        um_l.seeded_elo = None
        um_l.battles = 5
        user_movies = {winner_id: um_w, loser_id: um_l}

        call_count = 0

        async def fake_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # Match row lock
                result.scalar_one.return_value = match_obj
                return result
            if call_count == 2:
                # Tournament lookup (for completion)
                result.scalar_one.return_value = tournament_obj
                return result
            movie_id = _locked_movie_id(stmt)
            if movie_id is not None:
                result.scalar_one.return_value = user_movies[movie_id]
                return result
            result.scalar_one.return_value = MagicMock()
            return result

        db = AsyncMock()
        db.execute = fake_execute

        with patch(
            "backend.services.tournament.apply_elo_result",
            new_callable=AsyncMock,
        ) as mock_elo:
            mock_elo.return_value = MagicMock(id=uuid.uuid4())
            # bracket_size=2 → _num_rounds(2)=1 → round 1 is final
            await record_match_winner(
                db, tournament_id, 2, match_id, winner_id, loser_id, user_id
            )

        assert tournament_obj.champion_movie_id == winner_id
        assert tournament_obj.status == "completed"


# ---------------------------------------------------------------------------
# record_match_winner — FD-040 parity with the standard duel pipeline
# ---------------------------------------------------------------------------


class TestRecordMatchWinnerEloParity:
    """The real ELO maths, unpatched: a tournament match must move ratings
    exactly as a regular duel does, and leave the duel row linked to the match."""

    @pytest.mark.asyncio
    async def test_matches_the_shared_elo_calculation_and_stores_the_duel(self):
        import types

        from backend.db_models import Duel
        from backend.services.elo import update_elo
        from backend.services.tournament import record_match_winner

        tournament_id = uuid.uuid4()
        match_id = uuid.uuid4()
        winner_id = uuid.uuid4()
        loser_id = uuid.uuid4()
        user_id = uuid.uuid4()

        match_obj = types.SimpleNamespace(
            id=match_id,
            round=1,
            position=0,
            winner_movie_id=None,
            played_at=None,
            duel_id=None,
        )
        um_w = types.SimpleNamespace(elo=1200, battles=10, seeded_elo=None)
        um_l = types.SimpleNamespace(elo=1100, battles=8, seeded_elo=None)
        added = []

        # bracket_size=2 → round 1 is the final, so the second lookup is the
        # tournament row rather than a next-round match.
        lookups = [match_obj, MagicMock()]
        user_movies = {winner_id: um_w, loser_id: um_l}

        async def fake_execute(stmt):
            result = MagicMock()
            movie_id = _locked_movie_id(stmt)
            result.scalar_one.return_value = (
                user_movies[movie_id] if movie_id is not None else lookups.pop(0)
            )
            return result

        async def assign_ids_like_a_real_flush():
            for obj in added:
                if isinstance(obj, Duel) and obj.id is None:
                    obj.id = uuid.uuid4()

        db = AsyncMock()
        db.execute = fake_execute
        db.add = MagicMock(side_effect=added.append)
        db.flush = AsyncMock(side_effect=assign_ids_like_a_real_flush)

        returned = await record_match_winner(
            db, tournament_id, 2, match_id, winner_id, loser_id, user_id
        )

        expected_w, expected_l = update_elo(1200, 1100, 10, 8)
        assert (um_w.elo, um_l.elo) == (expected_w, expected_l)
        assert returned == (expected_w, expected_l)
        assert (um_w.battles, um_l.battles) == (11, 9)

        duels = [obj for obj in added if isinstance(obj, Duel)]
        assert len(duels) == 1
        duel = duels[0]
        assert duel.mode == "tournament"
        assert duel.pair_type == "ranked_vs_ranked"
        assert (duel.winner_elo_before, duel.winner_elo_after) == (1200, expected_w)
        assert (duel.loser_elo_before, duel.loser_elo_after) == (1100, expected_l)

        assert duel.id is not None
        assert match_obj.duel_id == duel.id


class TestRecordMatchWinnerLockOrder:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("winner_is_lower_id", [True, False])
    async def test_locks_user_movies_in_movie_id_order_regardless_of_outcome(
        self, winner_is_lower_id
    ):
        """Matches over the same pair with opposite outcomes must lock the
        UserMovie rows in the same order, or concurrent calls can deadlock."""
        import types

        from backend.services.tournament import record_match_winner

        low_id, high_id = sorted([uuid.uuid4(), uuid.uuid4()])
        winner_id, loser_id = (
            (low_id, high_id) if winner_is_lower_id else (high_id, low_id)
        )
        user_id = uuid.uuid4()

        match_obj = types.SimpleNamespace(
            id=uuid.uuid4(),
            round=1,
            position=0,
            winner_movie_id=None,
            played_at=None,
            duel_id=None,
        )
        um_w = types.SimpleNamespace(elo=1200, battles=5, seeded_elo=None)
        um_l = types.SimpleNamespace(elo=1100, battles=5, seeded_elo=None)
        user_movies = {winner_id: um_w, loser_id: um_l}
        lookups = [match_obj, MagicMock()]
        locked = []

        async def fake_execute(stmt):
            result = MagicMock()
            movie_id = _locked_movie_id(stmt)
            if movie_id is None:
                result.scalar_one.return_value = lookups.pop(0)
            else:
                locked.append(movie_id)
                result.scalar_one.return_value = user_movies[movie_id]
            return result

        db = AsyncMock()
        db.execute = fake_execute

        with patch(
            "backend.services.tournament.apply_elo_result",
            new_callable=AsyncMock,
        ) as mock_elo:
            mock_elo.return_value = MagicMock(id=uuid.uuid4())
            await record_match_winner(
                db, uuid.uuid4(), 2, match_obj.id, winner_id, loser_id, user_id
            )

        assert locked == [low_id, high_id]
        mock_elo.assert_awaited_once_with(
            db, user_id, winner_id, loser_id, um_w, um_l, "tournament"
        )


# ---------------------------------------------------------------------------
# Lifecycle rules: in-memory Tournament/TournamentMatch, no database
# ---------------------------------------------------------------------------


def _match(round_num, position=0, *, a=True, b=True, winner=False, bye=False):
    movie_a_id = uuid.uuid4() if a else None
    return TournamentMatch(
        id=uuid.uuid4(),
        round=round_num,
        position=position,
        movie_a_id=movie_a_id,
        movie_b_id=uuid.uuid4() if b else None,
        winner_movie_id=movie_a_id if winner else None,
        is_bye=bye,
    )


def _tournament(*, status="active", matches=(), is_ai_curated=True, llm_response=None):
    return Tournament(
        id=uuid.uuid4(),
        name="T",
        bracket_size=8,
        status=status,
        is_ai_curated=is_ai_curated,
        llm_response=llm_response,
        matches=list(matches),
    )


class TestNextPlayableMatch:
    def test_skips_byes_and_played_matches_in_bracket_order(self):
        bye = _match(1, 0, b=False, winner=True, bye=True)
        played = _match(1, 1, winner=True)
        later = _match(2, 0)
        first = _match(1, 2)

        assert next_playable_match(_tournament(matches=[later, first, bye, played])) is first

    def test_skips_matches_with_an_empty_slot(self):
        waiting = _match(2, 0, b=False)

        assert next_playable_match(_tournament(matches=[waiting])) is None


class TestProgressLabel:
    @pytest.mark.parametrize(
        "status, label", [("completed", "Completed"), ("abandoned", "Abandoned")]
    )
    def test_terminal_statuses_get_fixed_labels(self, status, label):
        assert progress_label(_tournament(status=status, matches=[_match(1)])) == label

    def test_round_1_partially_played(self):
        matches = [_match(1, 0, winner=True), _match(1, 1), _match(1, 2)]
        assert progress_label(_tournament(matches=matches)) == (
            "Round 1 — 1/3 matches played"
        )

    def test_round_1_complete_round_2_in_progress(self):
        matches = [_match(1, 0, winner=True), _match(1, 1, winner=True), _match(2, 0)]
        assert progress_label(_tournament(matches=matches)) == (
            "Round 2 — 0/1 matches played"
        )

    def test_empty_matches_list(self):
        assert progress_label(_tournament()) == "Round 1 — 0/0 matches played"

    def test_all_rounds_complete(self):
        matches = [_match(1, 0, winner=True), _match(2, 0, winner=True)]
        assert "Round 2" in progress_label(_tournament(matches=matches))


class TestEnsureCanAbandon:
    def test_allows_an_active_tournament(self):
        ensure_can_abandon(_tournament())

    @pytest.mark.parametrize(
        "status, message",
        [
            ("abandoned", "Tournament already abandoned"),
            ("completed", "Cannot abandon a completed tournament"),
        ],
    )
    def test_rejects_terminal_statuses(self, status, message):
        with pytest.raises(TournamentRuleError, match=f"^{message}$"):
            ensure_can_abandon(_tournament(status=status))


class TestEnsureCanRegenerate:
    def test_allows_a_fresh_ai_tournament_with_only_byes_played(self):
        bye = _match(1, 0, b=False, winner=True, bye=True)
        ensure_can_regenerate(
            _tournament(
                matches=[bye, _match(1, 1)],
                llm_response={"_regen_count": MAX_REGENERATIONS - 1},
            )
        )

    @pytest.mark.parametrize(
        "kwargs, message",
        [
            ({"status": "completed"}, "Tournament is not active"),
            ({"is_ai_curated": False}, "Only AI-curated tournaments can be regenerated"),
            (
                {"matches": [_match(1, winner=True)]},
                "Cannot regenerate after matches have been played",
            ),
            (
                {"llm_response": {"_regen_count": MAX_REGENERATIONS}},
                r"Maximum regeneration attempts \(3\) reached",
            ),
        ],
    )
    def test_rejects(self, kwargs, message):
        with pytest.raises(TournamentRuleError, match=f"^{message}$"):
            ensure_can_regenerate(_tournament(**kwargs))


class TestEnsurePoolFillsBracket:
    def test_rejects_a_pool_too_small_for_any_bracket(self):
        with pytest.raises(TournamentRuleError, match="^Need at least 4 ranked films$"):
            ensure_pool_fills_bracket(8, 3)

    def test_rejects_a_bracket_larger_than_twice_the_pool(self):
        with pytest.raises(TournamentRuleError, match="^Bracket too large. Max 8 for 5 films$"):
            ensure_pool_fills_bracket(16, 5)

    def test_allows_a_half_filled_bracket(self):
        ensure_pool_fills_bracket(16, 8)


class TestCurationBookkeeping:
    def test_reads_defaults_from_a_missing_response(self):
        assert CurationBookkeeping.read(_tournament()) == CurationBookkeeping("", 0)

    def test_regeneration_keeps_the_theme_hint_and_counts_up(self):
        tournament = _tournament(llm_response={"_theme_hint": "Noir", "_regen_count": 1})
        apply_curation(
            tournament,
            {"name": "New", "tagline": "t", "theme_description": "d"},
            CurationBookkeeping.read(tournament).next_regeneration(),
        )

        assert tournament.name == "New"
        assert tournament.llm_response["_theme_hint"] == "Noir"
        assert tournament.llm_response["_regen_count"] == 2

    def test_first_curation_stores_only_the_theme_hint(self):
        assert CurationBookkeeping("Noir").stamp({"name": "N"}) == {
            "name": "N",
            "_theme_hint": "Noir",
        }
