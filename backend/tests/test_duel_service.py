"""Tests for the duel service layer."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.duel import get_or_create_user_movie, process_duel


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


# ---------------------------------------------------------------------------
# get_or_create_user_movie
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_create_existing():
    """Returns existing UserMovie without creating a new one."""
    uid = uuid.uuid4()
    mid = uuid.uuid4()
    existing = _make_user_movie(uid, mid)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing

    db = AsyncMock()
    db.execute.return_value = mock_result

    um = await get_or_create_user_movie(db, uid, mid)
    assert um is existing
    db.add.assert_not_called()
    db.flush.assert_not_called()


@pytest.mark.asyncio
async def test_get_or_create_new():
    """Creates a new UserMovie when none exists."""
    uid = uuid.uuid4()
    mid = uuid.uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    db = AsyncMock()
    db.execute.return_value = mock_result

    um = await get_or_create_user_movie(db, uid, mid)
    assert um.user_id == uid
    assert um.movie_id == mid
    db.add.assert_called_once()
    db.flush.assert_awaited_once()


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

    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        # First two calls: get_or_create for um_a and um_b
        if call_count == 1:
            result.scalar_one_or_none.return_value = um_a
            return result
        elif call_count == 2:
            result.scalar_one_or_none.return_value = um_b
            return result
        else:
            # seen_unranked count query
            result.scalar_one.return_value = 5
            return result

    db = AsyncMock()
    db.execute = fake_execute

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

    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = um_a
            return result
        elif call_count == 2:
            result.scalar_one_or_none.return_value = um_b
            return result
        else:
            result.scalar_one.return_value = 5
            return result

    db = AsyncMock()
    db.execute = fake_execute

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

    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = um_a
            return result
        elif call_count == 2:
            result.scalar_one_or_none.return_value = um_b
            return result
        else:
            result.scalar_one.return_value = 5
            return result

    db = AsyncMock()
    db.execute = fake_execute

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

    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = um_a
            return result
        elif call_count == 2:
            result.scalar_one_or_none.return_value = um_b
            return result
        else:
            # Return seen_unranked count of 2 (< 3)
            result.scalar_one.return_value = 2
            return result

    db = AsyncMock()
    db.execute = fake_execute

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

    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = um_a
            return result
        elif call_count == 2:
            result.scalar_one_or_none.return_value = um_b
            return result
        else:
            result.scalar_one.return_value = 10
            return result

    db = AsyncMock()
    db.execute = fake_execute

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

    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = um_a
            return result
        elif call_count == 2:
            result.scalar_one_or_none.return_value = um_b
            return result
        else:
            result.scalar_one.return_value = 5
            return result

    db = AsyncMock()
    db.execute = fake_execute

    result = await process_duel(db, uid, mid_a, mid_b, "a_wins", "discovery")

    # A (1200) beats B (800) — A should gain less since heavily favored
    assert result.api_result.movie_a_elo_delta > 0
    assert result.api_result.movie_b_elo_delta < 0
    # ELO values should be based on seeded_elo, not default 1000
    assert result.new_elo_a > 1200
    assert result.new_elo_b < 800
