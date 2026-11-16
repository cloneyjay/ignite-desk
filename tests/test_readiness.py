"""Tests for live readiness validator."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from backend.ignite.services.readiness import ReadinessService, ReadinessReport, CheckResult


def test_readiness_all_green(rt):
    """All checks pass when all subsystems are healthy."""
    rt.config_service.update({"operating_mode": "autonomous", "execution_mode": "live"})
    report = ReadinessService(rt).check()
    assert report.ready is True
    assert all(c.ok for c in report.checks.values())


def test_readiness_kronos_down(rt):
    """Readiness fails when Kronos is down."""
    rt.forecast.health_override = {"ready": False, "model": "fake-kronos", "load_s": 0.1, "threads": 2}
    report = ReadinessService(rt).check()
    assert report.ready is False
    assert not report.checks["kronos"].ok


def test_readiness_mcp_unreachable(rt):
    """Readiness fails when MCP is unreachable."""
    with patch.object(rt, '_call', side_effect=Exception("MCP unreachable")):
        report = ReadinessService(rt).check()
        assert report.ready is False
        assert not report.checks["mcp"].ok


def test_readiness_kill_switch_on(rt):
    """Readiness fails when kill switch is engaged."""
    rt.store.set_kill_switch(True)
    report = ReadinessService(rt).check()
    assert report.ready is False
    assert not report.checks["kill_switch"].ok


def test_readiness_daily_loss_breached(rt):
    """Readiness fails when daily loss limit is breached."""
    rt.realised_override = -10000.0
    report = ReadinessService(rt).check()
    assert report.ready is False
    assert not report.checks["daily_loss"].ok


def test_readiness_positions_over_limit(rt):
    """Readiness fails when position limits are exceeded."""
    # Add positions that exceed max_concurrent_positions
    for i in range(15):
        rt.mcp.positions.append({
            "position_id": str(i),
            "symbol": "XAUUSD",
            "action": "buy",
            "volume": 0.01,
            "price_open": 3930.0,
            "price_last": 3930.0,
            "sl": 3920.0,
            "tp": 3950.0,
            "comment": "ignite agent",
            "create_time": "2026-01-01T00:00:00",
            "update_time": "2026-01-01T00:00:00",
        })
    rt.config_service.update({"max_concurrent_positions": 10})
    report = ReadinessService(rt).check()
    assert report.ready is False
    assert not report.checks["positions"].ok