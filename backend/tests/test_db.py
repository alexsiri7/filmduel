"""Tests for backend.db primitives."""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests!!")

import pytest
from sqlalchemy.dialects import postgresql

from backend.db import acquire_quota_lock


@pytest.mark.asyncio
async def test_acquire_quota_lock_uses_transaction_scoped_advisory_lock():
    """The lock must be transaction-scoped: session-level pg_advisory_lock is unsafe
    behind the PgBouncer transaction-mode pooler."""
    db = AsyncMock()
    key = uuid.uuid4()

    await acquire_quota_lock(db, "some_scope", key)

    db.execute.assert_awaited_once()
    compiled = db.execute.await_args.args[0].compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "pg_advisory_xact_lock(" in sql
    assert "hashtext(" in sql
    assert "pg_advisory_lock(" not in sql
    assert set(compiled.params.values()) == {"some_scope", str(key)}
