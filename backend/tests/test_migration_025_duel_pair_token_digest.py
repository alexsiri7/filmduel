"""Checks for migration 025 and the replay guard it adds, which CI never runs
through Alembic or against Postgres."""

from __future__ import annotations

import importlib.util
import pathlib
import uuid
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.db_models import Duel

_migration_path = (
    pathlib.Path(__file__).parent.parent
    / "migrations"
    / "versions"
    / "025_add_duel_pair_token_digest.py"
)
_spec = importlib.util.spec_from_file_location("migration_025", _migration_path)
_migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_migration)


def test_revises_the_previous_head():
    assert _migration.revision == "025"
    assert _migration.down_revision == "024"


def test_upgrade_adds_a_unique_digest_column(monkeypatch):
    op = MagicMock()
    monkeypatch.setattr(_migration, "op", op)
    _migration.upgrade()

    (table, column), _ = op.add_column.call_args
    assert table == "duels"
    assert column.name == "pair_token_digest"
    assert column.nullable
    op.create_index.assert_called_once_with(
        "uq_duels_pair_token_digest", "duels", ["pair_token_digest"], unique=True
    )


def test_model_index_matches_the_migration():
    (index,) = [i for i in Duel.__table__.indexes if i.name == "uq_duels_pair_token_digest"]
    assert index.unique
    assert [c.name for c in index.columns] == ["pair_token_digest"]


@pytest.fixture
def duels_session():
    engine = sa.create_engine("sqlite://")
    Duel.__table__.create(engine)
    with Session(engine) as session:
        yield session


def _duel(digest):
    return Duel(user_id=uuid.uuid4(), mode="discovery", pair_token_digest=digest)


def test_a_consumed_pair_token_cannot_record_a_second_duel(duels_session):
    duels_session.add(_duel("abc"))
    duels_session.commit()

    duels_session.add(_duel("abc"))
    with pytest.raises(IntegrityError):
        duels_session.flush()


def test_duels_without_a_digest_do_not_collide(duels_session):
    duels_session.add_all([_duel(None), _duel(None)])
    duels_session.commit()
