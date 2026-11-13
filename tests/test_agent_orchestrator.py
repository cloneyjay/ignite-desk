"""Tests for agent orchestrator."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from backend.ignite.agent.decision import Decision, DecisionError, parse_decision
from backend.ignite.agent.orchestrator import Orchestrator
from backend.ignite.agent.tools import ToolRegistry
from backend.ignite.llm.client import LLMResult, ToolCall


class FakeLLMClient:
    """Fake LLM client that returns configured responses."""

    def __init__(self):
        self.responses: list[LLMResult] = []

    def add_response(self, text: str, tool_calls: list[ToolCall] | None = None):
        self.responses.append(LLMResult(
            text=text,
            provider="fake",
            model="fake",
            latency_ms=1,
            tool_calls=tool_calls,
        ))

    def complete(self, messages, tools=None, tool_choice="auto", **kwargs):
        if not self.responses:
            # Default: return a valid NO_TRADE decision
            return LLMResult(
                text='{"symbol": "XAUUSD", "timeframe": "M15", "action": "NO_TRADE", "conviction": 0.0, "thesis": "budget exhausted", "evidence": [], "failed_conditions": ["budget_exhausted"], "entry": {"type": "market", "price": 0.0}, "risk": {"lots": 0.0, "sl": 0.0, "tp": 0.0}, "expected_rr": 0.0, "invalidate_if": [], "links": {"analysis_id": null, "draft_id": null, "decision_id": "test"}}',
                provider="fake",
                model="fake",
                latency_ms=1,
            )
        return self.responses.pop(0)


class FakeRuntime:
    """Fake runtime for testing."""

    def __init__(self):
        self.llm = FakeLLMClient()
        self.tool_registry = ToolRegistry()
        self.store = MagicMock()
        self.store.append_agent_event = MagicMock()
        self.config = MagicMock()
        self.config.return_value = MagicMock()
        self.config.return_value.operating_mode = "autonomous"
        self.kill_switch = MagicMock(return_value=False)

    def config(self):
        cfg = MagicMock()
        cfg.operating_mode = "autonomous"
        return cfg

    def kill_switch(self):
        return False


def test_orchestrator_respects_max_steps():
    rt = FakeRuntime()
    orch = Orchestrator(rt, max_steps=2, max_tool_calls=10, deadline_s=90.0)
    # Provide a fake LLM that always wants to call tools
    rt.llm.add_response(
        text="",
        tool_calls=[ToolCall(id="call_1", name="account.snapshot", arguments={})],
    )
    rt.llm.add_response(
        text="",
        tool_calls=[ToolCall(id="call_2", name="market.quote", arguments={"symbol": "XAUUSD"})],
    )
    # Third response would exceed max_steps
    decision = orch.run_cycle("XAUUSD", "M15")
    assert decision.action == "NO_TRADE"
    assert any("exceeded" in c for c in (decision.failed_conditions or []))


def test_orchestrator_records_tool_calls():
    rt = FakeRuntime()
    orch = Orchestrator(rt, max_steps=3, max_tool_calls=10, deadline_s=90.0)
    # LLM calls one tool, then returns a decision
    rt.llm.add_response(
        text="",
        tool_calls=[ToolCall(id="call_1", name="account.snapshot", arguments={})],
    )
    decision = orch.run_cycle("XAUUSD", "M15")
    # Verify agent_events was called for the tool
    calls = rt.store.append_agent_event.call_args_list
    tool_calls = [c for c in calls if c[0][0] == "tool.call"]
    assert len(tool_calls) > 0