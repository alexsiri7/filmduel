"""Tests for duel rejection logging and the rejection-spike alert (#648)."""

from __future__ import annotations

import logging

from backend.services import duel_rejections
from backend.services.duel_rejections import RejectionSpikeMonitor, record_duel_rejection


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _monitor(threshold=3, window=60.0):
    clock = FakeClock()
    return RejectionSpikeMonitor(threshold=threshold, window_seconds=window, clock=clock), clock


class TestRejectionSpikeMonitor:
    def test_alerts_when_threshold_reached(self):
        monitor, _ = _monitor(threshold=3)
        assert monitor.record() is None
        assert monitor.record() is None
        assert monitor.record() == 3

    def test_cooldown_suppresses_then_realerts(self):
        monitor, clock = _monitor(threshold=3, window=60.0)
        for _ in range(3):
            result = monitor.record()
        assert result == 3
        clock.now = 30.0
        assert monitor.record() is None
        assert monitor.record() is None

        clock.now = 61.0
        assert monitor.record() == 3

    def test_old_rejections_fall_out_of_window(self):
        monitor, clock = _monitor(threshold=3, window=60.0)
        monitor.record()
        monitor.record()
        clock.now = 61.0
        assert monitor.record() is None


class TestRecordDuelRejection:
    def test_logs_warning_with_reason(self, caplog, monkeypatch):
        monkeypatch.setattr(duel_rejections, "_monitor", _monitor(threshold=100)[0])
        with caplog.at_level(logging.WARNING, logger=duel_rejections.__name__):
            record_duel_rejection("invalid_pair_token", "user-1")
        [record] = caplog.records
        assert record.levelno == logging.WARNING
        assert record.getMessage() == "duel_rejected reason=invalid_pair_token user_id=user-1"

    def test_spike_logs_one_error(self, caplog, monkeypatch):
        monkeypatch.setattr(duel_rejections, "_monitor", _monitor(threshold=2)[0])
        with caplog.at_level(logging.WARNING, logger=duel_rejections.__name__):
            for _ in range(4):
                record_duel_rejection("missing_pair_token")
        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(errors) == 1
        assert errors[0].getMessage().startswith("duel_rejection_spike count=2")
