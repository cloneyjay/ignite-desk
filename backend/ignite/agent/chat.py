"""Chat router: pure function, no model choice.

Routes natural-language requests to skills. The model never decides which
task to run; the router is a deterministic function over the request text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from backend.ignite.agent.registry import SkillSpec, get_skill, UnknownSkill


@dataclass(frozen=True)
class ChatRoute:
    skill: str
    args: dict[str, Any]
    confidence: float
    needs_analysis: bool = False  # whether to start analysis first
    wants_execution: bool = False


INTENT_PATTERNS = [
    # live position questions must win before the generic "open trade" pattern
    (re.compile(r"\b(?:what(?:'s| is)|show|list|read|check)\s+(?:my\s+)?(?:the\s+)?(?:current\s+)?open\s+(?:trades?|positions?)\s*(?:in|on)?\s*(?:MT5|the terminal|the desk)?\b", re.I),
     lambda m: ("positions", {}, 0.96, False)),
    (re.compile(r"\b(?:what trades?|which trades?)\s+(?:are|do i have)\s+open\b", re.I),
     lambda m: ("positions", {}, 0.96, False)),
    # explicit trade instruction - analysis and all execution guards are still mandatory
    (re.compile(r"\b(?:buy|sell|open|place|enter|take)\s+(?:a\s+)?(?:trade|position|order)?\s*(?:on|in)?\s*((?!TTRADE\b)[A-Z]{6,7})(?:\s+(M5|M15|M30|H1))?\b", re.I),
     lambda m: ("analysis_narrative", {"symbol": m.group(1).upper(), "timeframe": (m.group(2) or "M15").upper()}, 0.96, True, True)),
    (re.compile(r"\b(long|short)\s+((?!TTRADE\b)[A-Z]{6,7})(?:\s+(M5|M15|M30|H1))?\b", re.I),
     lambda m: ("analysis_narrative", {"symbol": m.group(2).upper(), "timeframe": (m.group(3) or "M15").upper(), "side": m.group(1).lower()}, 0.94, True, True)),
    (re.compile(r"\b(?:place|make|open|take)\s+(?:a\s+)?(long|short)\s+(?:t+rade|order|position)\b", re.I),
     lambda m: ("trade_clarification", {"side": m.group(1).lower()}, 0.98, False)),
    # incomplete trade instruction - ask for the missing instrument/details
    (re.compile(r"\b(?:place|make|open|take)\s+(?:a\s+)?(?:t+rade|order|position)\b(?!\s+(?:on|in)?\s*[A-Z]{6,7}\b)", re.I),
     lambda m: ("trade_clarification", {}, 0.98, False)),
    # analyse XAUUSD M15 - triggers analysis + narrative
    (re.compile(r"\b(?:analyse|analyze|run)\s+([A-Z]{6,7})\s+(M5|M15|M30|H1)\b", re.I),
     lambda m: ("analysis_narrative", {"symbol": m.group(1).upper(), "timeframe": m.group(2).upper()}, 0.95, True)),
    # analyse XAUUSD - triggers analysis + narrative
    (re.compile(r"\b(?:analyse|analyze|run)\s+([A-Z]{6,7})\b", re.I),
     lambda m: ("analysis_narrative", {"symbol": m.group(1).upper()}, 0.85, True)),
    # live market structure / technical read
    (re.compile(r"\b(?:pull|get|read|show|check)\s+(?:the\s+)?(?:current\s+)?(?:market\s+)?(?:structure|technical analysis|technicals)\s*(?:of|for|on)?\s*([A-Z]{6,7})(?:\s+(?:on|at))?\s*(M5|M15|M30|H1)?\b", re.I),
     lambda m: ("market_structure", {"symbol": m.group(1).upper(), "timeframe": (m.group(2) or "M15").upper()}, 0.98, False)),
    (re.compile(r"\b(?:technical analysis|market structure)\s+([A-Z]{6,7})(?:\s+(?:on|at))?\s*(M5|M15|M30|H1)?\b", re.I),
     lambda m: ("market_structure", {"symbol": m.group(1).upper(), "timeframe": (m.group(2) or "M15").upper()}, 0.98, False)),
    # add EURUSD to watchlist
    (re.compile(r"\badd\s+([A-Z]{6,7})\s+(?:to\s+)?(?:watchlist|watch)\b", re.I),
     lambda m: ("add_symbol", {"symbol": m.group(1).upper()}, 0.95, False)),
    # remove EURUSD from watchlist
    (re.compile(r"\bremove\s+([A-Z]{6,7})\s+(?:from\s+)?(?:watchlist|watch)\b", re.I),
     lambda m: ("remove_symbol", {"symbol": m.group(1).upper()}, 0.95, False)),
    # what's my risk / risk state
    (re.compile(r"\b(?:what'?s|what\s+is|show)\s+(?:my\s+)?(?:current\s+)?risk\b", re.I),
     lambda m: ("risk_state", {}, 0.9, False)),
    (re.compile(r"\b(?:can you tell me|tell me|how much|am i)\b.*\b(?:current|open|account|portfolio)?\s*risk\b", re.I),
     lambda m: ("risk_state", {}, 0.88, False)),
    # show positions / open positions
    (re.compile(r"\b(?:show|list)\s+(?:my\s+)?(?:open\s+)?positions?\b", re.I),
     lambda m: ("positions", {}, 0.9, False)),
    (re.compile(r"\b(?:what(?:'s| is)|show|list|read|check)\s+(?:my\s+)?(?:the\s+)?(?:current\s+)?open\s+(?:trades?|positions?)\s*(?:in|on)?\s*(?:MT5|the terminal|the desk)?\b", re.I),
     lambda m: ("positions", {}, 0.96, False)),
    (re.compile(r"\b(?:what trades?|which trades?)\s+(?:are|do i have)\s+open\b", re.I),
     lambda m: ("positions", {}, 0.96, False)),
    # show account / account summary
    (re.compile(r"\b(?:show|what'?s)\s+(?:my\s+)?account\b", re.I),
     lambda m: ("account_snapshot", {}, 0.9, False)),
    # desk status / what the autonomous agent is doing
    (re.compile(r"\b(?:what are you doing|what are you watching|are you running|desk status)\b", re.I),
     lambda m: ("desk_status", {}, 0.95, False)),
    # show history / trade history
    (re.compile(r"\b(?:show|list)\s+(?:my\s+)?(?:trade\s+)?history\b", re.I),
     lambda m: ("trade_history", {}, 0.9, False)),
    # show calendar / economic calendar
    (re.compile(r"\b(?:show|list)\s+(?:economic\s+)?calendar\b", re.I),
     lambda m: ("calendar", {}, 0.9, False)),
    # show news
    (re.compile(r"\b(?:show|list)\s+news\b", re.I),
     lambda m: ("news", {}, 0.9, False)),
    # autonomous desk controls
    (re.compile(r"\b(?:turn|switch|set)\s+(autonomous|auto)\s+(on|off|enabled|disabled)\b", re.I),
     lambda m: ("autonomous_toggle", {"enabled": m.group(2).lower() in {"on", "enabled"}}, 0.98, False)),
    (re.compile(r"\b(?:enable|start)\s+(?:autonomous|auto)\s+(?:trading|mode)?\b", re.I),
     lambda m: ("autonomous_toggle", {"enabled": True}, 0.98, False)),
    (re.compile(r"\b(?:disable|stop)\s+(?:autonomous|auto)\s+(?:trading|mode)?\b", re.I),
     lambda m: ("autonomous_toggle", {"enabled": False}, 0.98, False)),
    # explicit position management
    (re.compile(r"\b(?:close|exit|flatten)\s+(?:position|trade)?\s*(\d{5,})\b", re.I),
     lambda m: ("close_position", {"ticket": m.group(1)}, 0.98, False)),
    (re.compile(r"\b(?:close|exit|flatten)\s+(?:my\s+)?(?:position|trade)\s+(?:on|in)\s+([A-Z]{6,7})\b", re.I),
     lambda m: ("close_position", {"symbol": m.group(1).upper()}, 0.95, False)),
    # daily brief
    (re.compile(r"\b(?:daily\s+)?brief\b", re.I),
     lambda m: ("daily_brief", {}, 0.9, False)),
    # postmortem
    (re.compile(r"\bpostmortem\b", re.I),
     lambda m: ("postmortem", {}, 0.9, False)),
    # news bias
    (re.compile(r"\bnews\s+bias\b", re.I),
     lambda m: ("news_bias", {}, 0.9, False)),
    # draft review
    (re.compile(r"\b(?:review|check)\s+draft\b", re.I),
     lambda m: ("draft_review", {}, 0.9, False)),
]

# Skills that can change the desk or the account. A question or a negation in
# the request must never be read as an instruction to act.
TRADE_GUARDED_SKILLS = {"trade_clarification", "close_position"}

_QUESTION_LEAD = re.compile(
    r"^(?:should|can|could|would|will|do|does|did|is|are|was|were|what|how|why|when|where|which)\b",
    re.I,
)
_NEGATION = re.compile(r"\b(?:don'?t|do not|doesn'?t|does not|not|never|no)\b", re.I)
_TRADE_VERBS = {
    "buy",
    "sell",
    "open",
    "place",
    "enter",
    "take",
    "close",
    "exit",
    "flatten",
    "long",
    "short",
}


def _is_question_or_negative(text: str) -> bool:
    """True when a trade-shaped phrase is a question or a negation, not an order."""
    stripped = text.strip()
    if stripped.endswith("?"):
        return True
    if _QUESTION_LEAD.match(stripped):
        return True
    tokens = re.findall(r"[a-z']+", stripped.lower())
    for index, token in enumerate(tokens):
        if token in _TRADE_VERBS:
            window = tokens[max(0, index - 2) : index]
            if any(_NEGATION.fullmatch(word) for word in window):
                return True
    return False


DIRECT_READ_SKILLS = {
    "risk_state",
    "positions",
    "account_snapshot",
    "desk_status",
    "trade_clarification",
    "autonomous_toggle",
    "close_position",
    "add_symbol",
    "remove_symbol",
    "calendar",
    "news",
    "trade_history",
    "daily_brief",
    "news_bias",
    "draft_review",
    "postmortem",
    "market_structure",
}


def route_chat(text: str) -> ChatRoute | None:
    """Deterministic routing. Returns None if no pattern matches."""
    text = text.strip()
    for pattern, builder in INTENT_PATTERNS:
        match = pattern.search(text)
        if match:
            result = builder(match)
            skill_id, args, confidence, needs_analysis = result[:4]
            wants_execution = bool(result[4]) if len(result) > 4 else False
            if (wants_execution or skill_id in TRADE_GUARDED_SKILLS) and (
                _is_question_or_negative(text)
            ):
                continue
            try:
                get_skill(skill_id)
                return ChatRoute(
                    skill=skill_id,
                    args=args,
                    confidence=confidence,
                    needs_analysis=needs_analysis,
                    wants_execution=wants_execution,
                )
            except UnknownSkill:
                if skill_id in DIRECT_READ_SKILLS:
                    return ChatRoute(skill=skill_id, args=args, confidence=confidence, needs_analysis=False)
                continue
    return None


def route_or_error(text: str) -> ChatRoute:
    route = route_chat(text)
    if route is None:
        raise ValueError(
            f"Could not route request: {text!r}. Try: 'analyse XAUUSD M15', "
            "'add EURUSD to watchlist', 'what is my risk', 'daily brief'."
        )
    return route