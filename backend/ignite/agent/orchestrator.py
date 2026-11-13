"""Agent orchestrator: bounded tool-calling loop that produces a structured decision."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

from backend.ignite.agent.decision import Decision, DecisionError, parse_decision
from backend.ignite.agent.tools import ToolRegistry, ToolSpec
from backend.ignite.llm.client import LLMClient, LLMResult, ToolCall
from backend.ignite.services.runtime import Runtime


@dataclass
class OrchestratorConfig:
    max_steps: int = 8
    max_tool_calls: int = 16
    deadline_s: float = 90.0


class Orchestrator:
    """Runs the agent's bounded tool-calling loop for one symbol/timeframe."""

    def __init__(
        self,
        rt: Runtime,
        max_steps: int = 8,
        max_tool_calls: int = 16,
        deadline_s: float = 90.0,
    ) -> None:
        self.rt = rt
        self.config = OrchestratorConfig(
            max_steps=max_steps,
            max_tool_calls=max_tool_calls,
            deadline_s=deadline_s,
        )

    def run_cycle(self, symbol: str, timeframe: str) -> Decision:
        decision_id = uuid.uuid4().hex
        tools = self.rt.tool_registry.get_available(
            self.rt.config().operating_mode, self.rt.kill_switch()
        )
        openai_tools = [t.to_openai() for t in tools]

        messages = self._build_context_pack(symbol, timeframe, decision_id)
        tool_call_count = 0
        start = time.monotonic()

        for step in range(self.config.max_steps):
            # Check budget
            if time.monotonic() - start > self.config.deadline_s:
                return self._budget_exhausted(decision_id, symbol, timeframe, "deadline_exceeded")
            if tool_call_count >= self.config.max_tool_calls:
                return self._budget_exhausted(decision_id, symbol, timeframe, "max_tool_calls_exceeded")

            # Call LLM
            resp = self.rt.llm.complete(
                messages,
                tools=openai_tools,
                tool_choice="auto",
            )

            # Handle tool calls
            if resp.tool_calls:
                for tc in resp.tool_calls:
                    tool_call_count += 1
                    result = self._execute_tool(tc, decision_id)
                    messages.append(
                        {"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)}
                    )
                continue

            # No tool calls -> model produced final decision
            decision = parse_decision(resp.text)
            if isinstance(decision, DecisionError):
                # Invalid decision, ask model to retry
                messages.append(
                    {"role": "user", "content": f"Decision invalid: {decision}. Try again."}
                )
                continue

            # Valid decision
            decision.links.decision_id = decision_id
            self.rt.store.append_agent_event(
                "decision.final",
                severity="info",
                symbol=symbol,
                decision_id=decision_id,
                payload=decision.model_dump(),
            )
            return decision

        # Exhausted steps without decision
        return self._budget_exhausted(decision_id, symbol, timeframe, "max_steps_exceeded")

    def _execute_tool(self, tool_call: ToolCall, decision_id: str) -> dict[str, Any]:
        """Execute a single tool call and record the event."""
        tool = self.rt.tool_registry._tools.get(tool_call.name)
        if tool is None:
            result = {"error": f"unknown tool: {tool_call.name}"}
            self._record_tool_event(
                decision_id,
                tool_call.name,
                tool_call.arguments,
                result,
                status="error",
            )
            return result

        # Validate input
        try:
            validated_args = tool.validate_input(tool_call.arguments)
        except Exception as exc:
            result = {"error": f"invalid arguments: {exc}"}
            self._record_tool_event(
                decision_id,
                tool_call.name,
                tool_call.arguments,
                result,
                status="error",
            )
            return result

        # Execute handler
        try:
            result = tool.handler(self.rt, validated_args)
            # Handler might be sync or async
            import asyncio
            if asyncio.iscoroutine(result):
                result = asyncio.run(result)
        except Exception as exc:
            result = {"error": f"handler failed: {exc}"}
            self._record_tool_event(
                decision_id,
                tool_call.name,
                validated_args,
                result,
                status="error",
            )
            return result

        # Validate output
        try:
            result = tool.validate_output(result)
        except Exception as exc:
            result = {"error": f"output validation failed: {exc}"}
            self._record_tool_event(
                decision_id,
                tool_call.name,
                validated_args,
                result,
                status="error",
            )
            return result

        self._record_tool_event(
            decision_id,
            tool_call.name,
            validated_args,
            result,
            status="ok",
        )
        return result

    def _record_tool_event(
        self,
        decision_id: str,
        tool_name: str,
        args: dict[str, Any],
        result: dict[str, Any],
        status: str,
    ) -> None:
        """Record a tool call to agent_events."""
        self.rt.store.append_agent_event(
            "tool.call",
            severity="info" if status == "ok" else "error",
            symbol=None,
            decision_id=decision_id,
            payload={
                "name": tool_name,
                "arguments": args,
                "result": result,
                "status": status,
            },
        )

    def _budget_exhausted(
        self, decision_id: str, symbol: str, timeframe: str, reason: str
    ) -> Decision:
        """Return a NO_TRADE decision when budget is exhausted."""
        decision = Decision(
            symbol=symbol,
            timeframe=timeframe,
            action="NO_TRADE",
            conviction=0.0,
            thesis=f"Budget exhausted: {reason}",
            evidence=[],
            failed_conditions=[reason],
            entry=Entry(type="market", price=0.0),
            risk=Risk(lots=0.0, sl=0.0, tp=0.0),
            expected_rr=0.0,
            invalidate_if=[],
            links=Links(analysis_id=None, draft_id=None, decision_id=decision_id),
        )
        self.rt.store.append_agent_event(
            "decision.final",
            severity="warning",
            symbol=symbol,
            decision_id=decision_id,
            payload=decision.model_dump(),
        )
        return decision

    def _build_context_pack(
        self, symbol: str, timeframe: str, decision_id: str
    ) -> list[dict[str, str]]:
        """Build the initial context pack for the LLM."""
        # This is a simplified context pack - in production it would fetch
        # account, positions, quote, bars, spec, structure, calendar, news, etc.
        return [
            {
                "role": "system",
                "content": (
                    "You are an autonomous trading agent. Use the available tools to "
                    "analyze the market and make a trading decision. Your final response "
                    "must be a structured decision matching the Decision schema. "
                    "Available actions: LONG, SHORT, NO_TRADE, WAIT, MONITOR, CLOSE, MODIFY."
                ),
            },
            {
                "role": "user",
                "content": f"Analyze {symbol} on {timeframe} and produce a trading decision.",
            },
        ]


# Re-export for type hints
from backend.ignite.agent.decision import Decision, Entry, Risk, Links