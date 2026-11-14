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

        # --- Identity gate: answer "who are you" without touching the model ---
        identity = self._detect_identity(text)
        if identity is not None:
            return ChatResponse(
                narrative=identity,
                tool_calls=[],
                structured={"kind": "identity"},
            )

        # --- Niche scope: decline clearly non-trading queries ---
        if self._is_non_trading(text):
            return ChatResponse(
                narrative=(
                    "I'm Aegus, a trading-only desk companion for XAUUSD day trading. "
                    "I can help with market analysis, risk, positions, news, and "
                    "guarded execution through MT5 — but I don't answer coding, "
                    "general knowledge, or non-trading questions."
                ),
                tool_calls=[],
                structured={"kind": "decline"},
            )

        # Detect market research / brief intent and route to Analyst directly
        # so the agent gathers live data instead of chatting from knowledge.
        analysis_intent = self._detect_analysis_intent(text)
        if analysis_intent:
            symbol, timeframe = analysis_intent
            try:
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
                narrative = (
                    f"{result.rationale}\n\n"
                    f"Live quote: bid {result.data.get('quote', {}).get('bid', 'n/a')}, "
                    f"ask {result.data.get('quote', {}).get('ask', 'n/a')}, "
                    f"spread {result.data.get('quote', {}).get('spread', 'n/a')} pts.\n"
                    f"Trend: {result.data.get('structure', {}).get('trend', 'n/a')}, "
                    f"ATR {result.data.get('structure', {}).get('atr', 'n/a'):.2f}."
                )
                tool_call_records = [
                    {
                        "name": "analyst.assess",
                        "arguments": {"symbol": symbol, "timeframe": timeframe},
                        "result": {
                            "symbol": result.symbol,
                            "timeframe": result.timeframe,
                            "signal": result.signal,
                            "p_up": result.p_up,
                            "edge_atr": result.edge_atr,
                            "draft_id": result.draft_id,
                            "rationale": result.rationale,
                        },
                    }
                ]
                return ChatResponse(
                    narrative=narrative,
                    tool_calls=tool_call_records,
                    structured=structured,
                )
            except Exception as exc:  # noqa: BLE001
                # Fall through to LLM conversation if analysis fails
                pass

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

    def _detect_analysis_intent(
        self, text: str
    ) -> tuple[str, str] | None:
        """Detect market research / brief / price-action requests.

        Returns (symbol, timeframe) when the user is asking for live market
        analysis rather than a general conversation.
        """
        import re

        text_lower = text.lower()
        triggers = [
            "brief", "price action", "anticipate", "outlook", "what to expect",
            "what should i expect", "research", "analyze", "analyse",
            "market read", "setup", "signal",
        ]
        if not any(w in text_lower for w in triggers):
            return None

        # Extract symbol (default XAUUSD). Match forex/crypto patterns like
        # XAUUSD, EURUSD, GBPUSD, BTCUSD, or gold/xau mentions.
        sym_match = re.search(r"\b(XAUUSD|XAGUSD|[A-Z]{3}USD)\b", text.upper())
        if not sym_match and any(w in text_lower for w in ("gold", "xau")):
            symbol = "XAUUSD"
        elif sym_match:
            symbol = sym_match.group(1)
        else:
            symbol = "XAUUSD"

        # Extract timeframe (default M15)
        tf_match = re.search(r"\b(M5|M15|M30|H1)\b", text.upper())
        timeframe = tf_match.group(1) if tf_match else "M15"

        return (symbol, timeframe)

    def _detect_identity(self, text: str) -> str | None:
        """Answer identity questions deterministically; no model needed."""
        import re

        text_lower = text.lower()
        identity_triggers = [
            r"\bwho\s+are\s+you\b",
            r"\bwhat\s+are\s+you\b",
            r"\byour\s+name\b",
            r"\bwhat\s+is\s+aegus\b",
            r"\btell\s+me\s+about\s+yourself\b",
        ]
        if not any(re.search(p, text_lower) for p in identity_triggers):
            return None
        return (
            "I'm Aegus, your personal AI day-trading desk companion for XAUUSD. "
            "I analyse the market (live quote, bars, structure, Kronos forecast, "
            "calendar and news), prepare risk-checked draft orders, and execute them "
            "through MT5 under guards — daily loss limit, kill switch, spread, and "
            "position caps. I only trade; I don't answer coding or general questions."
        )

    def _is_non_trading(self, text: str) -> bool:
        """Return True when the query is clearly outside the trading niche."""
        import re

        text_lower = text.lower()

        # If it mentions trading terms, it's in scope — check first so words
        # like "show" (in "show my positions") aren't misclassified.
        trading_terms = [
            r"\b(xauusd|xagusd|gold|forex|currency|pair|position[s]?|trade[s]?|order[s]?|buy|sell|long|"
            r"short|lot[s]?|pip[s]?|spread[s]?|sl|tp|stop[s]?|target[s]?|entry|exit|risk|margin|equity|"
            r"account|balance|p&l|pnl|drawdown|kronos|mt5|metatrader|mcp|brief|"
            r"analy[zs]|market|candle|bar|timeframe|signal|draft|execute|close[s]?|"
            r"autonomous|kill switch|guard|calendar|news|economic|event)\b",
        ]
        # Check trading terms first so words like "show" (in "show my positions")
        # aren't misclassified as non-trading.
        if any(re.search(p, text_lower) for p in trading_terms):
            return False

        # Short greetings without trading context are allowed (conversational)
        greetings = {"hi", "hello", "hey", "good morning", "good afternoon", "good evening"}
        if text_lower.strip() in greetings or len(text_lower.split()) <= 2:
            return False

        # Explicit non-trading topic signals
        non_trading_signals = [
            r"\b(python|javascript|js|html|css|react|code|script|program|bug|compile|"
            r"scrape|website|app|software|function|class|variable|loop|api endpoint)\b",
            r"\b(cook|recipe|food|restaurant|diet|fitness|gym|workout)\b",
            r"\b(movie|film|tv show|netflix|music|song|book|novel|game|sport|team)\b",
            r"\b(weather|travel|hotel|flight|vacation|shopping|clothes|shoe)\b",
            r"\b(politics|election|celebrity|gossip|religion|astrology)\b",
        ]
        if any(re.search(p, text_lower) for p in non_trading_signals):
            return True

        # Ambiguous short queries without trading terms: treat as non-trading to stay niche
        if len(text_lower.split()) <= 6:
            return True

        return False

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
        if name == "web.search":
            return self._handle_web_search(self.rt, args)

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

    def _handle_web_search(
        self, rt: Runtime, args: dict[str, Any]
    ) -> dict[str, Any]:
        """Search the web for current market context.

        Tries the configured search API first; falls back to DuckDuckGo
        Instant Answer API (no API key required). Returns results or a
        configuration message.
        """
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
                            results.append(
                                {
                                    "title": item.get("title", ""),
                                    "url": item.get("link", item.get("url", "")),
                                    "snippet": item.get("snippet", item.get("description", "")),
                                }
                            )
                        return {"results": results}
            except Exception:  # noqa: BLE001
                pass

        # No-key fallback: DuckDuckGo Instant Answer API (JSON, no parser needed)
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
                            results.append(
                                {
                                    "title": topic.get("Text", "")[:120],
                                    "url": topic.get("FirstURL", ""),
                                    "snippet": topic.get("Text", ""),
                                }
                            )
                    if results:
                        return {"results": results}
        except Exception:  # noqa: BLE001
            pass

        return {
            "results": [],
            "message": "Web search is not configured. Set SEARCH_API_URL and SEARCH_API_KEY to enable live web results.",
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
