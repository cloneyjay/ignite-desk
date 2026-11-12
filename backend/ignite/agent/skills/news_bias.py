"""Skill: news_bias — pre-session bias note from calendar + news + forecast."""

from __future__ import annotations

from typing import Any

from backend.ignite.agent.contracts import SkillSpec
from backend.ignite.agent.context import ContextPack


SYSTEM = """You are the desk analyst on Ignite Desk. Write a news bias note for the current session.

A deterministic engine has produced the forecast and the calendar. Your job is to explain how fundamentals may colour the session.

Rules:
- Use only numbers from CONTEXT or the desk notes.
- Reference: high-impact calendar events, news headlines, forecast direction.
- Write 2-4 sentences, plain prose. No headings, bullets, emojis, or promises.
- Never say you executed, will execute, or recommend that the reader buy or sell.
- Speak as the desk: "the calendar", "the model", "the news"."""

SPEC = SkillSpec(
    id="news_bias",
    title="News bias note",
    when="The operator requests a bias note before or during a session.",
    scopes=("fundamentals_desk", "market_analyst"),
    card_limits=(("fundamentals_desk", 3), ("market_analyst", 2)),
    max_words=140,
    temperature=0.2,
    max_tokens=320,
    system=SYSTEM,
    user_suffix="Write the news bias note now.",
)


def build_context(rt: Any, subject: str) -> ContextPack:
    from datetime import datetime, timezone, timedelta
    from backend.ignite.agent.context import ContextPack
    from backend.ignite.knowledge.facts import desk_facts

    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)

    calendar = rt.news.calendar(start, end)
    news = rt.news.news(start, end, limit=20)

    # Get latest analysis
    row = rt.store.latest_analysis("XAUUSD", "M15")
    analysis = {}
    if row:
        analysis = {
            "signal": row["signal"],
            "p_up": row["p_up"],
            "edge_atr": row["edge_atr"],
        }

    payload = {
        "date": start.date().isoformat(),
        "calendar": calendar,
        "news": news[:10],
        "analysis": analysis,
        "desk": {
            "risk_version": "risk.v1",
            "risk_pct": rt.risk_config().risk_pct,
            "max_drift_atr": rt.settings.max_drift_atr,
        },
    }

    facts = desk_facts(rt.settings, rt.risk_config())
    return ContextPack(
        skill="news_bias",
        subject=subject,
        payload=payload,
        facts=facts,
        allowed_numbers=set(),
        notes="Calendar events, recent news, and current forecast for bias assessment.",
    )


def template_narrative(pack: ContextPack) -> str:
    cal = pack.payload.get("calendar", [])
    high = [c for c in cal if c.get("impact") == "high"]
    news = pack.payload.get("news", [])
    ana = pack.payload.get("analysis", {})
    parts = []
    if high:
        parts.append(f"{len(high)} high-impact events today ({', '.join(c['currency'] for c in high)})")
    if news:
        parts.append(f"{len(news)} news items overnight")
    if ana:
        parts.append(f"model {ana.get('signal', 'none')} p_up {ana.get('p_up', 0):.2f}")
    if not parts:
        return "No significant calendar events or news. Session bias neutral."
    return f"{'; '.join(parts)}. Fundamentals may colour the session around event times."