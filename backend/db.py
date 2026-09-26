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
    # Kept small: the database lives in schema `filmduel` of a Supabase project
    # shared with other apps, so its pooler connection budget is shared too.
    # Worst case per replica is 5 app connections + 1 for alembic (NullPool) at
    # startup. Nothing here pins a schema: the `filmduel` role's search_path
    # (filmduel, extensions) resolves every unqualified table name.
    pool_size=3,
    max_overflow=2,
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


async def try_acquire_xact_lock(db: AsyncSession, scope: str, key: uuid.UUID) -> bool:
    """Non-blocking variant of acquire_quota_lock for work that should be skipped,
    not queued, when another run for the same (scope, key) is in flight.

    Same transaction-scoped semantics (pg_try_advisory_xact_lock), so it is safe
    behind the PgBouncer transaction-mode pooler and released on commit/rollback.
    Returns True if this transaction now holds the lock, False if another does.
    """
    result = await db.execute(
        select(
            func.pg_try_advisory_xact_lock(
                func.hashtext(scope), func.hashtext(str(key))
            )
        )
    )
    return bool(result.scalar_one())
