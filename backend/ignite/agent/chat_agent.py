"""UnifiedChatAgent: LLM-first conversational router with MCP tool access.

The agent speaks naturally (Pattern C) and can delegate to the structured
Analyst (Pattern B) for multi-source analysis or the ExecutionDesk for
guarded order execution. It never bypasses risk guards.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from backend.ignite.agent.analyst import Analyst
from backend.ignite.agent.execution_desk import ExecutionDesk
from backend.ignite.agent.tools import ToolRegistry, ToolSpec
from backend.ignite.llm.client import LLMResult, ToolCall
from backend.ignite.services.runtime import Runtime


@dataclass(frozen=True)
class ChatResponse:
    """Outcome of one chat turn."""

    narrative: str
    tool_calls: list[dict[str, Any]]
    structured: dict[str, Any]


SYSTEM_PROMPT = """You are Aegus, a calm, sharp personal trading companion for a one-person XAUUSD day-trading desk.

Speak naturally, warmly, and directly — like a trader talking to another trader. Plain English first, numbers and technical detail when useful. Explain what you checked, what it means, what could invalidate it, and what action was or was not taken.

CAPABILITIES:
- You can inspect live MT5 account state, positions, prices, candles, market structure, spreads, margin, calendar, news, forecasts, analyses, drafts, risk, and trade history.
- You can run a full market analysis (quote + bars + structure + fundamentals + Kronos forecast → draft) and explain the result.
- You can execute a prepared draft through guarded risk checks and the MT5 broker.
- You can manage positions (close, modify SL/TP) and watchlists.

GUARDRAILS:
- You may only execute orders when Autonomous mode is enabled and the kill switch is off.
- Every entry must have a protective stop loss and take profit.
- Never invent prices, positions, or account values. Read them from live tool outputs.
- If a tool fails or returns an error, say so plainly. Never pretend a check passed when it didn't.
- Never promise profit or hide a blocked trade.
- If uncertain, ask clarifying questions instead of hallucinating.

