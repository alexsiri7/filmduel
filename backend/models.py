"""Backward-compatibility shim — import from db_models and schemas instead.

This file will be removed once all references are migrated.
"""

from backend.db_models import *  # noqa: F401, F403
from backend.schemas import *  # noqa: F401, F403
