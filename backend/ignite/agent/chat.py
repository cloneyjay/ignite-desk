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


INTENT_PATTERNS = [
    # analyse XAUUSD M15
    (re.compile(r"\b(?:analyse|analyze|run)\s+([A-Z]{6,7})\s+(M5|M15|M30|H1)\b", re.I),
     lambda m: ("analysis_narrative", {"symbol": m.group(1).upper(), "timeframe": m.group(2).upper()}, 0.95)),
    # analyse XAUUSD
    (re.compile(r"\b(?:analyse|analyze|run)\s+([A-Z]{6,7})\b", re.I),
     lambda m: ("analysis_narrative", {"symbol": m.group(1).upper()}, 0.85)),
    # add EURUSD to watchlist
    (re.compile(r"\badd\s+([A-Z]{6,7})\s+(?:to\s+)?(?:watchlist|watch)\b", re.I),
     lambda m: ("add_symbol", {"symbol": m.group(1).upper()}, 0.95)),
    # remove EURUSD from watchlist
    (re.compile(r"\bremove\s+([A-Z]{6,7})\s+(?:from\s+)?(?:watchlist|watch)\b", re.I),
     lambda m: ("remove_symbol", {"symbol": m.group(1).upper()}, 0.95)),
    # what's my risk / risk state
    (re.compile(r"\b(?:what'?s|show)\s+(?:my\s+)?risk\b", re.I),
     lambda m: ("risk_state", {}, 0.9)),
    # show positions / open positions
    (re.compile(r"\b(?:show|list)\s+(?:my\s+)?(?:open\s+)?positions?\b", re.I),
     lambda m: ("positions", {}, 0.9)),
    # show account / account summary
    (re.compile(r"\b(?:show|what'?s)\s+(?:my\s+)?account\b", re.I),
     lambda m: ("account_snapshot", {}, 0.9)),
    # show history / trade history
    (re.compile(r"\b(?:show|list)\s+(?:my\s+)?(?:trade\s+)?history\b", re.I),
     lambda m: ("trade_history", {}, 0.9)),
    # show calendar / economic calendar
    (re.compile(r"\b(?:show|list)\s+(?:economic\s+)?calendar\b", re.I),
     lambda m: ("calendar", {}, 0.9)),
    # show news
    (re.compile(r"\b(?:show|list)\s+news\b", re.I),
     lambda m: ("news", {}, 0.9)),
    # daily brief
    (re.compile(r"\b(?:daily\s+)?brief\b", re.I),
     lambda m: ("daily_brief", {}, 0.9)),
    # postmortem
    (re.compile(r"\bpostmortem\b", re.I),
     lambda m: ("postmortem", {}, 0.9)),
    # news bias
    (re.compile(r"\bnews\s+bias\b", re.I),
     lambda m: ("news_bias", {}, 0.9)),
    # draft review
    (re.compile(r"\b(?:review|check)\s+draft\b", re.I),
     lambda m: ("draft_review", {}, 0.9)),
]


def route_chat(text: str) -> ChatRoute | None:
    """Deterministic routing. Returns None if no pattern matches."""
    text = text.strip()
    for pattern, builder in INTENT_PATTERNS:
        match = pattern.search(text)
        if match:
            skill_id, args, confidence = builder(match)
            try:
                get_skill(skill_id)
                return ChatRoute(skill=skill_id, args=args, confidence=confidence)
            except UnknownSkill:
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