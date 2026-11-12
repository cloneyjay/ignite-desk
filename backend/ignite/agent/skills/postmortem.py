"""Skill: postmortem — analyse a closed trade."""

from __future__ import annotations

from typing import Any

from backend.ignite.agent.contracts import SkillSpec
from backend.ignite.agent.context import ContextPack


SYSTEM = """You are the desk analyst on Ignite Desk. Write a postmortem for a closed trade.

A deterministic engine produced the original analysis and draft. Your job is to explain what happened.

Rules:
- Use only numbers from CONTEXT or the desk notes.
- Compare: forecast vs realised, draft vs fill, hold time vs horizon.
- Write 3-5 sentences, plain prose. No headings, bullets, emojis, or promises.
- Never say you executed, will execute, or recommend that the reader buy or sell.
- Speak as the desk: "the model", "the draft", "the fill"."""

SPEC = SkillSpec(
    id="postmortem",
    title="Trade postmortem",
    when="The operator requests a postmortem for a closed trade.",
    scopes=("risk_manager", "market_analyst", "fundamentals_desk"),
    card_limits=(("risk_manager", 2), ("market_analyst", 2), ("fundamentals_desk", 1)),
    max_words=180,
    temperature=0.15,
    max_tokens=360,
    system=SYSTEM,
    user_suffix="Write the postmortem now.",
)


def build_context(rt: Any, subject: str) -> ContextPack:
    from backend.ignite.agent.context import ContextPack
    from backend.ignite.knowledge.facts import desk_facts

    # subject is the trade ticket or order ID
    order = next((o for o in rt.store.recent_orders(200) if o["ticket"] == subject), None)
    if not order:
        raise ValueError(f"no order with ticket {subject}")

    draft_id = order["draft_id"]
    draft = rt.store.get_draft(draft_id) if draft_id else None
    analysis_id = draft["analysis_id"] if draft else None
    analysis = rt.store.get_analysis(analysis_id) if analysis_id else None

    payload = {
        "order": order,
        "draft": draft,
        "analysis": analysis,
        "desk": {
            "risk_version": "risk.v1",
            "risk_pct": rt.risk_config().risk_pct,
            "max_drift_atr": rt.settings.max_drift_atr,
        },
    }

    facts = desk_facts(rt.settings, rt.risk_config())
    return ContextPack(
        skill="postmortem",
        subject=subject,
        payload=payload,
        facts=facts,
        allowed_numbers=set(),
        notes="Full trade lifecycle: analysis → draft → fill → exit.",
    )


def template_narrative(pack: ContextPack) -> str:
    order = pack.payload.get("order", {})
    draft = pack.payload.get("draft", {})
    ana = pack.payload.get("analysis", {})

    side = order.get("side", "?")
    net = order.get("net", 0)
    r_mult = order.get("r_multiple", 0)
    hold = order.get("duration_s", 0) / 3600 if order.get("duration_s") else 0

    parts = [f"{side.upper()} {net:+.2f} USD ({r_mult:+.2f}R) held {hold:.1f}h."]
    if ana:
        parts.append(f"Model was {ana.get('signal', 'none')} p_up {ana.get('p_up', 0):.2f} edge {ana.get('edge_atr', 0):.2f} ATR.")
    if draft:
        parts.append(f"Draft SL {draft.get('sl', 0):.2f} TP {draft.get('tp', 0):.2f} vs fill {order.get('filled_price', 0):.2f}.")
    return " ".join(parts)