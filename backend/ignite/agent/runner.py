"""Skill runner: select cards, call the model, validate, fall back, record.

The runner is the only place that talks to an LLM on behalf of the desk. It has
no execution tool and no write path into an analysis or a draft. A run is
recorded even when the template answered, so the UI can say who wrote the text.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from backend.ignite.agent.context import ContextError, ContextPack
from backend.ignite.agent.registry import SkillSpec, get_skill
from backend.ignite.agent.skills import (
    analysis_narrative,
    daily_brief,
    draft_review,
    news_bias,
    postmortem,
)
from backend.ignite.agent.validators import collect_numbers, validate_text
from backend.ignite.knowledge.card import RenderError, render_card
from backend.ignite.store.db import utc_now

BUILDERS: dict[str, Callable[[Any, str], ContextPack]] = {
    analysis_narrative.SPEC.id: analysis_narrative.build_context,
    daily_brief.SPEC.id: daily_brief.build_context,
    draft_review.SPEC.id: draft_review.build_context,
    news_bias.SPEC.id: news_bias.build_context,
    postmortem.SPEC.id: postmortem.build_context,
}

TEMPLATES: dict[str, Callable[[ContextPack], str]] = {
    analysis_narrative.SPEC.id: analysis_narrative.template_narrative,
    daily_brief.SPEC.id: daily_brief.template_narrative,
    draft_review.SPEC.id: draft_review.template_narrative,
    news_bias.SPEC.id: news_bias.template_narrative,
    postmortem.SPEC.id: postmortem.template_narrative,
}


class AgentError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentOutput:
    run_id: str
    skill: str
    subject: str | None
    narrative: str
    provider: str
    model: str | None
    status: str
    fallback: bool
    created_at: str
    latency_ms: int | None
    cards: list[dict[str, Any]]
    checks: dict[str, Any]
    error: str | None = None

    @classmethod
    def from_run(cls, run: dict[str, Any]) -> "AgentOutput":
        return cls(
            run_id=run["id"],
            skill=run["skill"],
            subject=run.get("subject"),
            narrative=run.get("narrative") or "",
            provider=run["provider"],
            model=run.get("model"),
            status=run["status"],
            fallback=bool(run.get("fallback")),
            created_at=run["created_at"],
            latency_ms=run.get("latency_ms"),
            cards=run.get("cards") or [],
            checks=run.get("checks") or {},
            error=run.get("error"),
        )

    def payload(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "skill": self.skill,
            "subject": self.subject,
            "analysis_id": self.subject if self.skill == "analysis_narrative" else None,
            "narrative": self.narrative,
            "provider": self.provider,
            "model": self.model,
            "status": self.status,
            "fallback": self.fallback,
            "created_at": self.created_at,
            "latency_ms": self.latency_ms,
            "cards": self.cards,
            "checks": self.checks,
            "error": self.error,
        }


def select_cards(store: Any, spec: SkillSpec) -> list[dict[str, Any]]:
    """Deterministic: reviewed cards, scope budget, priority then id."""
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for scope, limit in spec.card_limits:
        cards = store.knowledge_cards(scope=scope, status="reviewed", skill=spec.id)
        for card in cards[:limit]:
            if card["id"] in seen:
                continue
            seen.add(card["id"])
            selected.append(card)
    return selected


def _render_cards(cards: list[dict[str, Any]], facts: dict[str, str]) -> str:
    blocks = []
    for card in cards:
        body = render_card(card, facts)
        blocks.append(f"### {card['title']} (`{card['id']}` v{card['version']})\n\n{body}")
    return "\n\n".join(blocks)


def _messages(pack: ContextPack, spec: SkillSpec, notes: str) -> list[dict[str, str]]:
    system = spec.system
    if notes:
        system = f"{system}\n\n# Desk notes\n\n{notes}"
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": (
                "CONTEXT (authoritative JSON):\n"
                f"{json.dumps(pack.payload, indent=2, ensure_ascii=False, default=str)}\n\n"
                f"{spec.user_suffix}"
            ),
        },
    ]


def _correction(checks: dict[str, Any]) -> str:
    problems = list(checks.get("violations") or []) + list(checks.get("style_issues") or [])
    joined = "; ".join(
        item.get("token", "") if isinstance(item, dict) else str(item)
        for item in problems[:6]
    )
    return (
        "Your previous draft failed validation: "
        f"{joined}. Output ONLY the corrected 2-4 sentence commentary. "
        "No reasoning, no planning, no meta-commentary. "
        "Use only numbers that appear verbatim in CONTEXT or the desk notes. "
        "Do not add a number that is not there."
    )


def run_skill(
    rt: Any, skill_id: str, subject: str, *, refresh: bool = False
) -> AgentOutput:
    try:
        spec = get_skill(skill_id)
    except KeyError as exc:
        raise AgentError(str(exc)) from exc

    builder = BUILDERS.get(skill_id)
    template = TEMPLATES.get(skill_id)
    if builder is None or template is None:
        raise AgentError(f"skill {skill_id!r} has no context builder")

    if not refresh:
        cached = rt.store.latest_agent_run(skill_id, subject)
        if cached and cached.get("narrative"):
            return AgentOutput.from_run(cached)

    try:
        pack = builder(rt, subject)
    except ContextError as exc:
        raise AgentError(str(exc)) from exc

    cards = select_cards(rt.store, spec)
    cards_meta = [
        {
            "id": card["id"],
            "title": card["title"],
            "version": card["version"],
            "scope": card["scope"],
        }
        for card in cards
    ]

    started = time.monotonic()
    provider_errors: list[str] = []
    rejected_text: str | None = None
    result = None
    checks: dict[str, Any] = {}
    allowed: set[float] = set(pack.allowed_numbers) | collect_numbers(pack.facts.values())

    try:
        notes = _render_cards(cards, pack.facts)
        allowed |= collect_numbers(notes)
        messages = _messages(pack, spec, notes)

        for attempt in (1, 2):
            try:
                result = rt.llm.complete(
                    messages,
                    max_tokens=spec.max_tokens,
                    temperature=spec.temperature,
                    timeout_s=rt.settings.agent_timeout_s,
                )
            except Exception as exc:  # noqa: BLE001 - a provider failure must fall back
                provider_errors.append(str(exc))
                attempts = getattr(exc, "attempts", None)
                if attempts:
                    provider_errors.extend(str(item) for item in attempts)
                result = None
                break

            checks = validate_text(result.text, allowed, spec.max_words)
            checks["attempt"] = attempt
            if checks["ok"]:
                break
            rejected_text = result.text
            if attempt == 1:
                messages = messages + [
                    {"role": "assistant", "content": result.text},
                    {"role": "user", "content": _correction(checks)},
                ]
                result = None
    except RenderError as exc:
        provider_errors.append(f"card render failed: {exc}")
        result = None

    elapsed = int((time.monotonic() - started) * 1000)
    created_at = utc_now()

    if result is not None and checks.get("ok"):
        narrative = result.text
        provider = result.provider
        model = result.model
        latency_ms = result.latency_ms
        status = "ok"
        fallback = False
        error = None
        prompt_tokens = result.prompt_tokens
        completion_tokens = result.completion_tokens
    else:
        narrative = template(pack)
        provider = "template"
        model = None
        latency_ms = elapsed
        status = "fallback"
        fallback = True
        error = "; ".join(provider_errors) if provider_errors else "model output failed validation"
        prompt_tokens = None
        completion_tokens = None
        template_checks = validate_text(narrative, allowed, spec.max_words)
        checks = {
            "ok": template_checks["ok"],
            "template": True,
            "numbers_checked": template_checks["numbers_checked"],
            "violations": template_checks["violations"],
            "style_issues": template_checks["style_issues"],
            "rejected_text": rejected_text,
            "provider_errors": provider_errors,
        }

    run_id = uuid.uuid4().hex
    output = {
        "text": narrative,
        "template": fallback,
        "rejected_text": rejected_text,
        "provider_errors": provider_errors,
    }
    rt.store.insert_agent_run(
        {
            "id": run_id,
            "created_at": created_at,
            "skill": skill_id,
            "subject": subject,
            "provider": provider,
            "model": model,
            "status": status,
            "fallback": fallback,
            "latency_ms": latency_ms,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cards": cards_meta,
            "checks": checks,
            "input": pack.to_audit(),
            "output": output,
            "narrative": narrative,
            "error": error,
        }
    )
    rt.events.publish(
        "agent.run",
        {
            "run_id": run_id,
            "skill": skill_id,
            "subject": subject,
            "provider": provider,
            "fallback": fallback,
        },
    )
    return AgentOutput(
        run_id=run_id,
        skill=skill_id,
        subject=subject,
        narrative=narrative,
        provider=provider,
        model=model,
        status=status,
        fallback=fallback,
        created_at=created_at,
        latency_ms=latency_ms,
        cards=cards_meta,
        checks=checks,
        error=error,
    )