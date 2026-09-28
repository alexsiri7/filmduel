"""Checks for migration 026, which CI never runs through Alembic."""

from __future__ import annotations

import importlib.util
import pathlib

_migration_path = (
    pathlib.Path(__file__).parent.parent
    / "migrations"
    / "versions"
    / "026_add_pool_import_status.py"
)
_spec = importlib.util.spec_from_file_location("migration_026", _migration_path)
_migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_migration)


def test_revises_the_previous_head():
    assert _migration.revision == "026"
    assert _migration.down_revision == "025"
