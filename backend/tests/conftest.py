"""Shared pytest configuration for backend tests.

Sets required environment variables before any test module is imported,
so that pydantic-settings can build the Settings object at collection time.
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://localhost/ci_test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests!!")
