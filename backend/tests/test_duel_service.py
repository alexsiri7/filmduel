"""Tests for the duel service layer."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.duel import (
    MIN_SEEN_UNRANKED,
    MIN_TOTAL_SEEN,
    get_user_movie,
    process_duel,
    should_suggest_swipe,
)


def _make_user_movie(
    user_id: uuid.UUID,
    movie_id: uuid.UUID,
    elo: int | None = None,
    seeded_elo: int | None = None,
    battles: int = 0,
    seen: bool | None = None,
) -> MagicMock:
    """Build a mock UserMovie with sensible defaults."""
    um = MagicMock()
    um.user_id = user_id
    um.movie_id = movie_id
    um.elo = elo
    um.seeded_elo = seeded_elo
    um.battles = battles
    um.seen = seen
    um.last_dueled_at = None
    um.updated_at = datetime.now(timezone.utc)
    return um


def _make_fake_execute(
    um_a: MagicMock, um_b: MagicMock, seen_unranked: int = 5, total_seen: int = 20
):
    """Build a fake db.execute that dispatches by movie_id bound parameter."""
    movie_map = {
        um_a.movie_id: um_a,
        um_b.movie_id: um_b,
    }

    async def fake_execute(stmt):
        result = MagicMock()
        stmt_str = str(stmt)
        # Count queries (contain 'count')
        if "count" in stmt_str.lower():
            # Distinguish seen_unranked (battles == 0) from total_seen
            if "battles" in stmt_str.lower():
                result.scalar_one.return_value = seen_unranked
            else:
                result.scalar_one.return_value = total_seen
            return result
        # UserMovie select queries — match movie_id by UUID hex in rendered SQL.
        # This avoids fragile SQLAlchemy AST introspection that breaks on
        # internal layout changes.
        try:
            stmt_str = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        except Exception:
            stmt_str = str(stmt)
        for mid, um in movie_map.items():
            if str(mid).replace("-", "") in stmt_str.replace("-", ""):
                result.scalar_one_or_none.return_value = um
                return result
        raise AssertionError(
            f"No movie_id matched in rendered SQL. movie_map keys: {list(movie_map)}"
        )

    return fake_execute


# ---------------------------------------------------------------------------
# get_user_movie
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_user_movie_existing():
    """Returns existing UserMovie."""
    uid = uuid.uuid4()
    mid = uuid.uuid4()
    existing = _make_user_movie(uid, mid)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing

    db = AsyncMock()
    db.execute.return_value = mock_result

    um = await get_user_movie(db, uid, mid)
    assert um is existing


@pytest.mark.asyncio
async def test_get_user_movie_with_for_update():
    """Verify that for_update=True causes with_for_update() to be applied to the statement."""
    uid = uuid.uuid4()
    mid = uuid.uuid4()
    existing = _make_user_movie(uid, mid)

    captured_stmts = []

    async def capturing_execute(stmt):
        captured_stmts.append(stmt)
        result = MagicMock()
        result.scalar_one_or_none.return_value = existing
        return result

    db = AsyncMock()
    db.execute = capturing_execute

    um = await get_user_movie(db, uid, mid, for_update=True)
    assert um is existing
    assert len(captured_stmts) == 1
    from sqlalchemy.dialects import postgresql

    compiled = captured_stmts[0].compile(dialect=postgresql.dialect())
    assert "FOR UPDATE" in str(compiled).upper()


@pytest.mark.asyncio
async def test_get_user_movie_not_found():
    """Raises ValueError when UserMovie does not exist."""
    uid = uuid.uuid4()
    mid = uuid.uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    db = AsyncMock()
    db.execute.return_value = mock_result

    with pytest.raises(ValueError, match="Movie not in your pool"):
        await get_user_movie(db, uid, mid)


# ---------------------------------------------------------------------------
# process_duel — a_wins
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_duel_a_wins_elo():
    """Winner gets ELO increase, loser gets decrease for a_wins."""
    uid = uuid.uuid4()
    mid_a = uuid.uuid4()
    mid_b = uuid.uuid4()

    um_a = _make_user_movie(uid, mid_a, elo=1000, battles=5)
    um_b = _make_user_movie(uid, mid_b, elo=1000, battles=5)

    db = AsyncMock()
    db.execute = _make_fake_execute(um_a, um_b)

    result = await process_duel(db, uid, mid_a, mid_b, "a_wins", "discovery")

    assert result.api_result.movie_a_elo_delta > 0, "Winner A should gain ELO"
    assert result.api_result.movie_b_elo_delta < 0, "Loser B should lose ELO"
    # Equal-ELO K=32 matchup: expected delta ~16, bounded by [10, 32]
    assert 10 <= result.api_result.movie_a_elo_delta <= 32
    assert um_a.battles == 6
    assert um_b.battles == 6
    assert um_a.seen is True
    assert um_b.seen is True


@pytest.mark.asyncio
async def test_process_duel_a_wins_reversed_sort_order():
    """
    When movie_b_id sorts before movie_a_id in UUID order, um_a/um_b must still
    refer to the correct movies. This exercises the 'else' branch at duel.py:109-110.
    """
    uid = uuid.uuid4()
    # Force movie_b_id < movie_a_id lexicographically
    mid_b = uuid.UUID("00000000-0000-0000-0000-000000000001")
    mid_a = uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")

    um_a = _make_user_movie(uid, mid_a, elo=1000, battles=5)
    um_b = _make_user_movie(uid, mid_b, elo=1000, battles=5)

    db = AsyncMock()
    db.execute = _make_fake_execute(um_a, um_b)

    result = await process_duel(db, uid, mid_a, mid_b, "a_wins", "discovery")

    # A is the winner — must gain ELO regardless of UUID sort order
    assert result.api_result.movie_a_elo_delta > 0, "A (winner) should gain ELO"
    assert result.api_result.movie_b_elo_delta < 0, "B (loser) should lose ELO"
    assert um_a.seen is True
    assert um_b.seen is True
    assert um_a.battles == 6
    assert um_b.battles == 6


# ---------------------------------------------------------------------------
# process_duel — b_wins
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_duel_b_wins_elo():
    """Winner gets ELO increase, loser gets decrease for b_wins."""
    uid = uuid.uuid4()
    mid_a = uuid.uuid4()
    mid_b = uuid.uuid4()

    um_a = _make_user_movie(uid, mid_a, elo=1000, battles=5)
    um_b = _make_user_movie(uid, mid_b, elo=1000, battles=5)

    db = AsyncMock()
    db.execute = _make_fake_execute(um_a, um_b)

    result = await process_duel(db, uid, mid_a, mid_b, "b_wins", "discovery")

    assert result.api_result.movie_b_elo_delta > 0, "Winner B should gain ELO"
    assert result.api_result.movie_a_elo_delta < 0, "Loser A should lose ELO"
    assert um_a.battles == 6
    assert um_b.battles == 6


# ---------------------------------------------------------------------------
# Duel record creation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_duel_creates_duel_record():
    """A Duel ORM object is added to the session."""
    uid = uuid.uuid4()
    mid_a = uuid.uuid4()
    mid_b = uuid.uuid4()

    um_a = _make_user_movie(uid, mid_a, elo=1000, battles=3)
    um_b = _make_user_movie(uid, mid_b, elo=1000, battles=3)

    db = AsyncMock()
    db.execute = _make_fake_execute(um_a, um_b)

    await process_duel(db, uid, mid_a, mid_b, "a_wins", "ranked")

    # db.add is called for the Duel record
    assert db.add.called
    # Find the Duel object among add calls
    from backend.db_models import Duel

    duel_adds = [
        call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], Duel)
    ]
    assert len(duel_adds) == 1
    duel = duel_adds[0]
    assert duel.user_id == uid
    assert duel.winner_movie_id == mid_a
    assert duel.loser_movie_id == mid_b
    assert duel.mode == "ranked"


# ---------------------------------------------------------------------------
# next_action = "swipe" when seen_unranked < 3
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_next_action_swipe_when_few_seen_unranked():
    """next_action should be 'swipe' when seen_unranked count < 3."""
    uid = uuid.uuid4()
    mid_a = uuid.uuid4()
    mid_b = uuid.uuid4()

    um_a = _make_user_movie(uid, mid_a, elo=1000, battles=2)
    um_b = _make_user_movie(uid, mid_b, elo=1000, battles=2)

    db = AsyncMock()
    db.execute = _make_fake_execute(um_a, um_b, seen_unranked=2, total_seen=20)

    result = await process_duel(db, uid, mid_a, mid_b, "a_wins", "discovery")
    assert result.api_result.next_action == "swipe"


@pytest.mark.asyncio
async def test_next_action_duel_when_enough_seen_unranked():
    """next_action should be 'duel' when seen_unranked count >= 3."""
    uid = uuid.uuid4()
    mid_a = uuid.uuid4()
    mid_b = uuid.uuid4()

    um_a = _make_user_movie(uid, mid_a, elo=1000, battles=2)
    um_b = _make_user_movie(uid, mid_b, elo=1000, battles=2)

    db = AsyncMock()
    db.execute = _make_fake_execute(um_a, um_b, seen_unranked=10, total_seen=20)

    result = await process_duel(db, uid, mid_a, mid_b, "a_wins", "discovery")
    assert result.api_result.next_action == "duel"


# ---------------------------------------------------------------------------
# Seeded ELO fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_duel_uses_seeded_elo_when_no_elo():
    """When elo is None, initial ELO should come from seeded_elo."""
    uid = uuid.uuid4()
    mid_a = uuid.uuid4()
    mid_b = uuid.uuid4()

    um_a = _make_user_movie(uid, mid_a, elo=None, seeded_elo=1200, battles=0)
    um_b = _make_user_movie(uid, mid_b, elo=None, seeded_elo=800, battles=0)

    db = AsyncMock()
    db.execute = _make_fake_execute(um_a, um_b)

    result = await process_duel(db, uid, mid_a, mid_b, "a_wins", "discovery")

    # A (1200) beats B (800) — A should gain less since heavily favored
    assert result.api_result.movie_a_elo_delta > 0
    assert result.api_result.movie_b_elo_delta < 0
    # ELO values should be based on seeded_elo, not default 1000
    assert result.new_elo_a > 1200
    assert result.new_elo_b < 800


# ---------------------------------------------------------------------------
# process_duel — a_only outcome
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_duel_a_only_skips_elo():
    """a_only marks A as seen, B as unseen, no ELO change."""
    uid = uuid.uuid4()
    mid_a = uuid.uuid4()
    mid_b = uuid.uuid4()

    um_a = _make_user_movie(uid, mid_a, elo=1000, battles=5, seen=None)
    um_b = _make_user_movie(uid, mid_b, elo=1000, battles=5, seen=None)

    db = AsyncMock()
    db.execute = _make_fake_execute(um_a, um_b)

    result = await process_duel(db, uid, mid_a, mid_b, "a_only", "discovery")

    assert result.api_result.movie_a_elo_delta == 0
    assert result.api_result.movie_b_elo_delta == 0
    assert um_a.seen is True
    assert um_b.seen is False
    # Battles should NOT be incremented for non-competitive outcomes
    assert um_a.battles == 5
    assert um_b.battles == 5


# ---------------------------------------------------------------------------
# process_duel — b_only outcome
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_duel_b_only_skips_elo():
    """b_only marks B as seen, A as unseen, no ELO change."""
    uid = uuid.uuid4()
    mid_a = uuid.uuid4()
    mid_b = uuid.uuid4()

    um_a = _make_user_movie(uid, mid_a, elo=1000, battles=5, seen=None)
    um_b = _make_user_movie(uid, mid_b, elo=1000, battles=5, seen=None)

    db = AsyncMock()
    db.execute = _make_fake_execute(um_a, um_b)

    result = await process_duel(db, uid, mid_a, mid_b, "b_only", "discovery")

    assert result.api_result.movie_a_elo_delta == 0
    assert result.api_result.movie_b_elo_delta == 0
    assert um_a.seen is False
    assert um_b.seen is True
    assert um_a.battles == 5
    assert um_b.battles == 5


# ---------------------------------------------------------------------------
# process_duel — neither outcome
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_duel_neither_skips_elo():
    """neither marks both as unseen, no ELO change."""
    uid = uuid.uuid4()
    mid_a = uuid.uuid4()
    mid_b = uuid.uuid4()

    um_a = _make_user_movie(uid, mid_a, elo=1000, battles=5, seen=None)
    um_b = _make_user_movie(uid, mid_b, elo=1000, battles=5, seen=None)

    db = AsyncMock()
    db.execute = _make_fake_execute(um_a, um_b)

    result = await process_duel(db, uid, mid_a, mid_b, "neither", "discovery")

    assert result.api_result.movie_a_elo_delta == 0
    assert result.api_result.movie_b_elo_delta == 0
    assert um_a.seen is False
    assert um_b.seen is False
    # Battles should NOT be incremented for neither outcome
    assert um_a.battles == 5
    assert um_b.battles == 5


# ---------------------------------------------------------------------------
# process_duel — pair_type classification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pair_type_ranked_vs_ranked():
    """Both films with battles >= 1 should produce pair_type='ranked_vs_ranked'."""
    uid = uuid.uuid4()
    mid_a = uuid.uuid4()
    mid_b = uuid.uuid4()

    um_a = _make_user_movie(uid, mid_a, elo=1000, battles=3)
    um_b = _make_user_movie(uid, mid_b, elo=1000, battles=5)

    db = AsyncMock()
    db.execute = _make_fake_execute(um_a, um_b)

    await process_duel(db, uid, mid_a, mid_b, "a_wins", "ranked")

    from backend.db_models import Duel

    duel_adds = [
        call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], Duel)
    ]
    assert len(duel_adds) == 1
    assert duel_adds[0].pair_type == "ranked_vs_ranked"


@pytest.mark.asyncio
async def test_pair_type_ranked_vs_unranked():
    """One film with battles=0 should produce pair_type='ranked_vs_unranked'."""
    uid = uuid.uuid4()
    mid_a = uuid.uuid4()
    mid_b = uuid.uuid4()

    um_a = _make_user_movie(uid, mid_a, elo=1000, battles=3)
    um_b = _make_user_movie(uid, mid_b, elo=None, battles=0)

    db = AsyncMock()
    db.execute = _make_fake_execute(um_a, um_b)

    await process_duel(db, uid, mid_a, mid_b, "a_wins", "discovery")

    from backend.db_models import Duel

    duel_adds = [
        call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], Duel)
    ]
    assert len(duel_adds) == 1
    assert duel_adds[0].pair_type == "ranked_vs_unranked"


class TestShouldSuggestSwipe:
    """Boundary tests for the swipe-suggestion threshold function."""

    @pytest.mark.parametrize(
        "seen_unranked, total_seen, expected",
        [
            (0, 0, True),
            (MIN_SEEN_UNRANKED - 1, MIN_TOTAL_SEEN, True),
            (MIN_SEEN_UNRANKED, MIN_TOTAL_SEEN - 1, True),
            (MIN_SEEN_UNRANKED, MIN_TOTAL_SEEN, False),
            (MIN_SEEN_UNRANKED + 5, MIN_TOTAL_SEEN + 50, False),
            (0, MIN_TOTAL_SEEN + 50, True),
            (MIN_SEEN_UNRANKED + 5, 0, True),
        ],
    )
    def test_boundary_conditions(self, seen_unranked, total_seen, expected):
        assert should_suggest_swipe(seen_unranked, total_seen) is expected
