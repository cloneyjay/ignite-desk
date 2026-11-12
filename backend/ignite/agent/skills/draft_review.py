"""Skill: draft_review — sanity-check a draft before execution."""

from __future__ import annotations

from typing import Any

from backend.ignite.agent.contracts import SkillSpec
from backend.ignite.agent.context import ContextPack


SYSTEM = """You are the risk manager on Ignite Desk. Review the draft order before execution.

A deterministic engine produced the draft. Your job is to confirm it passes every guard.

Rules:
- Use only numbers from CONTEXT or the desk notes.
- Check: drift guard, blackout, spread cap, risk cap, one-position rule, stop placement.
- Write 2-3 sentences, plain prose. No headings, bullets, emojis, or promises.
- Never say you executed, will execute, or recommend that the reader buy or sell.
- Speak as the desk: "the draft", "the rule", "the guard"."""

SPEC = SkillSpec(
    id="draft_review",
    title="Draft pre-execution review",
    when="The operator requests a draft review before confirming.",
    scopes=("risk_manager",),
    card_limits=(("risk_manager", 4),),
    max_words=120,
    temperature=0.1,
    max_tokens=240,
    system=SYSTEM,
    user_suffix="Review the draft now.",
)


def build_context(rt: Any, subject: str) -> ContextPack:
    from backend.ignite.agent.context import ContextPack

    row = rt.store.get_analysis(subject)
    if not row:
        raise ValueError(f"no analysis {subject}")

    draft = rt.store.draft_for_analysis(subject)
    if not draft:
        raise ValueError(f"no draft for analysis {subject}")

    # Re-evaluate all guards
    evaluation = rt.store.get_draft(draft["id"])  # has checks
    checks = evaluation.get("checks", []) if evaluation else []

    payload = {
        "analysis_id": subject,
        "draft": draft,
        "checks": checks,
        "desk": {
            "risk_version": "risk.v1",
            "risk_pct": rt.risk_config().risk_pct,
            "max_drift_atr": rt.settings.max_drift_atr,
            "max_spread_points": rt.risk_config().max_spread_points,
        },
    }

    from backend.ignite.knowledge.facts import desk_facts
    facts = desk_facts(rt.settings, rt.risk_config())

    return ContextPack(
        skill="draft_review",
        subject=subject,
        payload=payload,
        facts=facts,
        allowed_numbers=set(),
        notes="Full guard evaluation for this draft.",
    )


def template_narrative(pack: ContextPack) -> str:
    draft = pack.payload.get("draft", {})
    checks = pack.payload.get("checks", [])
    failures = [c for c in checks if not c.get("ok")]
    if failures:
        return f"Draft BLOCKED: {', '.join(c['code'] for c in failures)}. Do not execute."
    return "Draft passes all guards: drift ok, spread ok, risk within cap, no blackout, no conflicting position. Clear to execute."