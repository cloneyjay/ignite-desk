"""Skill: daily_brief — pre-session market overview."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.ignite.agent.contracts import SkillSpec
from backend.ignite.agent.context import build_analysis_context
from backend.ignite.agent.validators import collect_numbers


SYSTEM = """You are Aegus, the operator's personal trading companion. Give a warm, human
daily brief as if you are sitting beside the trader before the session starts.

The CONTEXT contains authoritative overnight reads and calendar data. Turn it into useful
plain English, not a technical report. Say what the market feels like, whether the
timeframes agree or are pulling in different directions, what deserves attention, and
which events could make the session jumpy.

Style:
- Start naturally, for example: "Here is the desk picture for today."
- Use short, conversational sentences and everyday words.
- Translate p_up into "the model's chance of prices finishing higher" and edge_atr into
  "the size of the expected move compared with a normal bar range".
- Do not say "p_up", "edge ATR", "risk.v1", "signal.v1", "consensus will guide bias",
  or other internal labels unless the operator asks for technical detail.
- If timeframes disagree, say that clearly. If there is no trade signal, say the desk is
  waiting rather than making it sound like a failure.
- Mention high-impact events by name and currency when available.
- Write 3-6 sentences, plain prose, with no headings, bullets, emojis, or promises.
- Never claim an order was sent or recommend a trade. The execution engine decides that."""

SPEC = SkillSpec(
    id="daily_brief",
    title="Daily pre-session brief",
    when="The operator requests the daily brief at session start.",
    scopes=("market_analyst", "fundamentals_desk"),
    card_limits=(("market_analyst", 4), ("fundamentals_desk", 2)),
    max_words=200,
    temperature=0.15,
    max_tokens=400,
    system=SYSTEM,
    user_suffix="Write the daily brief now.",
)


def build_context(rt: Any, subject: str) -> Any:
    """Build context from latest analyses across timeframes + calendar."""
    from backend.ignite.store.db import utc_now
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    session_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # Get latest analyses for each timeframe
    timeframes = ["M5", "M15", "M30", "H1"]
    analysis_summaries = []
    for tf in timeframes:
        row = rt.store.latest_analysis("XAUUSD", tf)
        if row:
            analysis_summaries.append({
                "timeframe": tf,
                "signal": row["signal"],
                "p_up": row["p_up"],
                "edge_atr": row["edge_atr"],
                "last_bar_time": row["last_bar_time"],
            })

    # Get calendar for today
    calendar = rt.news.calendar(session_start, session_start + timedelta(days=1))

    payload = {
        "date": session_start.date().isoformat(),
        "timeframes": analysis_summaries,
        "calendar": calendar,
        "desk": {
            "risk_version": "risk.v1",
            "risk_pct": rt.risk_config().risk_pct,
            "max_drift_atr": rt.settings.max_drift_atr,
        },
    }

    from backend.ignite.agent.context import ContextPack
    return ContextPack(
        skill="daily_brief",
        subject=subject,
        payload=payload,
        facts={},
        allowed_numbers=collect_numbers(payload),
        notes="Overnight analyses for all timeframes plus today's calendar.",
    )


def template_narrative(pack: Any) -> str:
    tf = pack.payload.get("timeframes", [])
    cal = pack.payload.get("calendar", [])
    parts = []
    for a in tf:
        signal = str(a["signal"]).lower()
        direction = (
            "leaning higher" if signal == "long"
            else "leaning lower" if signal == "short"
            else "without a clear edge"
        )
        parts.append(
            f"The {a['timeframe']} picture is {direction}"
        )
    cal_high = [c for c in cal if c.get("impact") == "high"]
    if not parts:
        market = "I do not have a fresh timeframe read yet, so I would rather wait for the next analysis than guess."
    else:
        market = " ".join(parts[:4])
    if cal_high:
        events = ", ".join(
            f"{event.get('name', 'an event')} ({event.get('currency', 'unknown currency')})"
            for event in cal_high[:3]
        )
        calendar = f"Keep an eye on {events}; those releases can make price move quickly."
    else:
        calendar = "There are no high-impact calendar releases in the current brief."
    return f"Here is the desk picture for today. {market} {calendar}"