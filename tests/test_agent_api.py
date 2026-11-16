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


def test_agent_baseline_endpoint(env):
    """Goal 5 daily baseline comparison is available to the dashboard."""
    client, rt = env
    rt.seed_symbols()
    resp = client.get("/api/agent/evaluation/baseline?lookback_days=2")
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "XAUUSD"
    assert data["no_trade"]["sum_r"] == 0.0
    assert "sum_r" in data["agent"] and "sum_r" in data["kronos"] and "sum_r" in data["random"]
    assert "Mechanics evidence only" in data["disclaimer"]


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


class _StubLLM:
    """Deterministic stand-in so conversation tests never touch the network."""

    def complete(self, messages, **kwargs):
        from backend.ignite.llm.client import LLMResult

        return LLMResult(
            text="Not without a setup. Nothing was sent.",
            provider="stub",
            model="stub",
            latency_ms=1,
        )


def _live_position(ticket: str = "900001") -> dict:
    return {
        "position_id": ticket,
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
    }


def test_manual_close_uses_symbol_and_ticket(client, rt):
    rt.mcp.positions.append(_live_position())
    # Also add to agent_positions table so the endpoint finds it
    rt.store.upsert_agent_position(
        {
            "ticket": "900001",
            "symbol": "XAUUSD",
            "side": "BUY",
            "entry_price": 3930.0,
            "volume": 0.01,
            "sl": 3920.0,
            "tp": 3950.0,
            "opened_at": "2026-01-01T00:00:00Z",
            "managed_by_agent": 1,
            "trail_sl": 3920.0,
            "scale_in_count": 0,
            "scale_out_count": 0,
        }
    )
    resp = client.post("/api/agent/positions/900001/close")
    assert resp.status_code == 200
    args = rt.mcp.called("trade_close_single_position")[0]
    assert args == {"symbol": "XAUUSD", "position_ticket": "900001"}


def test_config_put_round_trips_and_applies(client, rt):
    resp = client.put("/api/agent/config", json={"risk_pct": 0.025})
    assert resp.status_code == 200
    assert resp.json()["risk_pct"] == 0.025
    assert rt.config().risk_pct == 0.025


def test_question_does_not_place_an_order(client, rt):
    rt.llm = _StubLLM()
    resp = client.post("/api/agent/chat", json={"text": "should I buy XAUUSD?"})
    assert resp.status_code == 200
    assert rt.mcp.called("trade_send_market_order") == []


def test_chat_tool_trace_is_real(client, rt):
    from backend.ignite.llm.client import LLMResult, ToolCall

    class FakeLLM:
        def complete(self, messages, tools=None, tool_choice="auto", **kwargs):
            return LLMResult(
                text="",
                tool_calls=[
                    ToolCall(
                        id="tc_1",
                        name="account_positions",
                        arguments={},
                    )
                ],
                provider="fake",
                model="fake",
                latency_ms=1,
            )

    rt.llm = FakeLLM()  # type: ignore[method-assign]
    resp = client.post("/api/agent/chat", json={"text": "show my positions"})
    trace = resp.json()["tool_calls"]
    assert trace
    assert trace[0]["name"] == "account_positions"