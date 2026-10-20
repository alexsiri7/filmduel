"""Tests for duel pair selection in services/pair_selection.py."""

import unittest.mock
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from backend.services.pair_selection import CLOSEST_CANDIDATES, select_pair


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


def _result(films):
    result = MagicMock()
    result.unique.return_value.scalars.return_value.first.return_value = (
        films[0] if films else None
    )
    result.unique.return_value.scalars.return_value.all.return_value = films
    return result


def _mock_db(anchor, challengers):
    """AsyncSession mock answering the anchor query, then the challenger query."""
    db = AsyncMock()
    db.execute.side_effect = [_result([anchor] if anchor else []), _result(challengers)]
    return db


def _sql(db, call):
    stmt = db.execute.await_args_list[call].args[0]
    return stmt.compile(dialect=postgresql.dialect())


class TestSelectPair:
    @pytest.mark.asyncio
    async def test_raises_when_no_seen_films(self):
        with pytest.raises(ValueError, match="Need more seen movies to duel"):
            await select_pair(_mock_db(None, []), uuid.uuid4(), None)

    @pytest.mark.asyncio
    async def test_raises_when_only_one_seen_film(self):
        db = _mock_db(_make_user_movie(), [])
        with pytest.raises(ValueError, match="Need more seen movies to duel"):
            await select_pair(db, uuid.uuid4(), None)

    @pytest.mark.asyncio
    async def test_queries_filter_on_user_seen_and_media_type(self):
        uid = uuid.uuid4()
        db = _mock_db(_make_user_movie(), [_make_user_movie()])
        await select_pair(db, uid, None, media_type="tv")

        for call in (0, 1):
            compiled = _sql(db, call)
            sql = str(compiled)
            assert "user_movies.user_id = " in sql
            assert "user_movies.seen IS " in sql
            assert "movies.media_type = " in sql
            params = compiled.params.values()
            assert uid in params
            assert "tv" in params

    @pytest.mark.asyncio
    async def test_anchor_query_picks_one_least_dueled_film_at_random(self):
        db = _mock_db(_make_user_movie(), [_make_user_movie()])
        await select_pair(db, uuid.uuid4(), None)

        sql = str(_sql(db, 0))
        assert "ORDER BY user_movies.battles, random()" in sql
        assert "LIMIT" in sql

    @pytest.mark.asyncio
    async def test_challenger_query_takes_closest_by_effective_elo(self):
        anchor = _make_user_movie(elo=None, seeded_elo=1200, battles=0)
        db = _mock_db(anchor, [_make_user_movie()])
        await select_pair(db, uuid.uuid4(), None)

        compiled = _sql(db, 1)
        sql = str(compiled)
        assert "user_movies.movie_id != " in sql
        assert (
            "ORDER BY abs(coalesce(user_movies.elo, user_movies.seeded_elo, "
            in sql
        )
        assert "LIMIT" in sql
        params = list(compiled.params.values())
        assert anchor.movie_id in params
        assert 1200 in params
        assert 1000 in params  # DEFAULT_ELO for a film with neither ELO
        assert CLOSEST_CANDIDATES in params

    @pytest.mark.asyncio
    async def test_challenger_drawn_at_random_from_fetched_candidates(self):
        anchor = _make_user_movie(elo=1000, battles=0)
        close = [_make_user_movie(elo=e, battles=1) for e in (990, 1010, 1020)]
        populations = []

        def capture(population):
            populations.append(list(population))
            return population[-1]

        with unittest.mock.patch(
            "backend.services.pair_selection.random.choice", side_effect=capture
        ):
            a, b = await select_pair(_mock_db(anchor, close), uuid.uuid4(), None)

        assert a is anchor
        assert populations == [close]
        assert b is close[-1]

    @pytest.mark.asyncio
    async def test_last_partner_is_not_demoted_when_anchor_is_new(self):
        anchor = _make_user_movie(elo=1000, battles=0)
        y = _make_user_movie(elo=1001, battles=1)
        z = _make_user_movie(elo=1002, battles=1)
        last = {str(y.movie_id), str(z.movie_id)}
        db = _mock_db(anchor, [y])

        _, b = await select_pair(db, uuid.uuid4(), last)

        assert b is y
        assert "CAST(user_movies.movie_id AS TEXT) IN" not in str(_sql(db, 1))

    @pytest.mark.asyncio
    async def test_avoids_repeating_last_pair(self):
        x = _make_user_movie(elo=1000, battles=0)
        y = _make_user_movie(elo=1001, battles=1)
        z = _make_user_movie(elo=1400, battles=1)
        last = {str(x.movie_id), str(y.movie_id)}
        for _ in range(20):
            db = _mock_db(x, [y, z])
            a, b = await select_pair(db, uuid.uuid4(), last)
            assert a is x
            assert b is z

        compiled = _sql(db, 1)
        assert "ORDER BY CAST(user_movies.movie_id AS TEXT) IN" in str(compiled)
        assert [str(y.movie_id)] in compiled.params.values()

    @pytest.mark.asyncio
    async def test_repeats_last_pair_when_no_alternative(self):
        x = _make_user_movie(elo=1000, battles=0)
        y = _make_user_movie(elo=1001, battles=1)
        last = {str(x.movie_id), str(y.movie_id)}
        a, b = await select_pair(_mock_db(x, [y]), uuid.uuid4(), last)
        assert (a, b) == (x, y)
