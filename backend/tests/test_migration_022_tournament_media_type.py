"""Import-level checks for migration 022, which CI never runs through Alembic."""

from __future__ import annotations

import importlib.util
import pathlib

_migration_path = (
    pathlib.Path(__file__).parent.parent
    / "migrations"
    / "versions"
    / "022_add_tournament_media_type.py"
)
_spec = importlib.util.spec_from_file_location("migration_022", _migration_path)
_migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_migration)


class TestRevisionChain:
    def test_revision_id(self):
        assert _migration.revision == "022"

    def test_revises_the_previous_head(self):
        assert _migration.down_revision == "021"
