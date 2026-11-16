"""Tests for LLMHarness: the shared LLM intelligence loop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from backend.ignite.agent.llm_harness import HarnessResult, LLMHarness
from backend.ignite.agent.tools import ToolSpec
from backend.ignite.llm.client import LLMError, LLMResult, LLMUnavailable, ToolCall
from backend.ignite.services.runtime import Runtime


class ScriptedLLM:
    """Replays scripted model results and records every request."""

    def __init__(self, *results: LLMResult) -> None:
        self._results = list(results)
        self.requests: list[dict[str, Any]] = []

    def complete(self, messages, **kwargs) -> LLMResult:
        self.requests.append(
            {"messages": [dict(m) for m in messages], **kwargs}
        )
        if not self._results:
            raise AssertionError("model was called more often than scripted")
        return self._results.pop(0)


class UnavailableLLM:
    def complete(self, messages, **kwargs) -> LLMResult:
        raise LLMUnavailable("no LLM provider is configured", ["nim: no api key"])


class ErrorLLM:
    def complete(self, messages, **kwargs) -> LLMResult:
        raise LLMError("upstream provider returned 500")


def _text(text: str) -> LLMResult:
    return LLMResult(text=text, provider="fake", model="fake-model", latency_ms=1)


def _tool_calls(*calls: ToolCall) -> LLMResult:
    return LLMResult(
        text="",
        provider="fake",
        model="fake-model",
        latency_ms=1,
        tool_calls=list(calls),
    )


class FakeRuntime:
    def __init__(self) -> None:
        self.llm = ScriptedLLM()
        self.config_calls = 0

    def config(self):
        self.config_calls += 1
        c = type("C", (), {})()
        c.operating_mode = "prepare"
        c.autonomy_level = 0
        return c

    def kill_switch(self):
        return False


def _spec(name: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        permission="read",
        description=f"{name} tool",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        output_schema={"type": "object", "properties": {}, "additionalProperties": False},
        timeout_s=5.0,
        handler=lambda rt, args: {"ok": True, "tool": name},
    )


def test_harness_returns_final_text_when_no_tool_calls():
    rt = FakeRuntime()
    rt.llm = ScriptedLLM(_text("Hello from the model."))
    harness = LLMHarness(
        rt,
        system_prompt="You are helpful.",
        tool_specs=[_spec("market_quote")],
        execute=lambda name, args: {"ok": True},
    )
    result = harness.run([{"role": "user", "content": "hi"}])

    assert isinstance(result, HarnessResult)
    assert result.text == "Hello from the model."
    assert result.tool_calls == []
    assert result.provider == "fake"
    assert result.model == "fake-model"
    assert result.exhausted is False


def test_harness_executes_tool_calls_and_feeds_results_back():
    rt = FakeRuntime()
    rt.llm = ScriptedLLM(
        _tool_calls(ToolCall(id="call_1", name="market_quote", arguments={"symbol": "XAUUSD"})),
        _text("The quote is 3930.13."),
    )
    executed: list[tuple[str, dict[str, Any]]] = []

    def execute(name: str, args: dict[str, Any]) -> dict[str, Any]:
        executed.append((name, args))
        return {"ok": True, "bid": 3930.0, "ask": 3930.13}

    harness = LLMHarness(
        rt,
        system_prompt="You are helpful.",
        tool_specs=[_spec("market_quote")],
        execute=execute,
    )
    result = harness.run([{"role": "user", "content": "quote XAUUSD"}])

    assert result.text == "The quote is 3930.13."
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["name"] == "market_quote"
    assert result.tool_calls[0]["result"] == {"ok": True, "bid": 3930.0, "ask": 3930.13}
    assert executed == [("market_quote", {"symbol": "XAUUSD"})]
    assert result.exhausted is False

    # The tool result was fed back to the model in tool-message form.
    followup = rt.llm.requests[1]["messages"]
    tool_messages = [m for m in followup if m["role"] == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["tool_call_id"] == "call_1"


def test_harness_respects_max_steps_and_reports_exhausted():
    rt = FakeRuntime()
    rt.llm = ScriptedLLM(
        _tool_calls(ToolCall(id="call_1", name="market_quote", arguments={"symbol": "XAUUSD"})),
        _tool_calls(ToolCall(id="call_2", name="account_snapshot", arguments={})),
    )
    # After 2 scripted responses, the model is called a 3rd time (final answer).
    # With max_steps=2 the loop runs both tool-call steps, then a final call.
    # The third ScriptedLLM result would be the final answer text.
    rt.llm = ScriptedLLM(
        _tool_calls(ToolCall(id="call_1", name="market_quote", arguments={"symbol": "XAUUSD"})),
        _tool_calls(ToolCall(id="call_2", name="account_snapshot", arguments={})),
        _text("Best effort answer after tool budget."),
    )

    def execute(name, args):
        return {"ok": True}

    harness = LLMHarness(
        rt,
        system_prompt="You are helpful.",
        tool_specs=[_spec("market_quote"), _spec("account_snapshot")],
        execute=execute,
        max_steps=2,
    )
    result = harness.run([{"role": "user", "content": "analyze XAUUSD"}])

    assert result.exhausted is True
    assert result.text == "Best effort answer after tool budget."
    # The model was called 3 times: 2 tool steps + 1 final answer
    assert len(rt.llm.requests) == 3


def test_harness_propagates_llm_unavailable():
    rt = FakeRuntime()
    rt.llm = UnavailableLLM()
    harness = LLMHarness(
        rt,
        system_prompt="You are helpful.",
        tool_specs=[],
        execute=lambda name, args: {},
    )
    with pytest.raises(LLMUnavailable):
        harness.run([{"role": "user", "content": "hi"}])


def test_harness_propagates_llm_error():
    rt = FakeRuntime()
    rt.llm = ErrorLLM()

    def execute(name, args):
        return {}

    harness = LLMHarness(
        rt,
        system_prompt="You are helpful.",
        tool_specs=[],
        execute=execute,
    )
    with pytest.raises(LLMError):
        harness.run([{"role": "user", "content": "hi"}])


def test_harness_system_prompt_is_included():
    rt = FakeRuntime()
    rt.llm = ScriptedLLM(_text("ok"))
    captured: list[str] = []

    def execute(name, args):
        return {}

    harness = LLMHarness(
        rt,
        system_prompt="SYSTEM: you are Aegus.",
        tool_specs=[],
        execute=execute,
    )
    harness.run([{"role": "user", "content": "hi"}])
    assert rt.llm.requests[0]["messages"][0]["role"] == "system"
    assert "SYSTEM: you are Aegus." in rt.llm.requests[0]["messages"][0]["content"]


def test_harness_tool_specs_are_offered_to_model():
    rt = FakeRuntime()
    rt.llm = ScriptedLLM(_text("ok"))

    def execute(name, args):
        return {}

    harness = LLMHarness(
        rt,
        system_prompt="sys",
        tool_specs=[_spec("market_quote"), _spec("account_snapshot")],
        execute=execute,
    )
    harness.run([{"role": "user", "content": "hi"}])
    tool_names = {
        t["function"]["name"] for t in rt.llm.requests[0]["tools"]
    }
    assert {"market_quote", "account_snapshot"} <= tool_names
