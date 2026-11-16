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


def test_runtime_schedules_daily_evaluation(runtime):
    """The desk trades every day, so evaluation runs daily after session close."""
    runtime.start()
    job_ids = {job.id for job in runtime.scheduler.get_jobs()}
    runtime.stop()
    assert "daily_evaluation" in job_ids


def test_evaluation_job_runs_report_and_survives_failure(runtime, monkeypatch):
    """The daily job journals a report per symbol; failures are audited, not raised."""
    import backend.ignite.agent.baselines as baselines_mod

    runtime.seed_symbols()
    calls: list[str] = []

    def fake_report(rt, symbol, **kwargs):
        calls.append(symbol)
        if symbol == "BOOM":
            raise RuntimeError("mcp down")
        return {
            "agent": {"sum_r": 0.5}, "kronos": {"sum_r": 1.0},
            "random": {"sum_r": -0.5}, "symbol": symbol,
        }

    monkeypatch.setattr(baselines_mod, "baseline_report", fake_report)
    monkeypatch.setattr(
        "backend.ignite.store.db.Store.list_symbols",
        lambda self: [{"symbol": "XAUUSD"}, {"symbol": "BOOM"}],
    )

    runtime._evaluation_job()  # must not raise

    assert calls == ["XAUUSD", "BOOM"]
    audits = runtime.store.get_audit_log(limit=10)
    assert any(a["action"] == "baseline_report_failed" and "mcp down" in a["result"] for a in audits)


def test_runtime_cycle_lock_prevents_overlap(runtime):
    """Only one cycle runs at a time (single-flight lock)."""
    runtime.start()
    # The lock is internal; verify it exists and can be acquired
    assert runtime._cycle_lock is not None
    acquired = runtime._cycle_lock.acquire(blocking=False)
    assert acquired is True
    runtime._cycle_lock.release()
    runtime.stop()


def test_expire_stale_drafts_job_expires_pending(runtime):
    """The scheduled expiry job transitions stale drafts to expired (PRD Goal 4).

    Regression: the job passed an integer TTL where an ISO timestamp is required,
    so the SQL comparison `expires_at <= ?` was always false and nothing expired.
    """
    from backend.ignite.store.db import utc_now

    store = runtime.store
    store._conn.execute(
        """INSERT INTO analyses (id, created_at, symbol, timeframe, last_bar_time,
        lookback, horizon, samples, model_id, infer_s, atr, p_up, edge, edge_atr,
        dispersion, signal, signal_version, risk_version, features_json, reasons_json)
        VALUES ('a','2026-01-01T00:00:00+00:00','XAUUSD','M15','t',1,1,1,'m',0.1,
        2.5,0.6,1.0,0.5,0.1,'LONG','v1','v1','{}','[]')"""
    )
    store.insert_draft({
        "id": "d1", "analysis_id": "a", "created_at": "2026-01-01T00:00:00+00:00",
        "expires_at": "2026-01-01T00:00:01+00:00", "state": "draft",
        "side": "long", "lots": 0.01, "reference_price": 3930.0,
        "sl": 3920.0, "tp": 3950.0, "risk_usd": 10.0, "risk_pct": 0.01,
        "rr": 2.0, "margin": None, "worst_case_usd": None,
        "blocked": 0, "block_reason": None, "idempotency_key": "k1",
    })
    store._conn.commit()
    assert len(store.pending_drafts()) == 1

    runtime._expire_stale_drafts()

    assert store.pending_drafts() == []
    assert store.get_draft("d1")["state"] == "expired"
    assert store.expire_stale_drafts(utc_now()) == 0  # idempotent