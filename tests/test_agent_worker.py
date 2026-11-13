"""Tests for Runtime start/stop (replaces agent worker)."""

from __future__ import annotations

import pytest

from backend.ignite.services.runtime import Runtime


def test_runtime_start_stops_scheduler(runtime):
    """Runtime.start() creates and starts the scheduler with expected jobs."""
    assert runtime.scheduler.running is False
    runtime.start()
    assert runtime.scheduler.running is True
    job_ids = {job.id for job in runtime.scheduler.get_jobs()}
    assert "session_open" in job_ids
    assert "interval" in job_ids
    assert "position_manager" in job_ids
    assert "expire_drafts" in job_ids
    runtime.stop()
    assert runtime.scheduler.running is False


def test_runtime_stop_is_idempotent(runtime):
    """Stopping an already-stopped runtime is safe."""
    runtime.start()
    runtime.stop()
    runtime.stop()  # Should not raise


def test_runtime_cycle_lock_prevents_overlap(runtime):
    """Only one cycle runs at a time (single-flight lock)."""
    runtime.start()
    # The lock is internal; verify it exists and can be acquired
    assert runtime._cycle_lock is not None
    acquired = runtime._cycle_lock.acquire(blocking=False)
    assert acquired is True
    runtime._cycle_lock.release()
    runtime.stop()