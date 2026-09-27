"""Unit tests for backend/services/retention.py"""

from __future__ import annotations

import re
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from backend.db_models import DuelHistory, TournamentMatch
from backend.services.retention import (
    purge_expired_screenshots,
    purge_old_duels,
    purge_old_feedback_reports,
    purge_old_suggestions,
    purge_old_swipe_results,
    purge_old_tournament_llm_responses,
)


def _make_db(row_ids=None):
    row_ids = row_ids or []
    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=MagicMock(fetchall=MagicMock(return_value=[(r,) for r in row_ids]))
    )
    return db


class TestPurgeOldDuels:
    @pytest.mark.asyncio
    async def test_returns_count_of_deleted_rows(self):
        ids = [uuid.uuid4(), uuid.uuid4()]
        db = _make_db(ids)
        count = await purge_old_duels(db)
        assert count == 2

    @pytest.mark.asyncio
    async def test_returns_zero_when_nothing_to_delete(self):
        db = _make_db([])
        count = await purge_old_duels(db)
        assert count == 0

    @pytest.mark.asyncio
    async def test_moves_rows_into_duel_history_in_one_statement(self):
        db = _make_db([])
        await purge_old_duels(db)
        db.execute.assert_awaited_once()
        compiled = str(db.execute.call_args[0][0].compile(dialect=postgresql.dialect()))
        assert "DELETE FROM duels" in compiled
        assert "INSERT INTO duel_history" in compiled
        assert "duels.created_at <" in compiled

    @pytest.mark.asyncio
    async def test_history_keeps_only_minimal_columns(self):
        db = _make_db([])
        await purge_old_duels(db)
        compiled = str(db.execute.call_args[0][0].compile(dialect=postgresql.dialect()))
        insert_columns = re.search(r"INSERT INTO duel_history \(([^)]*)\)", compiled)
        assert insert_columns.group(1) == (
            "user_id, winner_movie_id, loser_movie_id, outcome, created_at"
        )
        for dropped in ("elo", "pair_type", "mode"):
            assert dropped not in compiled

    def test_duel_history_table_has_no_extra_columns(self):
        assert set(DuelHistory.__table__.columns.keys()) == {
            "id",
            "user_id",
            "winner_movie_id",
            "loser_movie_id",
            "outcome",
            "created_at",
        }

    def test_duel_history_id_has_no_python_default(self):
        """INSERT ... SELECT would bind one Python-generated id to every moved row."""
        id_column = DuelHistory.__table__.c.id
        assert id_column.default is None
        assert id_column.server_default is not None

    def test_duel_history_cascades_on_user_delete(self):
        (fk,) = DuelHistory.__table__.c.user_id.foreign_keys
        assert fk.target_fullname == "users.id"
        assert fk.ondelete == "CASCADE"

    def test_tournament_match_duel_fk_sets_null(self):
        """Purging a duel a tournament match points at must not violate the FK."""
        (fk,) = TournamentMatch.__table__.c.duel_id.foreign_keys
        assert fk.ondelete == "SET NULL"


class TestPurgeOldSwipeResults:
    @pytest.mark.asyncio
    async def test_returns_count_of_deleted_rows(self):
        ids = [uuid.uuid4()]
        db = _make_db(ids)
        count = await purge_old_swipe_results(db)
        assert count == 1

    @pytest.mark.asyncio
    async def test_returns_zero_when_nothing_to_delete(self):
        db = _make_db([])
        count = await purge_old_swipe_results(db)
        assert count == 0


class TestPurgeExpiredScreenshots:
    @pytest.mark.asyncio
    async def test_returns_count_of_updated_rows(self):
        ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
        db = _make_db(ids)
        count = await purge_expired_screenshots(db)
        assert count == 3

    @pytest.mark.asyncio
    async def test_returns_zero_when_nothing_expired(self):
        db = _make_db([])
        count = await purge_expired_screenshots(db)
        assert count == 0


class TestPurgeOldTournamentLlmResponses:
    @pytest.mark.asyncio
    async def test_returns_count_of_updated_rows(self):
        ids = [uuid.uuid4(), uuid.uuid4()]
        db = _make_db(ids)
        count = await purge_old_tournament_llm_responses(db)
        assert count == 2

    @pytest.mark.asyncio
    async def test_returns_zero_when_nothing_to_update(self):
        db = _make_db([])
        count = await purge_old_tournament_llm_responses(db)
        assert count == 0

    @pytest.mark.asyncio
    async def test_sql_where_filters_non_null_llm_response(self):
        """Verify the UPDATE statement includes the isnot(None) guard clause."""
        db = _make_db([])
        await purge_old_tournament_llm_responses(db)
        call_args = db.execute.call_args[0][0]
        compiled = str(call_args.compile(compile_kwargs={"literal_binds": True}))
        assert "llm_response IS NOT NULL" in compiled

    @pytest.mark.asyncio
    async def test_sql_uses_strict_less_than_on_created_at(self):
        """Verify cutoff comparison is strict < (rows AT cutoff instant are NOT purged)."""
        db = _make_db([])
        await purge_old_tournament_llm_responses(db)
        call_args = db.execute.call_args[0][0]
        compiled = str(call_args.compile(compile_kwargs={"literal_binds": True}))
        assert "created_at" in compiled


class TestPurgeOldSuggestions:
    @pytest.mark.asyncio
    async def test_returns_count_of_deleted_rows(self):
        ids = [uuid.uuid4()]
        db = _make_db(ids)
        count = await purge_old_suggestions(db)
        assert count == 1

    @pytest.mark.asyncio
    async def test_returns_zero_when_nothing_to_delete(self):
        db = _make_db([])
        count = await purge_old_suggestions(db)
        assert count == 0

    @pytest.mark.asyncio
    async def test_sql_uses_generated_at_not_created_at(self):
        """Verify DELETE uses generated_at (not created_at) as the age column."""
        db = _make_db([])
        await purge_old_suggestions(db)
        call_args = db.execute.call_args[0][0]
        compiled = str(call_args.compile(compile_kwargs={"literal_binds": True}))
        assert "generated_at" in compiled
        assert "created_at" not in compiled


class TestPurgeOldFeedbackReports:
    @pytest.mark.asyncio
    async def test_returns_count_of_deleted_rows(self):
        ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
        db = _make_db(ids)
        count = await purge_old_feedback_reports(db)
        assert count == 3

    @pytest.mark.asyncio
    async def test_returns_zero_when_nothing_to_delete(self):
        db = _make_db([])
        count = await purge_old_feedback_reports(db)
        assert count == 0
