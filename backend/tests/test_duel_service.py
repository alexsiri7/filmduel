"""Tests for the duel service layer."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.duel import get_user_movie, process_duel


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


def _make_fake_execute(um_a: MagicMock, um_b: MagicMock, seen_unranked: int = 5, total_seen: int = 20):
    """Build a fake db.execute that dispatches by SQL statement content, not call order."""
    returned_a = False
    returned_b = False

    async def fake_execute(stmt):
        nonlocal returned_a, returned_b
        result = MagicMock()
        stmt_str = str(stmt)
        # Count queries (contain 'count')
        if "count" in stmt_str.lower():
            # Distinguish seen_unranked (battles == 0) from total_seen
            if "battles" in stmt_str.lower() or (not returned_a and "count" in stmt_str.lower()):
                result.scalar_one.return_value = seen_unranked
            else:
                result.scalar_one.return_value = total_seen
            return result
        # UserMovie select queries — return um_a first, then um_b
        if not returned_a:
            returned_a = True
            result.scalar_one_or_none.return_value = um_a
            return result
        if not returned_b:
            returned_b = True
            result.scalar_one_or_none.return_value = um_b
            return result
        # Fallback for any additional queries
        result.scalar_one.return_value = seen_unranked
        return result

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
    assert um_a.battles == 6
    assert um_b.battles == 6
    assert um_a.seen is True
    assert um_b.seen is True


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
        call.args[0]
        for call in db.add.call_args_list
        if isinstance(call.args[0], Duel)
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
        call.args[0]
        for call in db.add.call_args_list
        if isinstance(call.args[0], Duel)
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
        call.args[0]
        for call in db.add.call_args_list
        if isinstance(call.args[0], Duel)
    ]
    assert len(duel_adds) == 1
    assert duel_adds[0].pair_type == "ranked_vs_unranked"
