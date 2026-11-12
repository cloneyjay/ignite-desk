"""Tests for agent API routes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.ignite.api.app import create_app
from backend.ignite.config import MCPSettings, Settings
from backend.ignite.services.runtime import Runtime
from tests.fakes import FakeForecast, FakeMCP


@pytest.fixture()
def env(tmp_path):
    settings = Settings(
        mcp=MCPSettings(url="http://fake", token="test-token"),
        db_path=tmp_path / "api-test.db",
        bind_host="127.0.0.1",
        bind_port=8000,
        kronos_worker_url="http://fake",
        kronos_model="fake",
        timezone="local",
    )
    runtime = Runtime(settings, mcp_client=FakeMCP(), forecast_client=FakeForecast())
    app = create_app(runtime=runtime)
    with TestClient(app) as client:
        yield client, runtime


def test_agent_status_endpoint(env):
    client, _ = env
    resp = client.get("/api/agent/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "enabled" in data
    assert "next_cycle" in data
    assert "decisions_today" in data
    assert "positions_open" in data


def test_agent_toggle_endpoint(env):
    client, rt = env
    # Enable
    resp = client.post("/api/agent/toggle", json={"enabled": True})
    assert resp.status_code == 200
    assert resp.json()["enabled"] is True
    # Verify DB
    assert rt.store.agent_config()["enabled"] == 1
    # Disable
    resp = client.post("/api/agent/toggle", json={"enabled": False})
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False


def test_agent_positions_endpoint(env):
    client, rt = env
    # Seed agent position
    rt.store.upsert_agent_position({
        "ticket": "12345",
        "symbol": "XAUUSD",
        "side": "BUY",
        "entry_price": 3900.0,
        "volume": 0.01,
        "sl": 3880.0,
        "tp": 3930.0,
        "opened_at": "2026-11-12T12:00:00Z",
        "managed_by_agent": 1,
        "trail_sl": 3885.0,
        "scale_in_count": 0,
        "scale_out_count": 0,
    })
    resp = client.get("/api/agent/positions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["positions"]) == 1
    assert data["positions"][0]["ticket"] == "12345"


def test_agent_config_endpoint(env):
    client, _ = env
    resp = client.get("/api/agent/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "cycle_interval_min" in data
    assert "daily_loss_limit_pct" in data