"""Draft inspection, confirmation tokens and execution."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.ignite.api.deps import get_rt
from backend.ignite.api.errors import ApiError
from backend.ignite.api.serializers import analysis_payload, draft_payload, iso
from backend.ignite.services.execution import evaluate_draft, execute_draft
from backend.ignite.services.runtime import Runtime

router = APIRouter(prefix="/api", tags=["drafts"])


def _draft_or_404(rt: Runtime, draft_id: str) -> dict[str, Any]:
    draft = rt.store.get_draft(draft_id)
    if draft is None:
        raise ApiError(404, "draft_not_found", f"no draft {draft_id}")
    return draft


@router.get("/drafts/{draft_id}")
def get_draft(draft_id: str, rt: Runtime = Depends(get_rt)) -> dict[str, Any]:
    draft = _draft_or_404(rt, draft_id)
    evaluation = evaluate_draft(rt, draft)
    analysis = rt.store.get_analysis(draft["analysis_id"])
    return {
        "draft": draft_payload(draft, evaluation),
        "analysis": analysis_payload(rt, analysis, include_paths=False)
        if analysis
        else None,
    }


class ConfirmRequest(BaseModel):
    confirm: bool = True


@router.post("/drafts/{draft_id}/confirm")
def confirm_draft(
    draft_id: str, body: ConfirmRequest, rt: Runtime = Depends(get_rt)
) -> dict[str, Any]:
    """Issue the single-use token that the execute call must present."""
    if not body.confirm:
        raise ApiError(400, "confirm_required", "confirmation must be acknowledged")
    draft = _draft_or_404(rt, draft_id)
    evaluation = evaluate_draft(rt, draft)
    if not evaluation["executable"]:
        failing = next(check for check in evaluation["checks"] if not check["ok"])
        raise ApiError(
            409,
            failing["code"],
            failing["message"],
            {"checks": evaluation["checks"], "draft": draft_payload(draft, evaluation)},
        )
    token = rt.issue_token(draft_id, draft["expires_at"])
    rt.store.audit("api", "confirm", {"draft_id": draft_id})
    return {
        "token": token,
        "draft_id": draft_id,
        "expires_at": iso(draft["expires_at"]),
        "expires_in_s": max(
            0,
            int(
                (
                    datetime.fromisoformat(draft["expires_at"])
                    - datetime.now(timezone.utc)
                ).total_seconds()
            ),
        ),
        "summary": draft_payload(draft, evaluation),
    }


class ExecuteRequest(BaseModel):
    confirm: bool = False
    token: str = ""


@router.post("/drafts/{draft_id}/execute")
def execute(
    draft_id: str, body: ExecuteRequest, rt: Runtime = Depends(get_rt)
) -> dict[str, Any]:
    return execute_draft(
        rt, draft_id, confirm=body.confirm, token=body.token or None
    )
