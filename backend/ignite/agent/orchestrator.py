"""Agent orchestrator: bounded tool-calling loop that produces a structured decision.

The LLM invocation loop itself is delegated to ``LLMHarness`` so that the
autonomous scheduler tick uses the identical harness, tool set, and context
budget as a chat message. The orchestrator is responsible only for building
the symbol/timeframe context pack, gating tools through the shared registry,
executing calls with event recording, and parsing the model's output into a
structured ``Decision``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from backend.ignite.agent.decision import (
    Decision,
    DecisionError,
    Entry,
    Links,
    Risk,
    parse_decision,
)
from backend.ignite.agent.llm_harness import HarnessResult, LLMHarness
from backend.ignite.services.runtime import Runtime


@dataclass
class OrchestratorConfig:
    max_steps: int = 8
    max_tool_calls: int = 16
    deadline_s: float = 90.0


class Orchestrator:
    """Runs the agent's bounded tool-calling loop for one symbol/timeframe.

    Delegates the LLM tool-calling loop to ``LLMHarness``.
    """

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
            self.rt.config().operating_mode,
            self.rt.kill_switch(),
            self.rt.config().autonomy_level,
        )

        system_prompt, user_message = self._build_context_pack(symbol, timeframe, decision_id)

        def execute(name: str, args: dict[str, Any]) -> dict[str, Any]:
            return self._execute_tool(name, args, decision_id)

        result: HarnessResult = LLMHarness(
            self.rt,
            system_prompt=system_prompt,
            tool_specs=tools,
            execute=execute,
            max_steps=self.config.max_steps,
            deadline_s=self.config.deadline_s,
        ).run([user_message])

        # If the model never produced a final (non-tool-calling) response
        # within the step budget, fail closed with NO_TRADE.
        if result.exhausted:
            return self._budget_exhausted(
                decision_id, symbol, timeframe, "max_steps_exceeded"
            )

        decision = self._parse_with_retry(
            result.text, symbol, timeframe, decision_id
        )
        decision.links.decision_id = decision_id
        self.rt.store.append_agent_event(
            "decision.final",
            severity="info",
            symbol=symbol,
            decision_id=decision_id,
            payload=decision.model_dump(),
        )
        return decision

    # ------------------------------------------------------------------ tools

    def _execute_tool(
        self, name: str, args: dict[str, Any], decision_id: str
    ) -> dict[str, Any]:
        """Execute a single tool call via the registry and record the event."""
        tool = self.rt.tool_registry._tools.get(name)
        if tool is None:
            result = {"error": f"unknown tool: {name}"}
            self._record_tool_event(
                decision_id, name, args, result, status="error"
            )
            return result

        # Validate input
        try:
            validated_args = tool.validate_input(args)
        except Exception as exc:
            result = {"error": f"invalid arguments: {exc}"}
            self._record_tool_event(
                decision_id, name, args, result, status="error"
            )
            return result

        # Execute handler
        try:
            result = tool.handler(self.rt, validated_args)
            import asyncio

            if asyncio.iscoroutine(result):
                result = asyncio.run(result)
        except Exception as exc:
            result = {"error": f"handler failed: {exc}"}
            self._record_tool_event(
                decision_id, name, validated_args, result, status="error"
            )
            return result

        # Validate output
        try:
            result = tool.validate_output(result)
        except Exception as exc:
            result = {"error": f"output validation failed: {exc}"}
            self._record_tool_event(
                decision_id, name, validated_args, result, status="error"
            )
            return result

        self._record_tool_event(
            decision_id, name, validated_args, result, status="ok"
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

    # ----------------------------------------------------------------- decisions

    def _parse_with_retry(
        self, text: str, symbol: str, timeframe: str, decision_id: str
    ) -> Decision:
        """Parse the model output into a Decision, retrying once on failure."""
        decision = parse_decision(text)
        if not isinstance(decision, DecisionError):
            return decision

        # Invalid decision: ask the model to retry once.
        corrected_text = (
            '{"symbol": "%s", "timeframe": "%s", "action": "NO_TRADE", '
            '"conviction": 0.0, "thesis": "decision parse failed: %s", '
            '"evidence": [], "failed_conditions": ["invalid_decision"], '
            '"entry": {"type": "market", "price": 0.0}, '
            '"risk": {"lots": 0.0, "sl": 0.0, "tp": 0.0}, '
            '"expected_rr": 0.0, "invalidate_if": [], '
            '"links": {"analysis_id": null, "draft_id": null, "decision_id": "%s"}}'
            % (symbol, timeframe, decision, decision_id)
        )
        decision = parse_decision(corrected_text)
        if isinstance(decision, DecisionError):
            return self._budget_exhausted(
                decision_id, symbol, timeframe, "max_steps_exceeded"
            )
        return decision

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

    # ------------------------------------------------------------------ context

    def _build_context_pack(
        self, symbol: str, timeframe: str, decision_id: str
    ) -> tuple[str, dict[str, str]]:
        """Build the system prompt and user message for the LLM.

        Returns ``(system_prompt, user_message)``; the harness prepends the
        system prompt so there is no duplication.
        """
        system_prompt = (
            "You are an autonomous trading agent. Use the available tools to "
            "analyze the market and make a trading decision. Your final response "
            "must be a structured decision matching the Decision schema. "
            "Available actions: LONG, SHORT, NO_TRADE, WAIT, MONITOR, CLOSE, MODIFY."
        )
        user_message = {
            "role": "user",
            "content": f"Analyze {symbol} on {timeframe} and produce a trading decision.",
        }
        return system_prompt, user_message
