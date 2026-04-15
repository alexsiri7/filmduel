"""Tests for tournament service pure functions and bracket logic."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.tournament import (
    _num_rounds,
    create_tournament_bracket,
    generate_seeded_bracket,
    validate_match,
)


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
                bye_matches = [obj for obj in added_objects if getattr(obj, "is_bye", False)]
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
            obj for obj in added_objects
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
            obj for obj in added_objects
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
                bye_matches = [obj for obj in added_objects if getattr(obj, "is_bye", False)]
                result.scalars.return_value.all.return_value = bye_matches
            else:
                result.scalar_one.return_value = round2_mock
            return result

        db.execute = fake_execute

        await create_tournament_bracket(db, tournament_id, 8, films)

        from backend.db_models import TournamentMatch
        bye_matches = [
            obj for obj in added_objects
            if isinstance(obj, TournamentMatch) and getattr(obj, "is_bye", False)
        ]
        for bm in bye_matches:
            assert bm.winner_movie_id is not None
            assert bm.winner_movie_id == bm.movie_a_id


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

    def test_rejects_inactive_tournament(self):
        """Should raise ValueError for a non-active tournament."""
        tournament = MagicMock()
        tournament.status = "completed"
        tournament.matches = []

        with pytest.raises(ValueError, match="not active"):
            validate_match(tournament, uuid.uuid4(), uuid.uuid4())
