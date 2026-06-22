"""Unit tests for backend/scheduler.py"""

from __future__ import annotations

import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests!!")

from backend.scheduler import build_scheduler


class TestBuildScheduler:
    def test_scheduler_has_one_job(self):
        scheduler = build_scheduler()
        jobs = scheduler.get_jobs()
        assert len(jobs) == 1

    def test_job_id_is_retention_purge(self):
        scheduler = build_scheduler()
        job = scheduler.get_jobs()[0]
        assert job.id == "retention_purge"

    def test_job_trigger_is_cron(self):
        scheduler = build_scheduler()
        job = scheduler.get_jobs()[0]
        assert job.trigger.__class__.__name__ == "CronTrigger"
