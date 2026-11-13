"""Tests for single-process lifecycle."""

from __future__ import annotations

import importlib.util

from fastapi.testclient import TestClient

from backend.ignite.api.app import create_app


def test_lifespan_starts_one_scheduler_and_one_runtime(runtime):
    app = create_app(runtime=runtime)
    with TestClient(app) as client:
        rt = app.state.runtime
        assert rt.scheduler.running is True
        assert len(rt.scheduler.get_jobs()) >= 3  # cycle + supervision + expiry
        assert client.get("/api/health").status_code == 200
    assert rt.scheduler.running is False


def test_no_worker_module():
    assert importlib.util.find_spec("backend.ignite.agent.worker") is None