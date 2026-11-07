"""Unit tests for backend/services/retention.py"""

from __future__ import annotations

import re
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from backend.db_models import Base, DuelHistory, TournamentMatch, User
from backend.services.retention import (
    purge_dormant_provider_tokens,
    purge_expired_screenshots,
    purge_old_duels,
    purge_old_feedback_reports,
    purge_old_suggestions,
    purge_old_swipe_results,
    purge_old_tournament_llm_responses,
    purge_unconsented_accounts,
)
from backend.services.token_crypto import TokenDecryptError


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


def _token_row(trakt="trakt-ct", simkl=None):
    return SimpleNamespace(
        id=uuid.uuid4(), trakt_access_token_enc=trakt, simkl_access_token_enc=simkl
    )


def _compiled(db, call=0):
    return str(
        db.execute.call_args_list[call][0][0].compile(dialect=postgresql.dialect())
    )


@pytest.fixture
def providers():
    """Patch the provider clients and decrypt each ciphertext to ``plain:<ct>``."""
    trakt, simkl = MagicMock(), MagicMock()
    trakt.return_value.revoke_token = AsyncMock()
    simkl.return_value.revoke_token = AsyncMock()

    def decrypt(ciphertext, *, purpose):
        if ciphertext == "bad-ct":
            raise TokenDecryptError("no key")
        return f"plain:{ciphertext}"

    with patch("backend.services.retention.TraktClient", trakt), \
         patch("backend.services.retention.SimklClient", simkl), \
         patch("backend.services.retention.decrypt_token", side_effect=decrypt):
        yield SimpleNamespace(
            trakt=trakt.return_value.revoke_token, simkl=simkl.return_value.revoke_token
        )


class TestPurgeUnconsentedAccounts:
    @pytest.mark.asyncio
    async def test_deletes_only_never_consented_dataless_idle_accounts(self, providers):
        db = _make_db([])
        await purge_unconsented_accounts(db)
        db.execute.assert_awaited_once()
        compiled = _compiled(db)
        assert compiled.startswith("DELETE FROM users")
        for clause in (
            "users.privacy_policy_accepted IS false",
            "users.privacy_policy_accepted_at IS NULL",
            "users.privacy_policy_version IS NULL",
            "users.pool_import_status IS NULL",
            "users.is_admin IS false",
            "users.created_at <",
            "users.last_seen_at <",
        ):
            assert clause in compiled

    @pytest.mark.asyncio
    async def test_keeps_accounts_with_rows_in_any_user_owned_table(self, providers):
        db = _make_db([])
        await purge_unconsented_accounts(db)
        compiled = _compiled(db)
        referencing = {
            fk.parent.table.name
            for table in Base.metadata.sorted_tables
            for fk in table.foreign_keys
            if fk.column is User.__table__.c.id
        }
        assert referencing
        for table in referencing:
            assert re.search(rf"NOT \(EXISTS \(SELECT \*\s+FROM {table}\b", compiled), table

    @pytest.mark.asyncio
    async def test_revokes_each_deleted_accounts_tokens(self, providers):
        db = AsyncMock()
        rows = [_token_row("t1"), _token_row(None, "s2"), _token_row("bad-ct")]
        db.execute = AsyncMock(return_value=MagicMock(fetchall=MagicMock(return_value=rows)))
        count = await purge_unconsented_accounts(db)
        assert count == 3
        providers.trakt.assert_awaited_once()
        assert providers.trakt.await_args.args == ("plain:t1",)
        providers.simkl.assert_awaited_once()
        assert providers.simkl.await_args.args == ("plain:s2",)

    @pytest.mark.asyncio
    async def test_returns_zero_when_nothing_to_delete(self, providers):
        assert await purge_unconsented_accounts(_make_db([])) == 0
        providers.trakt.assert_not_awaited()


class TestPurgeDormantProviderTokens:
    @pytest.mark.asyncio
    async def test_selects_idle_accounts_with_tokens_skipping_unadopted_legacy_rows(
        self, providers
    ):
        db = _make_db([])
        await purge_dormant_provider_tokens(db)
        compiled = _compiled(db)
        assert "users.last_seen_at <" in compiled
        assert "FOR UPDATE" in compiled
        assert "users.trakt_uuid IS NOT NULL OR users.trakt_user_id IS NULL" in compiled
        assert "users.trakt_access_token IS NOT NULL" in compiled

    @pytest.mark.asyncio
    async def test_no_update_when_nothing_dormant(self, providers):
        db = _make_db([])
        assert await purge_dormant_provider_tokens(db) == 0
        db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_clears_only_token_columns_and_revokes(self, providers):
        rows = [_token_row("t1", "s1"), _token_row("t2")]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(fetchall=MagicMock(return_value=rows)))
        count = await purge_dormant_provider_tokens(db)
        assert count == 2
        assert db.execute.await_count == 2
        update_sql = _compiled(db, 1)
        assert update_sql.startswith("UPDATE users SET")
        set_clause = update_sql.split(" WHERE ")[0]
        assigned = set(re.findall(r"(\w+)=", set_clause))
        assert assigned == {
            "trakt_access_token",
            "trakt_refresh_token",
            "trakt_token_expires_at",
            "simkl_access_token",
            "simkl_refresh_token",
            "simkl_token_expires_at",
        }
        assert [c.args for c in providers.trakt.await_args_list] == [
            ("plain:t1",),
            ("plain:t2",),
        ]
        assert [c.args for c in providers.simkl.await_args_list] == [("plain:s1",)]
