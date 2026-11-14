"""Reasoner: real-time reasoning stream for the agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generator

from backend.ignite.agent.tools import ToolRegistry
from backend.ignite.llm.client import LLMClient, LLMResult, ToolCall
from backend.ignite.services.runtime import Runtime


@dataclass(frozen=True)
class ReasoningEvent:
    """A single event in the reasoning stream."""
    type: str  # "thinking", "tool", "observation", "conclusion"
    content: str
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_result: dict[str, Any] | None = None
    timestamp: str = ""


class Reasoner:
    """Generates a real-time reasoning stream for the agent."""

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt

    def stream(self, prompt: str) -> Generator[dict[str, Any], None, None]:
        """Stream reasoning events for a given prompt."""
        # Initial thinking event
        yield {
            "type": "thinking",
            "content": f"Analyzing request: {prompt[:100]}...",
            "timestamp": self._now(),
        }

        # Get available tools
        tools = self.rt.tool_registry.get_available(
            self.rt.config().operating_mode,
            self.rt.kill_switch(),
            self.rt.config().autonomy_level,
        )

        # Build system prompt with available tools
        tool_descriptions = [
            f"- {t.name}: {t.description}"
            for t in self.rt.tool_registry._tools.values()
        ]

        system_prompt = (
            "You are an autonomous trading agent. Reason step by step about the request. "
            "When you need to use a tool, output a JSON tool call. "
            "Available tools:\n" + "\n".join(tool_descriptions)
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        # Stream LLM response with tool calls
        while True:
            resp = self.rt.llm.complete(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                tools=[t.to_openai() for t in self.rt.tool_registry.get_available(
                    self.rt.config().operating_mode,
                    self.rt.kill_switch(),
                    self.rt.config().autonomy_level,
                )],
                tool_choice="auto",
            )

            # Yield thinking
            if resp.text:
                yield {
                    "type": "thinking",
                    "content": resp.text,
                    "timestamp": self._now(),
                }

            # Handle tool calls
            if resp.tool_calls:
                for tc in resp.tool_calls:
                    # Tool call event
                    yield {
                        "type": "tool",
                        "tool": tc.name,
                        "arguments": tc.arguments,
                        "timestamp": self._now(),
                    }

                    # Execute tool
                    tool = self.rt.tool_registry._tools.get(tc.name)
                    if tool:
                        try:
                            import asyncio
                            result = asyncio.run(tool.handler(self.rt, tc.arguments))
                        except Exception as e:
                            result = {"error": str(e)}
                    else:
                        result = {"error": f"Unknown tool: {tc.name}"}

                    # Tool result event
                    yield {
                        "type": "observation",
                        "tool": tc.name,
                        "result": result,
                        "timestamp": self._now(),
                    }

                    # Add to conversation
                    messages.append({"role": "assistant", "tool_calls": [tc.to_dict()]})
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": str(result)})
                    continue

            # No tool calls - final conclusion
            if resp.text:
                yield {
                    "type": "conclusion",
                    "content": resp.text,
                    "timestamp": self._now(),
                }
            break

    def _now(self) -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()