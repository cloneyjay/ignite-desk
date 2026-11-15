"""UnifiedChatAgent: LLM-first conversational agent with full MCP tool access.

The LLM (NVIDIA NIM) is the only decision maker. It receives the user's
message with the complete tool set (market data, Kronos forecast, risk
guards, MT5 execution, strategy management, desk memory) as OpenAI functions
and decides which tools to call, in what order, and how to synthesize the
results into plain English.

There is no deterministic router, no regex intent detection, and no
canned-response fallback. If the model cannot be reached the agent says so
honestly instead of inventing a market read.

The LLM invocation loop itself lives in ``LLMHarness`` so that chat messages
and scheduler ticks route through the identical harness with the identical
tool set and context budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.ignite.agent.analyst import Analyst
from backend.ignite.agent.execution_desk import ExecutionDesk
from backend.ignite.agent.llm_harness import HarnessResult, LLMHarness
from backend.ignite.agent.tools import ToolRegistry, ToolSpec, permission_allowed
from backend.ignite.llm.client import LLMError, LLMUnavailable, ToolCall
from backend.ignite.services.runtime import Runtime

UNREACHABLE_NARRATIVE = (
    "I can't reach the language model right now, so I can't analyse the market "
    "or give you a real answer. I won't guess without it. Check the NVIDIA NIM "
    "provider configuration (or the backup provider) and try again."
)


@dataclass(frozen=True)
class ChatResponse:
    """Outcome of one chat turn."""

    narrative: str
    tool_calls: list[dict[str, Any]]
    structured: dict[str, Any]
    provider: str | None = None
    model: str | None = None


SYSTEM_PROMPT = """You are Aegus, an AI day-trading desk companion for XAUUSD.

You are the PRIMARY decision maker. You receive live market data, Kronos
forecasts, and MT5 execution tools as function calls. You decide which tools
to call, in what order, and how to synthesize the results into plain English.

READ TOOLS (always available):
- market.quote: Live bid/ask/spread for a symbol
- market.bars: OHLCV candles for symbol/timeframe
- market.structure: Trend, EMAs, VWAP, ATR, swing highs/lows
- market.spec: Symbol contract specifications
- account.snapshot: Account equity, balance, margin
- account.positions: Open positions with P&L
- position.list / position.history: Managed positions and closed trades
- news.calendar: Economic calendar events (high impact windows)
- news.headlines: Recent terminal news
- web.search: Web search for current news and context (optional; if it is not
  configured the tool says so - do not present its absence as a finding)

PREPARE TOOLS (analysis and drafting):
- forecast.run: KRONOS forecast - probabilistic price direction (p_up, edge_atr, dispersion)
- analysis.run: Full deterministic analysis → draft order with entry/SL/TP
- risk.evaluate: Validate order against risk guards
- draft.create / draft.evaluate: Create and inspect time-limited order drafts

EXECUTE TOOLS (only when Autonomous mode is enabled AND kill switch is off):
- execution.place_order: Send market order with SL/TP
- execution.modify_position: Modify stop loss / take profit
- execution.close_position: Close a position

STRATEGY AND MEMORY TOOLS:
- strategy.create / strategy.compile / strategy.backtest / strategy.list / strategy.get
- scratchpad.* / episodic.* / semantic.* / procedural.*: desk memory

INSTRUCTIONS:
1. ALWAYS use tools to get live data before answering market questions. Never invent prices.
2. Use Kronos (forecast.run) for directional probability - do not guess direction yourself.
3. For trade requests: analyse first (market data + Kronos + analysis), validate risk (risk.evaluate), then execute only if all guards pass.
4. Explain your reasoning in plain English: what you checked, what it means, what could invalidate it.
5. If uncertain, ask clarifying questions rather than guessing.
6. Never bypass safety guards. If a tool returns an error, say so plainly.
7. Never promise profit or hide a blocked trade.
8. The user must explicitly confirm before any order is sent (Autonomous mode must be on for automatic execution).
9. Stay on the desk: trading, market analysis, risk, positions, strategy, and account state.
10. The tool list you receive is already filtered by the desk's autonomy level. If an execution tool is missing, say that execution is disabled and name what has to change (autonomous mode, autonomy level, kill switch). Never claim an order was sent without a tool result.

