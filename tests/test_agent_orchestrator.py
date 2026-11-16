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
        self.config.return_value.operating_mode = "autonomous"
        self.config.return_value.execution_mode = "live"
        self.config.return_value.autonomy_level = 2
        self.kill_switch = MagicMock(return_value=False)

    def config(self):
        cfg = MagicMock()
        cfg.operating_mode = "autonomous"
        cfg.execution_mode = "live"
        cfg.autonomy_level = 2
        return cfg

    def kill_switch(self):
        return False


def test_orchestrator_respects_max_steps():
    rt = FakeRuntime()
    orch = Orchestrator(rt, max_steps=2, max_tool_calls=10, deadline_s=90.0)
    # Provide a fake LLM that always wants to call tools
    rt.llm.add_response(
        text="",
        tool_calls=[ToolCall(id="call_1", name="account_snapshot", arguments={})],
    )
    rt.llm.add_response(
        text="",
        tool_calls=[ToolCall(id="call_2", name="market_quote", arguments={"symbol": "XAUUSD"})],
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
        tool_calls=[ToolCall(id="call_1", name="account_snapshot", arguments={})],
    )
    decision = orch.run_cycle("XAUUSD", "M15")
    # Verify agent_events was called for the tool
    calls = rt.store.append_agent_event.call_args_list
    tool_calls = [c for c in calls if c[0][0] == "tool.call"]
    assert len(tool_calls) > 0


def test_registry_get_allowed_fails_closed():
    """PRD Invariant #4: execution-time lookup re-checks the permission gate."""
    registry = ToolRegistry()
    # execute tool, allowed in autonomous + kill switch off + autonomy 2
    assert registry.get_allowed("execution_place_order", "autonomous", False, 2) is not None
    # same tool blocked by each condition
    assert registry.get_allowed("execution_place_order", "prepare", False, 2) is None
    assert registry.get_allowed("execution_place_order", "autonomous", True, 2) is None
    assert registry.get_allowed("execution_place_order", "autonomous", False, 1) is None
    # unknown tool -> None
    assert registry.get_allowed("no_such_tool", "autonomous", False, 2) is None


def test_orchestrator_blocks_execute_tool_when_not_allowed():
    """The model must not be able to run an execute tool that the gate filtered
    out of its visible tool list (fail closed, PRD Invariant #4)."""
    rt = FakeRuntime()
    rt.kill_switch = lambda: True  # execute tools are gated out
    orch = Orchestrator(rt, max_steps=3, max_tool_calls=10, deadline_s=90.0)
    result = orch._execute_tool(
        "execution_place_order", {"draft_id": "d1"}, "dec1"
    )
    assert "not allowed" in result["error"]
    # and the rejection is journaled
    events = rt.store.append_agent_event.call_args_list
    assert any(
        c[0][0] == "tool.call" and c[1]["payload"]["status"] == "error" for c in events
    )


def test_orchestrator_blocks_prepare_tool_in_observe_mode():
    """prepare tools need mode autonomous/prepare and autonomy >= 1."""
    rt = FakeRuntime()

    def observe_mode():
        cfg = MagicMock()
        cfg.operating_mode = "observe"
        cfg.execution_mode = "shadow"
        cfg.autonomy_level = 0
        return cfg

    rt.config = observe_mode
    orch = Orchestrator(rt, max_steps=3, max_tool_calls=10, deadline_s=90.0)
    result = orch._execute_tool("draft_create", {}, "dec1")
    assert "not allowed" in result["error"]