TOOLS: Use the available tools to gather live data before answering. Do not guess about market state.
"""


class UnifiedChatAgent:
    """Conversational agent with full MCP tool access and B+C delegation."""

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt
        self.analyst = Analyst(rt)
        self.execution_desk = ExecutionDesk(rt)
        self._registry = ToolRegistry()

    def respond(
        self, session_id: str, text: str, history: list[dict[str, Any]]
    ) -> ChatResponse:
        """Handle one chat turn: LLM with tools, delegating to Analyst/ExecutionDesk."""
        messages = self._build_messages(session_id, text, history)
        tools = self._get_tools()
        openai_tools = [t.to_openai() for t in tools]

        tool_call_records: list[dict[str, Any]] = []
        structured: dict[str, Any] = {}
        start = time.monotonic()
        deadline_s = 90.0

        for _step in range(8):
            if time.monotonic() - start > deadline_s:
                break

            result: LLMResult = self.rt.llm.complete(
                messages,
                tools=openai_tools,
                tool_choice="auto",
                timeout_s=max(5.0, deadline_s - (time.monotonic() - start)),
            )

            if not result.tool_calls:
                return ChatResponse(
                    narrative=result.text or "I'm not sure how to help with that. Try asking about a symbol or your positions.",
                    tool_calls=tool_call_records,
                    structured=structured,
                )

            for tc in result.tool_calls:
                tool_result = self._execute_tool(tc, structured)
                tool_call_records.append(
                    {
                        "name": tc.name,
                        "arguments": tc.arguments,
                        "result": tool_result,
                    }
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(tool_result),
                    }
                )

        return ChatResponse(
            narrative="I've reached my analysis limit for this turn. Tell me what you'd like to do next.",
            tool_calls=tool_call_records,
            structured=structured,
        )

    # ------------------------------------------------------------------ tools

    def _get_tools(self) -> list[ToolSpec]:
        """Available tools: MCP registry tools plus analyst/execution delegation."""
        tools = self._registry.get_available(
            self.rt.config().operating_mode,
            self.rt.kill_switch(),
            self.rt.config().autonomy_level,
        )
        # Add custom delegation tools that wrap Analyst / ExecutionDesk
        tools.append(
            ToolSpec(
                name="analyst.assess",
                permission="prepare",
                description="Run full multi-source market analysis for a symbol/timeframe and return signal, levels, and draft",
                input_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "timeframe": {"type": "string", "enum": ["M5", "M15", "M30", "H1"]},
                    },
                    "required": ["symbol", "timeframe"],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "timeframe": {"type": "string"},
                        "signal": {"type": "string"},
                        "p_up": {"type": "number"},
                        "edge_atr": {"type": "number"},
                        "draft_id": {"type": ["string", "null"]},
                        "rationale": {"type": "string"},
                    },
                    "required": ["symbol", "timeframe", "signal", "p_up", "edge_atr", "rationale"],
                    "additionalProperties": False,
                },
                timeout_s=120.0,
                handler=self._handle_analyst_assess,
            )
        )
        tools.append(
            ToolSpec(
                name="execution_desk.execute",
                permission="execute",
                description="Execute a prepared draft order through guarded risk checks and the MT5 broker",
                input_schema={
                    "type": "object",
                    "properties": {
                        "draft_id": {"type": "string"},
                    },
                    "required": ["draft_id"],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "ok": {"type": "boolean"},
                        "ticket": {"type": ["string", "null"]},
                        "fill_price": {"type": ["number", "null"]},
                        "detail": {"type": "string"},
                        "blocked": {"type": "boolean"},
                        "block_reason": {"type": ["string", "null"]},
                    },
                    "required": ["ok", "detail"],
                    "additionalProperties": False,
                },
                timeout_s=30.0,
                handler=self._handle_execution_desk_execute,
            )
        )
        return tools

    def _execute_tool(
        self, tool_call: ToolCall, structured: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute one tool call, routing custom tools to Analyst/ExecutionDesk."""
        name = tool_call.name
        args = tool_call.arguments or {}

        if name == "analyst.assess":
            return self._handle_analyst_assess(self.rt, args)
        if name == "execution_desk.execute":
            return self._handle_execution_desk_execute(self.rt, args)

        # Registry tool
        tool = self._registry._tools.get(name)
        if tool is None:
            return {"error": f"unknown tool: {name}"}
        try:
            validated = tool.validate_input(args)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"invalid arguments: {exc}"}
        try:
            result = tool.handler(self.rt, validated)
            import asyncio

            if asyncio.iscoroutine(result):
                result = asyncio.run(result)
            result = tool.validate_output(result)
            return result
        except Exception as exc:  # noqa: BLE001
            return {"error": f"handler failed: {exc}"}

    # ------------------------------------------------------------------ handlers

    def _handle_analyst_assess(
        self, rt: Runtime, args: dict[str, Any]
    ) -> dict[str, Any]:
        symbol = args["symbol"]
        timeframe = args.get("timeframe", "M15")
        result = self.analyst.assess(symbol, timeframe)
        structured = {
            "kind": "analysis",
            "symbol": result.symbol,
            "timeframe": result.timeframe,
            "signal": result.signal,
            "p_up": result.p_up,
            "edge_atr": result.edge_atr,
            "draft_id": result.draft_id,
            "rationale": result.rationale,
        }
        return {
            "symbol": result.symbol,
            "timeframe": result.timeframe,
            "signal": result.signal,
            "p_up": result.p_up,
            "edge_atr": result.edge_atr,
            "draft_id": result.draft_id,
            "rationale": result.rationale,
            "data": result.data,
        }

    def _handle_execution_desk_execute(
        self, rt: Runtime, args: dict[str, Any]
    ) -> dict[str, Any]:
        draft_id = args["draft_id"]
        result = self.execution_desk.execute(draft_id)
        structured = {
            "kind": "execution",
            "draft_id": draft_id,
            "ok": result.ok,
            "ticket": result.ticket,
            "fill_price": result.fill_price,
            "detail": result.detail,
            "blocked": result.blocked,
            "block_reason": result.block_reason,
        }
        return {
            "ok": result.ok,
            "ticket": result.ticket,
            "fill_price": result.fill_price,
            "detail": result.detail,
            "blocked": result.blocked,
            "block_reason": result.block_reason,
        }

    # ------------------------------------------------------------------ messages

    def _build_messages(
        self,
        session_id: str,
        text: str,
        history: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
        chars = 0
        for message in reversed(history[-12:]):
            role = message.get("role")
            content = message.get("content", "")
            if role in {"user", "agent"} and content:
                mapped = "user" if role == "user" else "assistant"
                if chars + len(content) > 12000:
                    break
                messages.insert(1, {"role": mapped, "content": content})
                chars += len(content)
        messages.append({"role": "user", "content": text})
        return messages
