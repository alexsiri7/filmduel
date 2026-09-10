"""Tests for tournament service pure functions and bracket logic."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.tournament import (
    _num_rounds,
    create_tournament_bracket,
    curate_and_select_films,
    generate_seeded_bracket,
    get_filtered_ranked_films,
    max_bracket_size,
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
            # UserMovie lookups for ELO
            if "user_movie" in stmt_str.lower() or call_count in (3, 4):
                if call_count == 3:
                    result.scalar_one.return_value = um_w
                else:
                    result.scalar_one.return_value = um_l
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
            if call_count == 3:
                result.scalar_one.return_value = um_w
                return result
            if call_count == 4:
                result.scalar_one.return_value = um_l
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
        lookups = [match_obj, MagicMock(), um_w, um_l]

        async def fake_execute(stmt):
            result = MagicMock()
            result.scalar_one.return_value = lookups.pop(0)
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
