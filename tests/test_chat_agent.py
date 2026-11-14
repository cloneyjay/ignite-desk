"""Tests for the UnifiedChatAgent: LLM-first conversational router with MCP tools."""

from __future__ import annotations

from backend.ignite.agent.chat_agent import ChatResponse, UnifiedChatAgent


def test_unified_chat_agent_exists():
    """UnifiedChatAgent and ChatResponse can be imported."""
    assert UnifiedChatAgent is not None
    assert ChatResponse is not None


def test_unified_chat_agent_responds(rt):
    """UnifiedChatAgent.respond returns a ChatResponse with narrative."""
    from unittest.mock import MagicMock

    from backend.ignite.llm.client import LLMResult

    class FakeLLM:
        def complete(self, messages, tools=None, tool_choice="auto", **kwargs):
            return LLMResult(
                text="Hello! I'm Aegus, your trading assistant.",
                provider="fake",
                model="fake",
                latency_ms=1,
            )

    rt.llm = FakeLLM()  # type: ignore[method-assign]

    agent = UnifiedChatAgent(rt)
    response = agent.respond("session_1", "What is my risk?", [])

    assert isinstance(response, ChatResponse)
    assert isinstance(response.narrative, str)
    assert len(response.narrative) > 0
    assert isinstance(response.tool_calls, list)
    assert isinstance(response.structured, dict)
