"""Skill: daily_brief — pre-session market overview."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.ignite.agent.contracts import SkillSpec
from backend.ignite.agent.context import build_analysis_context


SYSTEM = """You are the desk analyst on Ignite Desk. Write a pre-session brief for the operator.

A deterministic engine has produced the overnight analyses and the calendar. Your job is to synthesise them into a concise brief.

Rules:
- Use only numbers from CONTEXT or the desk notes.
- Cover: overnight session summary, key levels, calendar events, bias.
- Write 3-6 sentences, plain prose. No headings, bullets, emojis, or promises.
- Never say you executed, will execute, or recommend that the reader buy or sell.
- Speak as the desk: "the model", "the rule", "the calendar"."""

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
    analyses = rt.store.knowledge_cards(scope="market_analyst", status="reviewed")

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
        allowed_numbers=set(),
        notes="Overnight analyses for all timeframes plus today's calendar.",
    )


def template_narrative(pack: Any) -> str:
    tf = pack.payload.get("timeframes", [])
    cal = pack.payload.get("calendar", [])
    parts = []
    for a in tf:
        parts.append(f"{a['timeframe']} {a['signal'].upper()} p_up {a['p_up']:.2f} edge {a['edge_atr']:.2f} ATR")
    cal_high = [c for c in cal if c.get("impact") == "high"]
    cal_str = f", {len(cal_high)} high-impact events" if cal_high else ""
    return f"Overnight: {'; '.join(parts)}.{cal_str}. Model consensus will guide session bias."