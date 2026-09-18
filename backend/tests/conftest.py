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

import pytest

from backend.rate_limit import limiter


@pytest.fixture(autouse=True)
def _reset_limiter():
    """Reset slowapi in-memory counters between tests so per-route caps don't leak."""
    limiter.reset()
    yield
    limiter.reset()
