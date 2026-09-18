"""Guard against behavioral personal data returning to INFO logs (SEC-15, #583).

A log line that pairs a user identifier with preference content — movie IDs, a duel
or swipe outcome, ELO/taste-profile values, declared seen/unseen counts, or a
ranking-derived next_action — must be emitted at DEBUG, not INFO, so it never lands
in production log sinks by default.
"""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_FILES = [
    REPO_ROOT / "backend" / "routers" / "duels.py",
    REPO_ROOT / "backend" / "services" / "duel.py",
    REPO_ROOT / "backend" / "routers" / "swipe.py",
    REPO_ROOT / "backend" / "services" / "suggest.py",
]
BEHAVIORAL_EVENTS = {
    "duel_submitted",
    "duel_processed",
    "duel_next_action",
    "swipe_band_selection",
    "swipe_submit",
    "suggest_taste_profile",
}


def _logger_calls(path: Path):
    """Yield (method, event_name, lineno) for every ``logger.<method>("event ...")``."""
    for node in ast.walk(ast.parse(path.read_text())):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "logger"
        ):
            continue
        fmt = node.args[0]
        if isinstance(fmt, ast.Constant) and isinstance(fmt.value, str):
            yield func.attr, fmt.value.split(" ", 1)[0], node.lineno


def test_behavioral_events_are_logged_at_debug():
    seen = set()
    for path in SOURCE_FILES:
        for method, event, lineno in _logger_calls(path):
            if event in BEHAVIORAL_EVENTS:
                seen.add(event)
                assert method == "debug", (
                    f"{path.relative_to(REPO_ROOT)}:{lineno} logs {event} via "
                    f"logger.{method}; behavioral personal data must use logger.debug"
                )
    assert seen == BEHAVIORAL_EVENTS, (
        f"events not found in source (renamed?): {BEHAVIORAL_EVENTS - seen}"
    )
