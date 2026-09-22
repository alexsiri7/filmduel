"""Shared pytest configuration for backend tests.

Sets required environment variables before any test module is imported,
so that pydantic-settings can build the Settings object at collection time.
The backend import below must stay after those assignments.

Also resets slowapi's in-memory counters around every test so per-route caps
don't leak between modules regardless of collection order.
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://localhost/ci_test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests!!")
# Assigned, not setdefault: the autouse limiter.reset() below raises when a
# RATE_LIMIT_STORAGE_URI exported in the shell (or in .env) points at a Redis
# that is not running, so the suite must always pin in-memory storage.
os.environ["RATE_LIMIT_STORAGE_URI"] = ""

# Popped, not left alone: with a platform var exported in the shell, the SEC-11
# fail-closed validator would abort Settings() at collection time (the default
# test BASE_URL is http://) — a confusing collection error instead of a test failure.
from backend.config import _PROXY_PLATFORM_ENV_VARS

for _var in _PROXY_PLATFORM_ENV_VARS:
    os.environ.pop(_var, None)

from unittest.mock import patch

import pytest

from backend.rate_limit import limiter


@pytest.fixture(autouse=True)
def _reset_limiter():
    """Reset slowapi in-memory counters between tests so per-route caps don't leak."""
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture(autouse=True)
def _no_real_scheduler():
    """Prevent TestClient(app)'s lifespan from starting a real APScheduler.

    backend.main builds one module-level `_scheduler` singleton shared by every
    TestClient(app) instantiation across the suite. Patching its start/shutdown
    here — rather than in backend.scheduler.build_scheduler — leaves
    test_scheduler.py (which builds its own scheduler via build_scheduler()
    directly, never through the app lifespan) unaffected.
    """
    from backend import main as _main

    with patch.object(_main._scheduler, "start"), patch.object(_main._scheduler, "shutdown"):
        yield
