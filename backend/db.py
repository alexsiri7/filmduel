"""Async SQLAlchemy engine and session factory."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    # Supabase pooler (PgBouncer transaction mode) doesn't support prepared statements
    connect_args={"statement_cache_size": 0, "prepared_statement_cache_size": 0},
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    """FastAPI dependency that yields an async database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def acquire_quota_lock(db: AsyncSession, scope: str, key: uuid.UUID) -> None:
    """Serialize a count-then-act quota check for `key` within `scope`.

    Takes a transaction-scoped advisory lock (pg_advisory_xact_lock), so it is
    safe behind the PgBouncer transaction-mode pooler and is released
    automatically when get_db() commits or rolls back. Concurrent requests for
    the same (scope, key) queue here; once the first commits, the next one's
    count query sees the committed rows and rejects at the cap.

    Relies on the engine running at Postgres's default READ COMMITTED isolation:
    the count statement issued after this call must take a fresh snapshot.
    """
    await db.execute(
        select(func.pg_advisory_xact_lock(func.hashtext(scope), func.hashtext(str(key))))
    )
