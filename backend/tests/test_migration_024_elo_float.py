"""Import-level checks for migration 024, which CI never runs through Alembic."""

from __future__ import annotations

import importlib.util
import pathlib
from unittest.mock import MagicMock

import sqlalchemy as sa

_migration_path = (
    pathlib.Path(__file__).parent.parent / "migrations" / "versions" / "024_elo_float.py"
)
_spec = importlib.util.spec_from_file_location("migration_024", _migration_path)
_migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_migration)

ELO_COLUMNS = {
    ("user_movies", "elo"),
    ("duels", "winner_elo_before"),
    ("duels", "loser_elo_before"),
    ("duels", "winner_elo_after"),
    ("duels", "loser_elo_after"),
}


def _run(step, monkeypatch):
    op = MagicMock()
    monkeypatch.setattr(_migration, "op", op)
    step()
    return op.alter_column.call_args_list


class TestRevisionChain:
    def test_revision_id(self):
        assert _migration.revision == "024"

    def test_revises_the_previous_head(self):
        assert _migration.down_revision == "023"


def test_upgrade_makes_every_elo_column_float(monkeypatch):
    calls = _run(_migration.upgrade, monkeypatch)
    assert {c.args for c in calls} == ELO_COLUMNS
    assert len(calls) == len(ELO_COLUMNS)
    assert all(isinstance(c.kwargs["type_"], sa.Float) for c in calls)


def test_downgrade_rounds_every_elo_column_back_to_integer(monkeypatch):
    calls = _run(_migration.downgrade, monkeypatch)
    assert {c.args for c in calls} == ELO_COLUMNS
    assert len(calls) == len(ELO_COLUMNS)
    for c in calls:
        assert isinstance(c.kwargs["type_"], sa.Integer)
        assert "round(" in c.kwargs["postgresql_using"]
