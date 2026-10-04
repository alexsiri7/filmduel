"""Logging and spike alerting for rejected duel submissions (#648).

A frontend that stopped sending ``pair_token`` had every duel rejected for three
months without anyone noticing (#647). Every rejection path now funnels through
``record_duel_rejection`` so the failures are visible and a burst of them alerts.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable

logger = logging.getLogger(__name__)

# Stale pair tokens (past PAIR_TOKEN_TTL_SECONDS) cause occasional rejections;
# ten within the window on this small, single-process app means the flow is broken.
SPIKE_THRESHOLD = 10
# Also the alert cooldown, so an ongoing outage alerts at most once per window.
SPIKE_WINDOW_SECONDS = 300


class RejectionSpikeMonitor:
    """Sliding-window counter that reports once when rejections cross a threshold.

    No lock: ``record`` never awaits, so on the single asyncio loop it cannot
    interleave with itself.
    """

    def __init__(
        self,
        threshold: int = SPIKE_THRESHOLD,
        window_seconds: float = SPIKE_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.threshold = threshold
        self.window_seconds = window_seconds
        self._clock = clock
        self._timestamps: deque[float] = deque()
        self._last_alert: float | None = None

    def record(self) -> int | None:
        """Count one rejection; return the window's count if an alert is due."""
        now = self._clock()
        self._timestamps.append(now)
        while now - self._timestamps[0] > self.window_seconds:
            self._timestamps.popleft()
        count = len(self._timestamps)
        if count < self.threshold:
            return None
        if self._last_alert is not None and now - self._last_alert < self.window_seconds:
            return None
        self._last_alert = now
        return count


_monitor = RejectionSpikeMonitor()


def record_duel_rejection(reason: str, user_id: object | None = None) -> None:
    """Log a rejected duel at WARNING and raise an ERROR when rejections spike.

    The ERROR is what reaches Sentry (via the SDK's default LoggingIntegration)
    and so drives the alert. Never pass movie IDs or the outcome: a user ID paired
    with preference data must stay at DEBUG (SEC-15, see tests/test_log_levels.py).
    """
    logger.warning("duel_rejected reason=%s user_id=%s", reason, user_id)
    count = _monitor.record()
    if count is not None:
        logger.error(
            "duel_rejection_spike count=%d window_seconds=%d",
            count,
            _monitor.window_seconds,
        )
