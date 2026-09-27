"""Import-level checks for migration 023, which CI never runs through Alembic."""

from __future__ import annotations

import importlib.util
import pathlib
from unittest.mock import MagicMock

import pytest

_migration_path = (
    pathlib.Path(__file__).parent.parent
    / "migrations"
    / "versions"
    / "023_add_duel_history.py"
)
_spec = importlib.util.spec_from_file_location("migration_023", _migration_path)
_migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_migration)


class TestRevisionChain:
    def test_revision_id(self):
        assert _migration.revision == "023"

    def test_revises_the_previous_head(self):
        assert _migration.down_revision == "022"


class TestUpgrade:
    @pytest.fixture
    def op(self, monkeypatch):
        op = MagicMock()
        monkeypatch.setattr(_migration, "op", op)
        _migration.upgrade()
        return op

    def test_adds_outcome_to_duels(self, op):
        table, column = op.add_column.call_args.args
        assert table == "duels"
        assert column.name == "outcome"
        assert column.nullable

    def test_creates_duel_history_cascading_on_user_delete(self, op):
        name, *columns = op.create_table.call_args.args
        assert name == "duel_history"
        (user_id,) = [c for c in columns if c.name == "user_id"]
        (fk,) = user_id.foreign_keys
        assert fk.target_fullname == "users.id"
        assert fk.ondelete == "CASCADE"

    def test_tournament_duel_fk_sets_null(self, op):
        op.drop_constraint.assert_called_once_with(
            "tournament_matches_duel_id_fkey", "tournament_matches", type_="foreignkey"
        )
        args = op.create_foreign_key.call_args
        assert args.args[:3] == (
            "tournament_matches_duel_id_fkey",
            "tournament_matches",
            "duels",
        )
        assert args.kwargs["ondelete"] == "SET NULL"
