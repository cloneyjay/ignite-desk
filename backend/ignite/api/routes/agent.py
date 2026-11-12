"""Agent endpoints: narrative commentary, run log, knowledge inspection.

The narrative endpoint has no execution path. It cannot change a signal, a
draft, or a guard; it only explains a stored analysis.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from backend.ignite.agent.runner import AgentError, AgentOutput, run_skill
from backend.ignite.api.deps import get_rt
from backend.ignite.api.errors import ApiError
from backend.ignite.services.runtime import Runtime

router = APIRouter(prefix="/api", tags=["agent"])

NARRATIVE = "analysis_narrative"


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
