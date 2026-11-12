"""Analysis jobs and stored analyses."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from backend.ignite.analysis.graph import DEFAULT_HORIZON, DEFAULT_LOOKBACK
from backend.ignite.api.deps import get_rt
from backend.ignite.api.errors import ApiError
from backend.ignite.api.serializers import analysis_payload
from backend.ignite.services.analysis_service import (
    AnalysisError,
    refresh_draft,
    start_analysis,
)
from backend.ignite.services.runtime import Runtime

router = APIRouter(prefix="/api", tags=["analyses"])


class AnalysisRequest(BaseModel):
    symbol: str = Field(default="XAUUSD", min_length=1, max_length=32)
    timeframe: str = Field(default="M15")
    horizon: int | None = Field(default=None, ge=1, le=64)
    samples: int = Field(default=25, ge=1, le=100)


@router.post("/analyses", status_code=202)
def create_analysis(
    body: AnalysisRequest, rt: Runtime = Depends(get_rt)
) -> dict[str, Any]:
    timeframe = body.timeframe.upper()
    if timeframe not in DEFAULT_LOOKBACK:
        raise ApiError(
            400,
            "bad_timeframe",
            f"timeframe must be one of {sorted(DEFAULT_LOOKBACK)}",
        )
    job = start_analysis(
        rt,
        body.symbol.strip().upper(),
        timeframe,
        horizon=body.horizon,
        samples=body.samples,
    )
    return {
        "job": job.to_dict(),
        "horizon": body.horizon or DEFAULT_HORIZON[timeframe],
        "lookback": DEFAULT_LOOKBACK[timeframe],
    }


@router.get("/jobs/{job_id}")
def get_job(job_id: str, rt: Runtime = Depends(get_rt)) -> dict[str, Any]:
    job = rt.job(job_id)
    if job is None:
        raise ApiError(404, "job_not_found", f"no job {job_id}")
    return job.to_dict()


@router.get("/analyses/latest")
def latest_analysis(
    symbol: str = Query("XAUUSD"),
    tf: str = Query("M15"),
    rt: Runtime = Depends(get_rt),
) -> dict[str, Any]:
    row = rt.store.latest_analysis(symbol.upper(), tf.upper())
    if row is None:
        raise ApiError(
            404, "no_analysis", f"no analysis stored for {symbol.upper()} {tf.upper()}"
        )
    return analysis_payload(rt, row)


@router.get("/analyses/{analysis_id}")
def get_analysis(
    analysis_id: str,
    include_paths: bool = Query(True),
    rt: Runtime = Depends(get_rt),
) -> dict[str, Any]:
    row = rt.store.get_analysis(analysis_id)
    if row is None:
        raise ApiError(404, "analysis_not_found", f"no analysis {analysis_id}")
    return analysis_payload(rt, row, include_paths=include_paths)


@router.post("/analyses/{analysis_id}/draft", status_code=201)
def new_draft(
    analysis_id: str,
    rt: Runtime = Depends(get_rt),
) -> dict[str, Any]:
    row = rt.store.get_analysis(analysis_id)
    if row is None:
        raise ApiError(404, "analysis_not_found", f"no analysis {analysis_id}")
    try:
        draft = refresh_draft(rt, row)
    except AnalysisError as exc:
        raise ApiError(400, "no_trade", str(exc)) from exc
    return {"draft": draft, "analysis": analysis_payload(rt, row, include_paths=False)}