TOOL USAGE FORMAT:
When you need information, call the relevant tool. When you have all the information,
synthesize it into a clear, trader-to-trader response. Do not chain unnecessary tool calls.
"""


class UnifiedChatAgent:
    """LLM-first conversational agent. The model decides which tools to call.

    Delegates the bounded tool-calling loop to ``LLMHarness`` so chat and the
    autonomous scheduler share one decision brain.
    """

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt
        self._registry = ToolRegistry()

    def respond(
        self, session_id: str, text: str, history: list[dict[str, Any]]
    ) -> ChatResponse:
        """Handle one chat turn: the model decides which tools to call."""
        messages = self._build_messages(session_id, text, history)
        tool_specs = self._get_tools()

        def execute(name: str, args: dict[str, Any]) -> dict[str, Any]:
            return self._execute_tool(ToolCall(id="", name=name, arguments=args))

        try:
            result: HarnessResult = LLMHarness(
                self.rt,
                system_prompt=SYSTEM_PROMPT,
                tool_specs=tool_specs,
                execute=execute,
            ).run(messages)
        except LLMUnavailable as exc:
            attempts = "; ".join(exc.attempts) if exc.attempts else str(exc)
            return ChatResponse(
                narrative=UNREACHABLE_NARRATIVE,
                tool_calls=[],
                structured={"kind": "llm_unavailable", "error": attempts[:500]},
            )
        except LLMError as exc:
            return ChatResponse(
                narrative=(
                    "The model call failed, so this answer is incomplete. "
                    f"Detail: {exc}"
                ),
                tool_calls=[],
                structured={"kind": "llm_error", "error": str(exc)},
            )

        return ChatResponse(
            narrative=result.text,
            tool_calls=result.tool_calls,
            structured={},
            provider=result.provider,
            model=result.model,
        )

    # ------------------------------------------------------------------- tools

    def _get_tools(self) -> list[ToolSpec]:
        """All available tools: MCP registry + Analyst + ExecutionDesk + web.search.

        ``analyst.assess`` is always offered: it only reads the market and
        produces an inert draft, and execution stays guarded downstream.
        ``execution_desk.execute`` follows the same gate as every other
        execute tool.
        """
        mode = self.rt.config().operating_mode
        kill_switch = self.rt.kill_switch()
        autonomy_level = self.rt.config().autonomy_level
        can_execute = permission_allowed(
            "execute", mode, kill_switch, autonomy_level
        )

        tools = self._registry.get_available(mode, kill_switch, autonomy_level)

        tools.append(
            ToolSpec(
                name="analyst.assess",
                permission="prepare",
                description="Run full multi-source market analysis: live quote, bars, structure, Kronos forecast, news → draft order with rationale",
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

        if can_execute:
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

        tools.append(
            ToolSpec(
                name="web.search",
                permission="read",
                description="Search the web for current market news, economic events, and price context",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "results": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "title": {"type": "string"},
                                    "url": {"type": "string"},
                                    "snippet": {"type": "string"},
                                },
                                "required": ["title", "url", "snippet"],
                                "additionalProperties": False,
                            },
                        },
                        "message": {"type": "string"},
                    },
                    "required": ["results"],
                    "additionalProperties": False,
                },
                timeout_s=15.0,
                handler=self._handle_web_search,
            )
        )

        return tools

    def _execute_tool(self, tool_call: ToolCall) -> dict[str, Any]:
        """Execute one tool call, routing custom tools to Analyst/ExecutionDesk,
        everything else to the MCP ToolRegistry."""
        name = tool_call.name
        args = tool_call.arguments or {}

        if name == "analyst.assess":
            return self._handle_analyst_assess(self.rt, args)
        if name == "execution_desk.execute":
            return self._handle_execution_desk_execute(self.rt, args)

        tool = self._registry.get(name)
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

    def _handle_analyst_assess(
        self, rt: Runtime, args: dict[str, Any]
    ) -> dict[str, Any]:
        """Run full multi-source analysis via Analyst."""
        analyst = Analyst(rt)
        result = analyst.assess(args["symbol"], args.get("timeframe", "M15"))
        return {
            "kind": "analysis",
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
        """Execute a draft via ExecutionDesk."""
        desk = ExecutionDesk(rt)
        result = desk.execute(args["draft_id"])
        return {
            "kind": "execution",
            "ok": result.ok,
            "ticket": result.ticket,
            "fill_price": result.fill_price,
            "detail": result.detail,
            "blocked": result.blocked,
            "block_reason": result.block_reason,
        }

    def _handle_web_search(
        self, rt: Runtime, args: dict[str, Any]
    ) -> dict[str, Any]:
        """Search the web for current market context."""
        query = args["query"]
        search_url = getattr(rt.settings, "search_api_url", None) or ""
        search_key = getattr(rt.settings, "search_api_key", None) or ""

        if search_url and search_key:
            try:
                import httpx

                with httpx.Client(timeout=10.0) as client:
                    resp = client.get(
                        search_url,
                        params={"q": query, "key": search_key},
                        headers={"Accept": "application/json"},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        results = []
                        for item in data.get("items", data.get("results", []))[:5]:
                            results.append({
                                "title": item.get("title", ""),
                                "url": item.get("link", item.get("url", "")),
                                "snippet": item.get("snippet", item.get("description", "")),
                            })
                        return {"results": results}
            except Exception:  # noqa: BLE001
                pass

        try:
            import httpx

            with httpx.Client(timeout=10.0, headers={"User-Agent": "Mozilla/5.0"}) as client:
                resp = client.get(
                    "https://api.duckduckgo.com/",
                    params={"q": query, "format": "json", "no_html": "1", "no_redirect": "1"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    results = []
                    for topic in data.get("RelatedTopics", [])[:5]:
                        if isinstance(topic, dict) and topic.get("Text"):
                            results.append({
                                "title": topic.get("Text", "")[:120],
                                "url": topic.get("FirstURL", ""),
                                "snippet": topic.get("Text", ""),
                            })
                    if results:
                        return {"results": results}
        except Exception:  # noqa: BLE001
            pass

        return {
            "results": [],
            "message": "Web search is not configured. Set SEARCH_API_URL and SEARCH_API_KEY to enable live web results.",
        }

    def _build_messages(
        self,
        session_id: str,
        text: str,
        history: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Build message history for the model. ``session_id`` is accepted for
        call-site symmetry; conversation history is passed in explicitly."""
        messages: list[dict[str, Any]] = []
        chars = 0
        for message in reversed(history[-12:]):
            role = message.get("role")
            content = message.get("content", "")
            if role in {"user", "agent"} and content:
                mapped = "user" if role == "user" else "assistant"
                if chars + len(content) > 12000:
                    break
                messages.insert(0, {"role": mapped, "content": content})
                chars += len(content)
        messages.append({"role": "user", "content": text})
        return messages
