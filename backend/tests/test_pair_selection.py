"""Tests for duel pair selection in services/pair_selection.py."""

import unittest.mock
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from backend.services.pair_selection import select_pair


def _make_user_movie(elo=None, battles=0, seeded_elo=None, movie_id=None, seen=True):
    """Create a mock UserMovie with a nested mock Movie."""
    um = MagicMock()
    um.elo = elo
    um.battles = battles
    um.seeded_elo = seeded_elo
    um.seen = seen
    um.movie_id = movie_id or uuid.uuid4()
    um.movie = MagicMock()
    return um


def _mock_db(films):
    """AsyncSession mock whose single query returns the given seen films."""
    db = AsyncMock()
    result = MagicMock()
    result.unique.return_value.scalars.return_value.all.return_value = films
    db.execute.return_value = result
    return db


class TestSelectPair:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("film_count", [0, 1])
    async def test_raises_when_fewer_than_two_seen_films(self, film_count):
        films = [_make_user_movie() for _ in range(film_count)]
        with pytest.raises(ValueError, match="Need more seen movies to duel"):
            await select_pair(_mock_db(films), uuid.uuid4(), None)

    @pytest.mark.asyncio
    async def test_query_filters_on_user_seen_and_media_type(self):
        uid = uuid.uuid4()
        db = _mock_db([_make_user_movie(), _make_user_movie()])
        await select_pair(db, uid, None, media_type="tv")

        stmt = db.execute.call_args[0][0]
        compiled = stmt.compile(dialect=postgresql.dialect())
        sql = str(compiled)
        assert "user_movies.user_id = " in sql
        assert "user_movies.seen IS " in sql
        assert "movies.media_type = " in sql
        params = compiled.params.values()
        assert uid in params
        assert "tv" in params

    @pytest.mark.asyncio
    async def test_query_is_uncapped_and_unordered(self):
        db = _mock_db([_make_user_movie(), _make_user_movie()])
        await select_pair(db, uuid.uuid4(), None)

        sql = str(db.execute.call_args[0][0].compile(dialect=postgresql.dialect()))
        assert "LIMIT" not in sql
        assert "ORDER BY" not in sql

    @pytest.mark.asyncio
    async def test_anchor_is_a_least_dueled_film(self):
        films = [
            _make_user_movie(elo=1000, battles=3),
            _make_user_movie(elo=1100, battles=0),
            _make_user_movie(elo=900, battles=5),
            _make_user_movie(elo=None, battles=0),
        ]
        for _ in range(50):
            anchor, challenger = await select_pair(_mock_db(films), uuid.uuid4(), None)
            assert anchor.battles == 0
            assert challenger is not anchor

    @pytest.mark.asyncio
    async def test_unranked_film_can_anchor(self):
        unranked = _make_user_movie(elo=None, battles=0)
        films = [_make_user_movie(elo=1000 + i, battles=2) for i in range(3)]
        films.append(unranked)
        anchor, _ = await select_pair(_mock_db(films), uuid.uuid4(), None)
        assert anchor is unranked

    @pytest.mark.asyncio
    async def test_challenger_drawn_from_closest_ratings(self):
        anchor = _make_user_movie(elo=None, seeded_elo=1200, battles=0)
        close = [
            _make_user_movie(elo=e, battles=1) for e in (1190, 1210, 1220, 1180, 1230)
        ]
        far = [_make_user_movie(elo=e, battles=1) for e in (1600, 400)]
        populations = []

        def capture(population):
            populations.append(list(population))
            return population[0]

        with unittest.mock.patch(
            "backend.services.pair_selection.random.choice", side_effect=capture
        ):
            a, b = await select_pair(
                _mock_db([far[0], *close, anchor, far[1]]), uuid.uuid4(), None
            )

        assert a is anchor
        assert populations[0] == [anchor]
        assert set(map(id, populations[1])) == set(map(id, close))
        assert b in close

    @pytest.mark.asyncio
    async def test_unranked_challenger_uses_default_elo(self, monkeypatch):
        monkeypatch.setattr(
            "backend.services.pair_selection.CLOSEST_CANDIDATES", 1
        )
        anchor = _make_user_movie(elo=1000, battles=0)
        unranked = _make_user_movie(elo=None, seeded_elo=None, battles=1)
        ranked = _make_user_movie(elo=1500, battles=1)
        a, b = await select_pair(
            _mock_db([ranked, anchor, unranked]), uuid.uuid4(), None
        )
        assert a is anchor
        assert b is unranked

    @pytest.mark.asyncio
    async def test_avoids_repeating_last_pair(self):
        x = _make_user_movie(elo=1000, battles=0)
        y = _make_user_movie(elo=1001, battles=1)
        z = _make_user_movie(elo=1400, battles=1)
        last = {str(x.movie_id), str(y.movie_id)}
        for _ in range(20):
            a, b = await select_pair(_mock_db([x, y, z]), uuid.uuid4(), last)
            assert a is x
            assert b is z

    @pytest.mark.asyncio
    async def test_repeats_last_pair_when_no_alternative(self):
        x = _make_user_movie(elo=1000, battles=0)
        y = _make_user_movie(elo=1001, battles=1)
        last = {str(x.movie_id), str(y.movie_id)}
        a, b = await select_pair(_mock_db([x, y]), uuid.uuid4(), last)
        assert (a, b) == (x, y)
