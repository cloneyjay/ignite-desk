"""End-to-end tests for agent cycle integration."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from backend.ignite.agent.decision import Decision, Entry, Risk, Links
from backend.ignite.agent.engine import AgentEngine
from backend.ignite.llm.client import LLMResult, ToolCall
from backend.ignite.services.runtime import Runtime


class FakeLLMWithDecision:
    """Fake LLM that returns a pre-configured decision on first call."""

    def __init__(self, decision: Decision):
        self.decision = decision
        self.call_count = 0

    def complete(self, messages, tools=None, tool_choice="auto", **kwargs):
        self.call_count += 1
        if self.call_count == 1:
            # Return the decision as JSON
            return LLMResult(
                text=self.decision.model_dump_json(),
                provider="fake",
                model="fake",
                latency_ms=1,
            )
        # Subsequent calls (should not happen in normal flow)
        return LLMResult(
            text='{"symbol": "XAUUSD", "timeframe": "M15", "action": "NO_TRADE", "conviction": 0.0, "thesis": "done", "evidence": [], "failed_conditions": [], "entry": {"type": "market", "price": 0.0}, "risk": {"lots": 0.0, "sl": 0.0, "tp": 0.0}, "expected_rr": 0.0, "invalidate_if": [], "links": {"analysis_id": null, "draft_id": null, "decision_id": "test"}}',
            provider="fake",
            model="fake",
            latency_ms=1,
        )


def _make_long_decision() -> Decision:
    return Decision(
        symbol="XAUUSD",
        timeframe="M15",
        action="LONG",
        conviction=0.82,
        thesis="Strong bullish setup",
        evidence=["trend up", "forecast supports long"],
        failed_conditions=[],
        entry=Entry(type="market", price=0.0),
        risk=Risk(lots=0.01, sl=3920.0, tp=3950.0),
        expected_rr=2.5,
        invalidate_if=["price below 3900"],
        links=Links(analysis_id="test_analysis", draft_id="test_draft", decision_id="test_decision"),
    )


def test_full_cycle_produces_decision(rt):
    rt.config_service.update({"enabled": True, "operating_mode": "autonomous", "execution_mode": "shadow"})
    rt.realised_override = 0.0
    # Fake LLM that returns a valid LONG decision on first turn
    rt.llm = FakeLLMWithDecision(_make_long_decision())
    # Seed market data
    rt.mcp.positions.append({
        "position_id": "1", "symbol": "XAUUSD", "action": "buy",
        "volume": 0.01, "price_open": 3930.0, "price_last": 3930.0,
        "sl": 3920.0, "tp": 3950.0, "comment": "ignite agent",
        "create_time": "2026-01-01T00:00:00", "update_time": "2026-01-01T00:00:00",
    })
    # Trigger cycle manually
    engine = AgentEngine(rt, rt.config())
    engine.run_cycle()
    decisions = rt.store.agent_decisions(limit=10)
    assert len(decisions) == 1
    assert decisions[0]["decision"] == "LONG"


def test_cycle_in_shadow_mode_does_not_send_order(rt):
    rt.config_service.update({"enabled": True, "operating_mode": "autonomous", "execution_mode": "shadow"})
    rt.realised_override = 0.0
    rt.llm = FakeLLMWithDecision(_make_long_decision())
    engine = AgentEngine(rt, rt.config())
    engine.run_cycle()
    # Gateway should validate but not send (shadow mode)
    assert rt.mcp.called("trade_send_market_order") == []


def test_cycle_records_agent_events(rt):
    rt.config_service.update({"enabled": True, "operating_mode": "autonomous", "execution_mode": "shadow"})
    rt.realised_override = 0.0
    rt.llm = FakeLLMWithDecision(_make_long_decision())
    engine = AgentEngine(rt, rt.config())
    engine.run_cycle()
    # Check that agent_events were recorded
    events = rt.store.agent_events()
    assert len(events) > 0
    # Should have decision.final event
    final_events = [e for e in events if e["kind"] == "decision.final"]
    assert len(final_events) == 1