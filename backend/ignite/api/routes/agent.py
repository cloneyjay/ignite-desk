"""Agent endpoints: narrative commentary, run log, knowledge inspection, chat.

The narrative endpoint has no execution path. It cannot change a signal, a
draft, or a guard; it only explains a stored analysis.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from backend.ignite.agent.chat import ChatRoute, route_or_error
from backend.ignite.agent.runner import AgentError, AgentOutput, run_skill
from backend.ignite.api.deps import get_rt
from backend.ignite.api.errors import ApiError
from backend.ignite.services.runtime import Runtime
from backend.ignite.services.analysis_service import start_analysis

router = APIRouter(prefix="/api", tags=["agent"])

NARRATIVE = "analysis_narrative"
SKILLS = ("analysis_narrative", "daily_brief", "news_bias", "draft_review", "postmortem")


def _analysis_or_404(rt: Runtime, analysis_id: str) -> dict[str, Any]:
    row = rt.store.get_analysis(analysis_id)
    if row is None:
        raise ApiError(404, "analysis_not_found", f"no analysis {analysis_id}")
    return row


@router.get("/analyses/{analysis_id}/narrative")
def get_narrative(
    analysis_id: str, rt: Runtime = Depends(get_rt)
) -> dict[str, Any]:
    _analysis_or_404(rt, analysis_id)
    row = rt.store.latest_agent_run(NARRATIVE, analysis_id)
    if row is None:
        return {
            "run_id": None,
            "skill": NARRATIVE,
            "subject": analysis_id,
            "analysis_id": analysis_id,
            "narrative": None,
            "provider": None,
            "model": None,
            "status": "not_generated",
            "fallback": False,
            "created_at": None,
            "latency_ms": None,
            "cards": [],
            "checks": {},
            "error": "no commentary has been generated for this analysis yet",
        }
    return AgentOutput.from_run(row).payload()


class NarrativeRequest(BaseModel):
    refresh: bool = False


@router.post("/analyses/{analysis_id}/narrative")
def create_narrative(
    analysis_id: str,
    body: NarrativeRequest | None = None,
    rt: Runtime = Depends(get_rt),
) -> dict[str, Any]:
    _analysis_or_404(rt, analysis_id)
    try:
        output = run_skill(
            rt,
            NARRATIVE,
            analysis_id,
            refresh=bool(body and body.refresh),
        )
    except AgentError as exc:
        raise ApiError(400, "agent_error", str(exc)) from exc
    return output.payload()


@router.get("/agent/runs")
def recent_runs(
    limit: int = Query(50, ge=1, le=200), rt: Runtime = Depends(get_rt)
) -> dict[str, Any]:
    runs = rt.store.recent_agent_runs(limit)
    summary = [
        {
            "id": run["id"],
            "created_at": run["created_at"],
            "skill": run["skill"],
            "subject": run["subject"],
            "provider": run["provider"],
            "model": run["model"],
            "status": run["status"],
            "fallback": run["fallback"],
            "latency_ms": run["latency_ms"],
            "cards": [card["id"] for card in run.get("cards") or []],
            "checks": {
                "ok": (run.get("checks") or {}).get("ok"),
                "numbers_checked": (run.get("checks") or {}).get("numbers_checked"),
                "violations": (run.get("checks") or {}).get("violations"),
            },
            "narrative": run.get("narrative"),
            "error": run.get("error"),
        }
        for run in runs
    ]
    return {"runs": summary, "count": len(summary)}


@router.get("/agent/runs/{run_id}")
def get_run(run_id: str, rt: Runtime = Depends(get_rt)) -> dict[str, Any]:
    run = rt.store.agent_run(run_id)
    if run is None:
        raise ApiError(404, "run_not_found", f"no agent run {run_id}")
    return {"run": run}


@router.get("/knowledge/status")
def knowledge_status(rt: Runtime = Depends(get_rt)) -> dict[str, Any]:
    return rt.knowledge_stats()


@router.get("/knowledge/cards")
def knowledge_cards(
    scope: str | None = Query(None),
    q: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    rt: Runtime = Depends(get_rt),
) -> dict[str, Any]:
    if q:
        cards = rt.store.search_knowledge(q, limit)
        if scope:
            cards = [card for card in cards if card["scope"] == scope]
    else:
        rows = rt.store.knowledge_cards(scope=scope)
        cards = rows[:limit]
    return {
        "cards": [
            {
                "id": card["id"],
                "title": card["title"],
                "scope": card["scope"],
                "layer": card["layer"],
                "version": card["version"],
                "status": card["status"],
                "priority": card["priority"],
                "tags": card["tags"],
                "applies_to": card["applies_to"],
                "source_path": card["source_path"],
                "body": card["body"],
            }
            for card in cards
        ],
        "count": len(cards),
    }


@router.get("/knowledge/cards/{card_id}")
def knowledge_card(card_id: str, rt: Runtime = Depends(get_rt)) -> dict[str, Any]:
    card = rt.store.knowledge_card(card_id)
    if card is None:
        raise ApiError(404, "card_not_found", f"no knowledge card {card_id}")
    return {"card": card}


class ChatRequest(BaseModel):
    text: str


@router.post("/agent/chat")
def agent_chat(
    body: ChatRequest, rt: Runtime = Depends(get_rt)
) -> dict[str, Any]:
    """Route a natural-language request to the appropriate skill."""
    try:
        route: ChatRoute = route_or_error(body.text)
    except ValueError as exc:
        raise ApiError(400, "route_failed", str(exc)) from exc

    try:
        if route.needs_analysis:
            # Start analysis job
            symbol = route.args.get("symbol", "XAUUSD")
            timeframe = route.args.get("timeframe", "M15")
            job = start_analysis(rt, symbol, timeframe)
            # Wait for job to complete
            import time
            start = time.monotonic()
            timeout = 120.0
            while True:
                job_status = rt.job(job.id)
                if not job_status:
                    raise ApiError(500, "job_lost", f"job {job.id} disappeared")
                if job_status.status == "done":
                    analysis_id = job_status.analysis_id
                    break
                if job_status.status == "failed":
                    raise ApiError(500, "analysis_failed", job_status.error or "unknown error")
                if time.monotonic() - start > timeout:
                    raise ApiError(504, "analysis_timeout", f"analysis job timed out after {timeout}s")
                time.sleep(0.5)
            subject = analysis_id
        else:
            subject = _skill_subject(rt, route.skill, **route.args)

        output = run_skill(rt, route.skill, subject, refresh=True)
    except AgentError as exc:
        raise ApiError(400, "agent_error", str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise ApiError(500, "agent_error", str(exc)) from exc

    return {
        "route": {"skill": route.skill, "args": route.args, "confidence": route.confidence},
        "output": output.payload(),
    }


def _skill_subject(rt: Runtime, skill: str, **kwargs) -> str:
    if skill == "analysis_narrative":
        analysis_id = kwargs.get("analysis_id")
        if not analysis_id:
            row = rt.store.latest_analysis(kwargs.get("symbol", "XAUUSD"), kwargs.get("tf", "M15"))
            analysis_id = row["id"] if row else None
        return analysis_id or "latest"
    return kwargs.get("subject", "latest")


def _skill_endpoint(skill: str):
    def endpoint(
        rt: Runtime = Depends(get_rt),
        symbol: str = Query("XAUUSD"),
        tf: str = Query("M15"),
        analysis_id: str | None = Query(None),
        subject: str | None = Query(None),
        refresh: bool = Query(False),
    ) -> dict[str, Any]:
        subj = _skill_subject(rt, skill, symbol=symbol, tf=tf, analysis_id=analysis_id, subject=subject)
        try:
            output = run_skill(rt, skill, subj, refresh=refresh)
        except AgentError as exc:
            raise ApiError(400, "agent_error", str(exc)) from exc
        return output.payload()

    return endpoint


for skill in SKILLS:
    if skill == "analysis_narrative":
        continue
    router.post(f"/agent/{skill}")(_skill_endpoint(skill))
    router.get(f"/agent/{skill}")(_skill_endpoint(skill))
