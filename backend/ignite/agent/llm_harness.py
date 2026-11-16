"""Shared LLM intelligence loop used by both chat and autonomous cycle.

This is the single decision brain of Ignite Desk. A user message (chat) and a
scheduler tick (autonomous cycle) both route through ``LLMHarness.run`` with
the same tool registry, the same permission gate, the same context budget, and
the same execution path. There is no second decision brain.

LLM failures (``LLMUnavailable``, ``LLMError``) are propagated to the caller,
which decides how to present them (chat sets a structured ``kind``; the
orchestrator returns a NO_TRADE decision).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable

from backend.ignite.agent.tools import ToolSpec
from backend.ignite.llm.client import LLMResult, ToolCall
from backend.ignite.services.runtime import Runtime

MAX_TOOL_STEPS = 10
TURN_DEADLINE_S = 180.0


@dataclass(frozen=True)
class HarnessResult:
    """Outcome of one LLM harness turn."""

    text: str
    tool_calls: list[dict[str, Any]]
    provider: str | None
    model: str | None
    exhausted: bool = False


class LLMHarness:
    """Bounded LLM tool-calling loop shared by chat and autonomous mode.

    ``execute`` is a callable ``(tool_name, arguments) -> dict`` supplied by
    the caller (chat routes custom tools to Analyst/ExecutionDesk; the
    orchestrator routes everything through the ToolRegistry). ``tool_specs``
    is the already-gated list of tools (the caller applies
    ``permission_allowed`` via ``ToolRegistry.get_available``).
    """

    def __init__(
        self,
        rt: Runtime,
        *,
        system_prompt: str,
        tool_specs: list[ToolSpec],
        execute: Callable[[str, dict[str, Any]], dict[str, Any]],
        max_steps: int = MAX_TOOL_STEPS,
        max_tool_calls: int | None = None,
        deadline_s: float = TURN_DEADLINE_S,
    ) -> None:
        self.rt = rt
        self.system_prompt = system_prompt
        self.tool_specs = tool_specs
        self.execute = execute
        self.max_steps = max_steps
        self.max_tool_calls = max_tool_calls
        self.deadline_s = deadline_s

    # ------------------------------------------------------------------ run

    def run(
        self,
        initial_messages: list[dict[str, Any]],
    ) -> HarnessResult:
        """Run one bounded tool-calling turn through the LLM.

        Propagates ``LLMUnavailable`` and ``LLMError`` to the caller.
        """
        messages: list[dict[str, Any]] = [{"role": "system", "content": self.system_prompt}]
        messages.extend(initial_messages)

        openai_tools = [t.to_openai() for t in self.tool_specs]
        tool_call_records: list[dict[str, Any]] = []
        start = time.monotonic()
        exhausted = True  # assume budget exhausted until a final response arrives

        for _step in range(self.max_steps):
            remaining = self.deadline_s - (time.monotonic() - start)
            if remaining <= 1.0:
                break

            result: LLMResult = self.rt.llm.complete(
                messages,
                tools=openai_tools,
                tool_choice="auto",
                timeout_s=remaining,
            )

            # Model produced final text - no more tool calls needed
            if not result.tool_calls:
                exhausted = False
                return HarnessResult(
                    text=result.text,
                    tool_calls=tool_call_records,
                    provider=result.provider,
                    model=result.model,
                    exhausted=False,
                )

            # Record the assistant turn that requested the tools, then the
            # tool results. OpenAI-compatible providers require that order.
            messages.append(
                {
                    "role": "assistant",
                    "content": result.text or "",
                    "tool_calls": [tc.to_dict() for tc in result.tool_calls],
                }
            )
            for tc in result.tool_calls:
                if self.max_tool_calls is not None:
                    if len(tool_call_records) >= self.max_tool_calls:
                        # Budget exhausted: let the model produce a final answer
                        # from what it has already gathered.
                        break
                tool_result = self.execute(tc.name, tc.arguments or {})
                tool_call_records.append(
                    {
                        "name": tc.name,
                        "arguments": tc.arguments,
                        "result": tool_result,
                        "latency_ms": None,
                    }
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(tool_result, default=str),
                    }
                )
            else:
                continue
            break

        # Tool budget or deadline exhausted: ask the model for a final answer
        # from what it already gathered. Still the model, never a template.
        remaining = max(5.0, self.deadline_s - (time.monotonic() - start))
        final: LLMResult = self.rt.llm.complete(
            messages,
            tools=None,
            tool_choice=None,
            timeout_s=remaining,
        )

        return HarnessResult(
            text=final.text,
            tool_calls=tool_call_records,
            provider=final.provider,
            model=final.model,
            exhausted=True,
        )
