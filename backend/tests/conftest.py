"""Test configuration — stub heavy/external dependencies before module import."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock

# ---------------------------------------------------------------------------
# Stub asyncpg so backend.db can be imported without the real driver
# ---------------------------------------------------------------------------
if "asyncpg" not in sys.modules:
    asyncpg_stub = MagicMock()
    sys.modules["asyncpg"] = asyncpg_stub
    sys.modules["asyncpg.connection"] = asyncpg_stub

# ---------------------------------------------------------------------------
# Stub sentry_sdk to avoid initialisation side-effects
# ---------------------------------------------------------------------------
if "sentry_sdk" not in sys.modules:
    sentry_stub = MagicMock()
    sys.modules["sentry_sdk"] = sentry_stub
    sys.modules["sentry_sdk.integrations"] = sentry_stub
    sys.modules["sentry_sdk.integrations.fastapi"] = sentry_stub
    sys.modules["sentry_sdk.integrations.sqlalchemy"] = sentry_stub

# ---------------------------------------------------------------------------
# Override async_session_factory so it doesn't attempt a real DB connection
# ---------------------------------------------------------------------------
import importlib

# Force backend.db to be imported now (with asyncpg stubbed) so later imports
# of async_session_factory reference the same module object.
import backend.db  # noqa: E402  (must be after stubs)

_fake_ctx = MagicMock()
_fake_ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
_fake_ctx.__aexit__ = AsyncMock(return_value=False)
backend.db.async_session_factory = MagicMock(return_value=_fake_ctx)
