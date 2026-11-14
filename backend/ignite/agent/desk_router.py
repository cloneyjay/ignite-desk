"""Desk router: routes chat intents to Aegus capabilities.

Every user message is classified into one intent and handled by the
appropriate capability unit. Keeps the chat focused on trading:
non-trading queries are declined, identity is answered directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.ignite.agent.analyst import Analyst, AnalystResult
from backend.ignite.agent.execution_desk import ExecutionDesk, ExecutionResult
from backend.ignite.agent.session import SessionGuard, SessionState
from backend.ignite.agent.tools import ToolRegistry, ToolSpec
from backend.ignite.agent.chat_agent import ChatResponse, UnifiedChatAgent
from backend.ignite.services.runtime import Runtime


@dataclass(frozen=True)
class DeskRoute:
    """Classification of a chat message."""

    intent: str  # "identity" | "decline" | "analyze" | "execute" | "manage" | "brief" | "chat"
    symbol: str | None = None
    timeframe: str | None = None
    draft_id: str | None = None
    ticket: str | None = None
    action: str | None = None  # e.g. "close" for manage intents
    confidence: float = 0.0


@dataclass(frozen=True)
class DeskResponse:
    """Outcome of one desk-routed turn."""

    narrative: str
    tool_calls: list[dict[str, Any]]
    structured: dict[str, Any]
    route: DeskRoute


class DeskRouter:
    """Routes chat messages to trading capabilities."""

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt
        self.analyst = Analyst(rt)
        self.execution_desk = ExecutionDesk(rt)
        self.session_guard = SessionGuard(rt)
        self._base_agent = UnifiedChatAgent(rt)
        self._registry = ToolRegistry()

    def route(self, text: str, history: list[dict[str, Any]]) -> DeskResponse:
        """Classify and handle one chat message."""
        route = self._classify(text)

        if route.intent == "identity":
            return DeskResponse(
                narrative=(
                    "I'm Aegus, your personal AI day-trading desk companion for XAUUSD. "
                    "I analyse the market (live quote, bars, structure, Kronos forecast, "
                    "calendar and news), prepare risk-checked draft orders, and execute them "
                    "through MT5 under guards — daily loss limit, kill switch, spread, and "
                    "position caps. I only trade; I don't answer coding or general questions."
                ),
                tool_calls=[],
                structured={"kind": "identity"},
                route=route,
            )

        if route.intent == "decline":
            return DeskResponse(
                narrative=(
                    "I'm Aegus, a trading-only desk companion for XAUUSD day trading. "
                    "I can help with market analysis, risk, positions, news, and "
                    "guarded execution through MT5 — but I don't answer coding, "
                    "general knowledge, or non-trading questions."
                ),
                tool_calls=[],
                structured={"kind": "decline"},
                route=route,
            )

        if route.intent == "brief":
            return self._handle_brief(route)

        if route.intent == "positions":
            return self._handle_positions(route)

        if route.intent == "analyze":
            return self._handle_analyze(route)

        if route.intent == "execute":
            return self._handle_execute(route)

        if route.intent == "manage":
            return self._handle_manage(route)

        # Default: conversational chat via UnifiedChatAgent
        return self._handle_chat(text, history, route)

    # ------------------------------------------------------------------ classify

    def _classify(self, text: str) -> DeskRoute:
        import re

        text_lower = text.lower()

        # Identity
        identity_triggers = [
            r"\bwho\s+are\s+you\b",
            r"\bwhat\s+are\s+you\b",
            r"\byour\s+name\b",
            r"\bwhat\s+is\s+aegus\b",
            r"\btell\s+me\s+about\s+yourself\b",
        ]
        if any(re.search(p, text_lower) for p in identity_triggers):
            return DeskRoute(intent="identity", confidence=1.0)

        # Non-trading decline
        non_trading_signals = [
            r"\b(python|javascript|js|html|css|react|code|script|program|bug|compile|"
            r"scrape|website|app|software|function|class|variable|loop|api endpoint)\b",
            r"\b(cook|recipe|food|restaurant|diet|fitness|gym|workout)\b",
            r"\b(movie|film|tv show|netflix|music|song|book|novel|game|sport|team)\b",
            r"\b(weather|travel|hotel|flight|vacation|shopping|clothes|shoe)\b",
            r"\b(politics|election|celebrity|gossip|religion|astrology)\b",
        ]
        trading_terms = [
            r"\b(xauusd|xagusd|gold|forex|currency|pair|position[s]?|trade[s]?|order[s]?|buy|sell|long|"
            r"short|lot[s]?|pip[s]?|spread[s]?|sl|tp|stop[s]?|target[s]?|entry|exit|risk|margin|equity|"
            r"account|balance|p&l|pnl|drawdown|kronos|mt5|metatrader|mcp|brief|"
            r"analy[zs]|market|candle|bar|timeframe|signal|draft|execute|close[s]?|"
            r"autonomous|kill switch|guard|calendar|news|economic|event)\b",
        ]
        if any(re.search(p, text_lower) for p in non_trading_signals):
            if not any(re.search(p, text_lower) for p in trading_terms):
                return DeskRoute(intent="decline", confidence=0.95)

        # Execute: explicit close/modify of a ticket
        close_match = re.search(
            r"\b(?:close|exit|flatten)\s+(?:position|trade)?\s*(\d{5,})\b", text_lower
        )
        if close_match:
            return DeskRoute(
                intent="manage",
                ticket=close_match.group(1),
                action="close",
                confidence=0.98,
            )

        symbol_match = re.search(
            r"\b(?:close|exit|flatten)\s+(?:my\s+)?(?:position|trade)\s+(?:on|in)\s+([A-Z]{6,7})\b",
            text.upper(),
        )
        if symbol_match:
            return DeskRoute(
                intent="manage",
                symbol=symbol_match.group(1),
                action="close",
                confidence=0.95,
            )

        # Brief / market awareness
        brief_triggers = [
            r"\b(?:brief|outlook|anticipate|what to expect|what should i expect|"
            r"can i trade|is the market|session|weekend|market open|go no.?go)\b",
        ]
        if any(re.search(p, text_lower) for p in brief_triggers):
            sym_match = re.search(r"\b(XAUUSD|XAGUSD|[A-Z]{3}USD)\b", text.upper())
            symbol = sym_match.group(1) if sym_match else "XAUUSD"
            return DeskRoute(intent="brief", symbol=symbol, confidence=0.9)

        # Positions read
        position_triggers = [
            r"\b(?:show|list|read|check|what)\s+(?:my\s+)?(?:the\s+)?(?:current\s+)?open\s+(?:trades?|positions?)\b",
            r"\b(?:what trades?|which trades?)\s+(?:are|do i have)\s+open\b",
            r"\bshow\s+(?:my\s+)?(?:open\s+)?positions?\b",
        ]
        if any(re.search(p, text_lower) for p in position_triggers):
            return DeskRoute(intent="positions", confidence=0.95)

        # Analyze
        analyze_triggers = [
            r"\b(?:analyse|analyze|run)\s+([A-Z]{6,7})(?:\s+(M5|M15|M30|H1))?\b",
            r"\b(?:long|short)\s+([A-Z]{6,7})(?:\s+(M5|M15|M30|H1))?\b",
        ]
        for p in analyze_triggers:
            m = re.search(p, text.upper(), re.IGNORECASE)
            if m:
                symbol = m.group(1)
                timeframe = m.group(2) if len(m.groups()) > 1 and m.group(2) else "M15"
                return DeskRoute(
                    intent="analyze", symbol=symbol, timeframe=timeframe, confidence=0.95
                )

        # Execute that trade / draft
        execute_triggers = [
            r"\b(?:execute|send|place|take|enter)\s+(?:that\s+)?(?:trade|draft|setup|order)\b",
            r"\bexecute\s+that\s+trade\b",
        ]
        if any(re.search(p, text_lower) for p in execute_triggers):
            return DeskRoute(intent="execute", confidence=0.9)

        # Default to chat
        return DeskRoute(intent="chat", confidence=0.5)

    # ------------------------------------------------------------------ handlers

    def _handle_brief(self, route: DeskRoute) -> DeskResponse:
        """Market awareness: can I trade right now? What's the outlook?"""
        session = self.session_guard.evaluate()
        symbol = route.symbol or "XAUUSD"

        lines: list[str] = []
        if session.tradable:
            lines.append(f"Yes — {symbol} is tradable right now.")
        else:
            lines.append(f"No — {symbol} is not tradable right now.")
            for reason in session.reasons:
                lines.append(f"• {reason}")

        # Add live quote if terminal connected
        if session.terminal_connected:
            try:
                bid, ask = self.rt.quote(symbol)
                spread = self.rt.spread(symbol)
                lines.append(
                    f"Live quote: bid {bid:.2f}, ask {ask:.2f}, spread {spread:.0f} pts."
                )
            except Exception:  # noqa: BLE001
                lines.append("Live quote unavailable.")

        narrative = " ".join(lines)
        return DeskResponse(
            narrative=narrative,
            tool_calls=[
                {
                    "name": "session.evaluate",
                    "arguments": {},
                    "result": {
                        "tradable": session.tradable,
                        "reasons": session.reasons,
                    },
                }
            ],
            structured={
                "kind": "brief",
                "symbol": symbol,
                "tradable": session.tradable,
                "reasons": session.reasons,
            },
            route=route,
        )

    def _handle_positions(self, route: DeskRoute) -> DeskResponse:
        """Read open positions from MT5."""
        try:
            positions = self.rt.positions()
        except Exception as exc:  # noqa: BLE001
            return DeskResponse(
                narrative=f"I couldn't read positions: {exc}.",
                tool_calls=[],
                structured={"kind": "positions", "error": str(exc)},
                route=route,
            )

        tool_calls = [
            {
                "name": "account.positions",
                "arguments": {},
                "result": {"positions": positions},
            }
        ]

        if not positions:
            narrative = "There are no open MT5 positions right now."
        else:
            details = []
            for p in positions:
                details.append(
                    f"{p['symbol']} {p['side']} {p['lots']:g} lots, "
                    f"entry {p['price_open']:.2f}, current {p['price_current']:.2f}, "
                    f"SL {p['sl'] if p['sl'] is not None else 'none'}, "
                    f"TP {p['tp'] if p['tp'] is not None else 'none'}, "
                    f"P/L {p['profit']:.2f}, ticket {p['ticket']}"
                )
            narrative = (
                f"I can see {len(positions)} open MT5 position(s): " + "; ".join(details) + "."
            )

        return DeskResponse(
            narrative=narrative,
            tool_calls=tool_calls,
            structured={
                "kind": "positions",
                "positions": positions,
            },
            route=route,
        )

    def _handle_analyze(self, route: DeskRoute) -> DeskResponse:
        """Run full multi-source analysis → draft."""
        symbol = route.symbol or "XAUUSD"
        timeframe = route.timeframe or "M15"

        try:
            result = self.analyst.assess(symbol, timeframe)
        except Exception as exc:  # noqa: BLE001
            return DeskResponse(
                narrative=(
                    f"I couldn't complete the analysis for {symbol} {timeframe}: {exc}. "
                    "Try again or check the MT5 connection."
                ),
                tool_calls=[],
                structured={"kind": "analysis", "error": str(exc)},
                route=route,
            )

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

        draft_line = ""
        if result.draft_id:
            draft_line = (
                f"\nDraft ready: {result.draft_id[:8]}… — say “execute that trade” to send it."
            )

        narrative = (
            f"{result.rationale}{draft_line}"
        )

        return DeskResponse(
            narrative=narrative,
            tool_calls=[
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
            ],
            structured=structured,
            route=route,
        )

    def _handle_execute(self, route: DeskRoute) -> DeskResponse:
        """Execute the most recent draft for the symbol."""
        # Find the latest pending draft
        drafts = self.rt.store.pending_drafts(limit=20)
        draft = None
        for d in drafts:
            if d.get("state") == "draft" and not d.get("blocked"):
                draft = d
                break

        if not draft:
            return DeskResponse(
                narrative=(
                    "I don't have a ready-to-execute draft. Ask me to analyse a symbol "
                    "first, and I'll prepare one you can execute."
                ),
                tool_calls=[],
                structured={"kind": "execute", "error": "no draft"},
                route=route,
            )

        session = self.session_guard.evaluate()
        if not session.tradable:
            return DeskResponse(
                narrative=(
                    f"I can't execute right now: {', '.join(session.reasons)}. "
                    "Fix the blocker (e.g., disable kill switch, wait for session open) "
                    "and try again."
                ),
                tool_calls=[],
                structured={"kind": "execute", "error": "guards blocked"},
                route=route,
            )

        try:
            result = self.execution_desk.execute(draft["id"])
        except Exception as exc:  # noqa: BLE001
            return DeskResponse(
                narrative=(
                    f"Execution failed for draft {draft['id'][:8]}…: {exc}."
                ),
                tool_calls=[],
                structured={"kind": "execute", "error": str(exc)},
                route=route,
            )

        if result.ok:
            narrative = (
                f"Executed {draft['side']} {draft['lots']:g} lots on {draft.get('symbol', 'XAUUSD')}. "
                f"Ticket {result.ticket}, fill {result.fill_price:.2f}. "
                f"SL {draft['sl']:.2f}, TP {draft['tp']:.2f}."
            )
        else:
            narrative = (
                f"Execution blocked: {result.block_reason or result.detail}. "
                "No order was sent."
            )

        return DeskResponse(
            narrative=narrative,
            tool_calls=[
                {
                    "name": "execution_desk.execute",
                    "arguments": {"draft_id": draft["id"]},
                    "result": {
                        "ok": result.ok,
                        "ticket": result.ticket,
                        "fill_price": result.fill_price,
                        "detail": result.detail,
                        "blocked": result.blocked,
                        "block_reason": result.block_reason,
                    },
                }
            ],
            structured={
                "kind": "execute",
                "draft_id": draft["id"],
                "ok": result.ok,
                "ticket": result.ticket,
                "fill_price": result.fill_price,
                "blocked": result.blocked,
                "block_reason": result.block_reason,
            },
            route=route,
        )

    def _handle_manage(self, route: DeskRoute) -> DeskResponse:
        """Position management: close, modify SL/TP."""
        if route.action == "close" and route.ticket:
            try:
                result = self.rt.gateway.close(route.ticket, "CHAT")
            except Exception as exc:  # noqa: BLE001
                return DeskResponse(
                    narrative=f"Close failed for ticket {route.ticket}: {exc}.",
                    tool_calls=[],
                    structured={"kind": "manage", "error": str(exc)},
                    route=route,
                )
            if result.ok:
                narrative = f"Close request sent for position {route.ticket}."
            else:
                narrative = f"Close rejected for {route.ticket}: {result.detail}."
            return DeskResponse(
                narrative=narrative,
                tool_calls=[
                    {
                        "name": "execution.close_position",
                        "arguments": {"ticket": route.ticket},
                        "result": {
                            "ok": result.ok,
                            "code": result.code,
                            "detail": result.detail,
                        },
                    }
                ],
                structured={
                    "kind": "manage",
                    "action": "close",
                    "ticket": route.ticket,
                    "ok": result.ok,
                },
                route=route,
            )

        return DeskResponse(
            narrative=(
                "I can close a position by ticket (e.g. “close position 12345”) or "
                "by symbol (e.g. “close my XAUUSD position”). Tell me which one."
            ),
            tool_calls=[],
            structured={"kind": "manage", "error": "ambiguous"},
            route=route,
        )

    def _handle_chat(
        self, text: str, history: list[dict[str, Any]], route: DeskRoute
    ) -> DeskResponse:
        """Conversational fallback via UnifiedChatAgent."""
        try:
            response = self._base_agent.respond(
                "session", text, history
            )
        except Exception as exc:  # noqa: BLE001
            response = ChatResponse(
                narrative=(
                    "I'm having trouble processing that right now. "
                    "Try asking about your positions, risk, or a market brief."
                ),
                tool_calls=[],
                structured={"kind": "chat", "error": str(exc)},
            )

        return DeskResponse(
            narrative=response.narrative,
            tool_calls=response.tool_calls,
            structured=response.structured,
            route=route,
        )
