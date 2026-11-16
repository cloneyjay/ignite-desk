"""Tests for LLM tool calling."""

from __future__ import annotations

import pytest

from backend.ignite.llm.client import LLMClient, LLMResult, ToolCall, ToolCallError


class FakeLLMClient(LLMClient):
    """Fake LLM client for testing tool calling."""

    def __init__(self):
        # Skip parent init
        self._responses = []

    def set_response(self, text: str, tool_calls: list[dict] | None = None):
        self._responses.append((text, tool_calls or []))

    def complete(self, messages, tools=None, tool_choice="auto", **kwargs):
        if not self._responses:
            raise RuntimeError("No response configured")
        text, tool_calls = self._responses.pop(0)
        return LLMResult(
            text=text,
            provider="fake",
            model="fake",
            latency_ms=1,
            tool_calls=[ToolCall(**tc) for tc in tool_calls] if tool_calls else None,
        )


def test_native_tool_calls_returned():
    client = FakeLLMClient()
    client.set_response(
        text="I'll check your account",
        tool_calls=[{"id": "call_1", "name": "account_snapshot", "arguments": {}}],
    )
    resp = client.complete(
        messages=[{"role": "user", "content": "test"}],
        tools=[{"type": "function", "function": {"name": "account_snapshot"}}],
    )
    assert resp.tool_calls is not None
    assert len(resp.tool_calls) >= 1
    assert resp.tool_calls[0].name == "account_snapshot"


def test_malformed_args_raises_toolcallerror():
    from backend.ignite.llm.client import LLMClient, LLMResult
    from backend.ignite.config import LLMSettings

    # Test the parsing logic directly with a minimal client
    class TestClient(LLMClient):
        def __init__(self):
            pass  # Skip parent init

        def _parse_native_tool_calls(self, message):
            return super()._parse_native_tool_calls(message)

    client = TestClient()
    # Test malformed JSON in arguments
    message = {
        "tool_calls": [
            {
                "id": "call_1",
                "function": {"name": "account_snapshot", "arguments": "not valid json"},
            }
        ]
    }
    with pytest.raises(ToolCallError, match="invalid arguments"):
        client._parse_native_tool_calls(message)