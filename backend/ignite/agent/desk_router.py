"""Desk router: routes chat intents to Aegus capabilities.

Every user message is classified into one intent and handled by the
appropriate capability unit. Keeps the chat focused on trading:
non-trading queries are declined, identity is answered directly.
"""

from __future__ import annotations

import json
import re
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
    action: str | None = None  # e.g. "close", "modify", "breakeven", "trail", "scale_out"
    price: float | None = None  # target price for modify
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
            r"\b(?:close|exit|flatten)\s+(?:my\s+)?(?:([a-z]{6,7})\s+)?(?:position|trade)\b",
            text_lower,
        )
        if symbol_match:
            return DeskRoute(
                intent="manage",
                symbol=symbol_match.group(1).upper(),
                action="close",
                confidence=0.95,
            )

        # Modify SL/TP / breakeven / trail
        modify_match = re.search(
            r"\b(?:modify|change|set|move|update)\s+(?:my\s+)?(?:stop|sl|tp|take profit|stop loss)\s+(?:to\s+)?([\d.]+)\b",
            text_lower,
        )
        if modify_match:
            sym_match = re.search(r"\b(XAUUSD|XAGUSD|[A-Z]{3}USD)\b", text.upper())
            ticket_match = re.search(r"\b(\d{5,})\b", text)
            return DeskRoute(
                intent="manage",
                symbol=sym_match.group(1) if sym_match else None,
                ticket=ticket_match.group(1) if ticket_match else None,
                action="modify",
                price=float(modify_match.group(1)),
                confidence=0.9,
            )

        # Breakeven
        be_match = re.search(
            r"\b(?:move\s+to\s+|set\s+to\s+)?(?:breakeven|b\.?e\.?|be)\b",
            text_lower,
        )
        if be_match:
            sym_match = re.search(r"\b(XAUUSD|XAGUSD|[A-Z]{3}USD)\b", text.upper())
            ticket_match = re.search(r"\b(\d{5,})\b", text)
            return DeskRoute(
                intent="manage",
                symbol=sym_match.group(1) if sym_match else None,
                ticket=ticket_match.group(1) if ticket_match else None,
                action="breakeven",
                confidence=0.9,
            )

        # Trailing stop
        trail_match = re.search(
            r"\b(?:trail|trailing)\s+(?:my\s+)?(?:stop|sl)\b",
            text_lower,
        )
        if trail_match:
            sym_match = re.search(r"\b(XAUUSD|XAGUSD|[A-Z]{3}USD)\b", text.upper())
            ticket_match = re.search(r"\b(\d{5,})\b", text)
            return DeskRoute(
                intent="manage",
                symbol=sym_match.group(1) if sym_match else None,
                ticket=ticket_match.group(1) if ticket_match else None,
                action="trail",
                confidence=0.9,
            )

        # Scale out / partial close
        scale_match = re.search(
            r"\b(?:scale\s+out|partial\s+close|take\s+partial\s+profit)\b",
            text_lower,
        )
        if scale_match:
            sym_match = re.search(r"\b(XAUUSD|XAGUSD|[A-Z]{3}USD)\b", text.upper())
            ticket_match = re.search(r"\b(\d{5,})\b", text)
            return DeskRoute(
                intent="manage",
                symbol=sym_match.group(1) if sym_match else None,
                ticket=ticket_match.group(1) if ticket_match else None,
                action="scale_out",
                confidence=0.9,
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

    def _handle_brief(self, route: DeskRoute) -> DeskRoute:
        """Market awareness: can I trade right now? What's the outlook?

        Always runs the Analyst so the user gets a market outlook even when
        the market is closed (e.g. weekend). Session status is reported first,
        then the outlook.
        """
        session = self.session_guard.evaluate()
        symbol = route.symbol or "XAUUSD"

        lines: list[str] = []
        if session.tradable:
            lines.append(f"Yes — {symbol} is tradable right now.")
        else:
            lines.append(f"No — {symbol} is not tradable right now.")
            for reason in session.reasons:
                lines.append(f"• {reason}")

        # Always gather live market data for the outlook, even when closed.
        try:
            result = self.analyst.assess(symbol, "M15")
        except Exception as exc:  # noqa: BLE001
            return DeskResponse(
                narrative=(
                    " ".join(lines)
                    + f" I couldn't pull market data for the outlook: {exc}."
                ),
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

        quote = result.data.get("quote", {}) or {}
        structure = result.data.get("structure", {}) or {}
        calendar = result.data.get("calendar", []) or []
        forecast = result.data.get("forecast", {}) or {}

        bid = quote.get("bid")
        ask = quote.get("ask")
        spread = quote.get("spread")
        if bid is not None and ask is not None:
            lines.append(
                f"Live quote: bid {bid:.2f}, ask {ask:.2f}, "
                f"spread {spread:.0f} pts."
            )

        trend = structure.get("trend", "unknown")
        last_close = structure.get("last_close")
        atr = structure.get("atr")
        vwap = structure.get("vwap")
        price_vs_vwap = structure.get("price_vs_vwap")
        recent_high = structure.get("recent_high")
        recent_low = structure.get("recent_low")

        lines.append(
            f"Structure: {trend} trend, last close {last_close:.2f}, "
            f"ATR14 {atr:.2f}, price {price_vs_vwap} VWAP ({vwap:.2f})."
        )
        if recent_high and recent_low:
            lines.append(
                f"Recent range: {recent_low:.2f}–{recent_high:.2f}."
            )

        p_up = result.p_up
        edge_atr = result.edge_atr
        lines.append(
            f"Kronos: p_up {p_up:.0%}, edge {edge_atr:+.2f} ATR → "
            f"{'bullish bias' if p_up > 0.55 else 'bearish bias' if p_up < 0.45 else 'neutral'}."
        )

        high_impact = [
            e for e in calendar
            if str(e.get("importance", "")).lower() == "high"
        ]
        if high_impact:
            names = ", ".join(e.get("name", "event") for e in high_impact[:3])
            lines.append(f"High-impact news ahead: {names}.")

        if not session.tradable:
            lines.append(
                "The market is closed, so no new entries can be sent until "
                "session reopens and guards clear. Use this outlook to plan "
                "your entries for next week."
            )

        narrative = " ".join(lines)

        tool_calls = [
            {
                "name": "session.evaluate",
                "arguments": {},
                "result": {
                    "tradable": session.tradable,
                    "reasons": session.reasons,
                },
            },
            {
                "name": "analyst.assess",
                "arguments": {"symbol": symbol, "timeframe": "M15"},
                "result": {
                    "symbol": result.symbol,
                    "timeframe": result.timeframe,
                    "signal": result.signal,
                    "p_up": result.p_up,
                    "edge_atr": result.edge_atr,
                    "draft_id": result.draft_id,
                    "rationale": result.rationale,
                },
            },
        ]

        return DeskResponse(
            narrative=narrative,
            tool_calls=tool_calls,
            structured={
                "kind": "brief",
                "symbol": symbol,
                "tradable": session.tradable,
                "reasons": session.reasons,
                "signal": result.signal,
                "p_up": result.p_up,
                "edge_atr": result.edge_atr,
                "draft_id": result.draft_id,
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
        """Position management: close, modify SL/TP, breakeven, trail, scale out."""
        session = self.session_guard.evaluate()

        # Resolve target position: by ticket or by symbol
        target = self._resolve_position(route)
        if target is None:
            return DeskResponse(
                narrative=(
                    "I couldn't find a matching position. "
                    "Specify a ticket (e.g. “close position 12345”) or a symbol "
                    "(e.g. “close my XAUUSD position”)."
                ),
                tool_calls=[],
                structured={"kind": "manage", "error": "no_position"},
                route=route,
            )

        ticket = str(target["ticket"])
        symbol = target["symbol"]
        side = target["side"]
        current_sl = target.get("sl")
        current_tp = target.get("tp")
        entry_price = target.get("entry_price")
        current_price = target.get("price_current") or entry_price

        if route.action == "close":
            return self._handle_manage_close(route, ticket, target)

        if route.action == "modify":
            return self._handle_manage_modify(route, ticket, symbol, side, current_sl, current_tp, entry_price, current_price)

        if route.action == "breakeven":
            return self._handle_manage_breakeven(route, ticket, symbol, side, entry_price, current_sl, current_tp)

        if route.action == "trail":
            return self._handle_manage_trail(route, ticket, symbol, side, current_sl, current_tp, entry_price, current_price)

        if route.action == "scale_out":
            return self._handle_manage_scale_out(route, ticket, symbol, side, target)

        return DeskResponse(
            narrative=(
                "I can close a position, modify its SL/TP, move to breakeven, "
                "trail the stop, or scale out. Tell me what you'd like to do."
            ),
            tool_calls=[],
            structured={"kind": "manage", "error": "ambiguous"},
            route=route,
        )

    def _resolve_position(self, route: DeskRoute) -> dict[str, Any] | None:
        """Find a position by ticket or symbol."""
        try:
            positions = self.rt.positions()
        except Exception:  # noqa: BLE001
            return None

        if route.ticket:
            for p in positions:
                if str(p["ticket"]) == route.ticket:
                    return p
            return None

        if route.symbol:
            matches = [p for p in positions if p["symbol"] == route.symbol]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                return None  # ambiguous
            return None

        return None

    def _handle_manage_close(
        self, route: DeskRoute, ticket: str, target: dict[str, Any]
    ) -> DeskResponse:
        """Close a position by ticket."""
        try:
            result = self.rt.gateway.close(ticket, "CHAT")
        except Exception as exc:  # noqa: BLE001
            return DeskResponse(
                narrative=f"Close failed for ticket {ticket}: {exc}.",
                tool_calls=[],
                structured={"kind": "manage", "error": str(exc)},
                route=route,
            )
        if result.ok:
            narrative = f"Close request sent for {target['symbol']} position {ticket}."
        else:
            narrative = f"Close rejected for {ticket}: {result.detail}."
        return DeskResponse(
            narrative=narrative,
            tool_calls=[
                {
                    "name": "execution.close_position",
                    "arguments": {"ticket": ticket},
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
                "ticket": ticket,
                "ok": result.ok,
            },
            route=route,
        )

    def _handle_manage_modify(
        self,
        route: DeskRoute,
        ticket: str,
        symbol: str,
        side: str,
        current_sl: float | None,
        current_tp: float | None,
        entry_price: float | None,
        current_price: float | None,
    ) -> DeskResponse:
        """Modify SL or TP of a position."""
        new_price = route.price
        if new_price is None:
            return DeskResponse(
                narrative="I need a price to modify to. "
                "Say “move my stop to 3930” or “set TP to 3970”.",
                tool_calls=[],
                structured={"kind": "manage", "error": "no_price"},
                route=route,
            )

        # Determine whether the price is for SL or TP based on side and price level
        side_upper = side.upper()
        new_sl = current_sl
        new_tp = current_tp

        if side_upper == "BUY":
            if new_price < current_price:
                new_sl = new_price  # SL below current price for buy
            else:
                new_tp = new_price  # TP above current price for buy
        elif side_upper == "SELL":
            if new_price > current_price:
                new_sl = new_price  # SL above current price for sell
            else:
                new_tp = new_price  # TP below current price for sell

        try:
            result = self.rt.gateway.modify(ticket, new_sl, new_tp)
        except Exception as exc:  # noqa: BLE001
            return DeskResponse(
                narrative=f"Modify failed for ticket {ticket}: {exc}.",
                tool_calls=[],
                structured={"kind": "manage", "error": str(exc)},
                route=route,
            )
        if result.ok:
            changed = []
            if new_sl is not None and new_sl != current_sl:
                changed.append(f"SL {new_sl:.2f}")
            if new_tp is not None and new_tp != current_tp:
                changed.append(f"TP {new_tp:.2f}")
            narrative = f"Modified {ticket}: {', '.join(changed)}."
        else:
            narrative = f"Modify rejected for {ticket}: {result.detail}."
        return DeskResponse(
            narrative=narrative,
            tool_calls=[
                {
                    "name": "execution.modify_position",
                    "arguments": {"ticket": ticket, "sl": new_sl, "tp": new_tp},
                    "result": {
                        "ok": result.ok,
                        "code": result.code,
                        "detail": result.detail,
                    },
                }
            ],
            structured={
                "kind": "manage",
                "action": "modify",
                "ticket": ticket,
                "new_sl": new_sl,
                "new_tp": new_tp,
                "ok": result.ok,
            },
            route=route,
        )

    def _handle_manage_breakeven(
        self,
        route: DeskRoute,
        ticket: str,
        symbol: str,
        side: str,
        entry_price: float | None,
        current_sl: float | None,
        current_tp: float | None,
    ) -> DeskResponse:
        """Move stop to breakeven (entry price)."""
        if entry_price is None:
            return DeskResponse(
                narrative="I don't have an entry price for this position.",
                tool_calls=[],
                structured={"kind": "manage", "error": "no_entry"},
                route=route,
            )

        try:
            result = self.rt.gateway.modify(ticket, entry_price, current_tp)
        except Exception as exc:  # noqa: BLE001
            return DeskResponse(
                narrative=f"Breakeven failed for ticket {ticket}: {exc}.",
                tool_calls=[],
                structured={"kind": "manage", "error": str(exc)},
                route=route,
            )
        if result.ok:
            narrative = f"Moved {ticket} stop to breakeven at {entry_price:.2f}."
        else:
            narrative = f"Breakeven rejected for {ticket}: {result.detail}."
        return DeskResponse(
            narrative=narrative,
            tool_calls=[
                {
                    "name": "execution.modify_position",
                    "arguments": {"ticket": ticket, "sl": entry_price, "tp": current_tp},
                    "result": {
                        "ok": result.ok,
                        "code": result.code,
                        "detail": result.detail,
                    },
                }
            ],
            structured={
                "kind": "manage",
                "action": "breakeven",
                "ticket": ticket,
                "entry_price": entry_price,
                "ok": result.ok,
            },
            route=route,
        )

    def _handle_manage_trail(
        self,
        route: DeskRoute,
        ticket: str,
        symbol: str,
        side: str,
        current_sl: float | None,
        current_tp: float | None,
        entry_price: float | None,
        current_price: float | None,
    ) -> DeskResponse:
        """Trail the stop using config trail_sl_atr."""
        atr = self._get_atr(symbol)
        if atr is None or atr == 0:
            return DeskResponse(
                narrative="I can't compute ATR for trailing right now.",
                tool_calls=[],
                structured={"kind": "manage", "error": "no_atr"},
                route=route,
            )

        config = self.rt.config()
        trail_atr = getattr(config, "trail_sl_atr", 1.5)
        side_upper = side.upper()

        if side_upper == "BUY":
            new_sl = current_price - trail_atr * atr
            new_sl = min(new_sl, current_price - 0.01)
            if current_sl is not None and new_sl <= current_sl:
                return DeskResponse(
                    narrative=(
                        f"Trailing stop would not improve the current SL "
                        f"({current_sl:.2f}). Price hasn't moved enough in your favour."
                    ),
                    tool_calls=[],
                    structured={"kind": "manage", "error": "no_improvement"},
                    route=route,
                )
            new_tp = current_tp
        elif side_upper == "SELL":
            new_sl = current_price + trail_atr * atr
            new_sl = max(new_sl, current_price + 0.01)
            if current_sl is not None and new_sl >= current_sl:
                return DeskResponse(
                    narrative=(
                        f"Trailing stop would not improve the current SL "
                        f"({current_sl:.2f}). Price hasn't moved enough in your favour."
                    ),
                    tool_calls=[],
                    structured={"kind": "manage", "error": "no_improvement"},
                    route=route,
                )
            new_tp = current_tp
        else:
            return DeskResponse(
                narrative=f"Unknown side {side} for trailing.",
                tool_calls=[],
                structured={"kind": "manage", "error": "unknown_side"},
                route=route,
            )

        try:
            result = self.rt.gateway.modify(ticket, new_sl, new_tp)
        except Exception as exc:  # noqa: BLE001
            return DeskResponse(
                narrative=f"Trail failed for ticket {ticket}: {exc}.",
                tool_calls=[],
                structured={"kind": "manage", "error": str(exc)},
                route=route,
            )
        if result.ok:
            narrative = f"Trailed {ticket} stop to {new_sl:.2f} ({trail_atr} ATR behind)."
        else:
            narrative = f"Trail rejected for {ticket}: {result.detail}."
        return DeskResponse(
            narrative=narrative,
            tool_calls=[
                {
                    "name": "execution.modify_position",
                    "arguments": {"ticket": ticket, "sl": new_sl, "tp": new_tp},
                    "result": {
                        "ok": result.ok,
                        "code": result.code,
                        "detail": result.detail,
                    },
                }
            ],
            structured={
                "kind": "manage",
                "action": "trail",
                "ticket": ticket,
                "new_sl": new_sl,
                "atr": atr,
                "ok": result.ok,
            },
            route=route,
        )

    def _get_atr(self, symbol: str) -> float | None:
        """Get ATR from the latest analysis for the symbol."""
        try:
            row = self.rt.store.latest_analysis(symbol, "M15")
            if row:
                features = row.get("features")
                if not isinstance(features, dict):
                    features = json.loads(row.get("features_json") or "{}")
                atr = features.get("atr")
                return float(atr) if atr is not None else None
        except Exception:  # noqa: BLE001
            pass
        return None

    def _handle_manage_scale_out(
        self, route: DeskRoute, ticket: str, symbol: str, side: str, target: dict[str, Any]
    ) -> DeskResponse:
        """Scale out (partial close) - MT5 MCP close tool doesn't support partial volume,
        so we close the full position. This is a known limitation."""
        volume = target.get("lots") or 0.0
        try:
            result = self.rt.gateway.close(ticket, "CHAT_SCALE_OUT")
        except Exception as exc:  # noqa: BLE001
            return DeskResponse(
                narrative=f"Scale out failed for ticket {ticket}: {exc}.",
                tool_calls=[],
                structured={"kind": "manage", "error": str(exc)},
                route=route,
            )
        if result.ok:
            narrative = (
                f"Closed {symbol} position {ticket} ({volume:g} lots). "
                "Note: MT5 partial close isn't supported via MCP, so the full position was closed."
            )
        else:
            narrative = f"Scale out rejected for {ticket}: {result.detail}."
        return DeskResponse(
            narrative=narrative,
            tool_calls=[
                {
                    "name": "execution.close_position",
                    "arguments": {"ticket": ticket},
                    "result": {
                        "ok": result.ok,
                        "code": result.code,
                        "detail": result.detail,
                    },
                }
            ],
            structured={
                "kind": "manage",
                "action": "scale_out",
                "ticket": ticket,
                "volume": volume,
                "ok": result.ok,
            },
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
