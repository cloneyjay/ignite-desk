"""Analysis jobs: fetch, cache-check, run the graph, persist, notify.

One job at a time is enough: the Kronos worker serialises anyway. The cache key
is the last closed bar, so a second click on the same bar is instant (W-5).
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timedelta
from typing import Any

from backend.ignite.analysis.graph import (
    DEFAULT_HORIZON,
    DEFAULT_LOOKBACK,
    build_draft,
    run_analysis,
)
from backend.ignite.market.bars import fetch_bars
from backend.ignite.services.runtime import Job, Runtime
from backend.ignite.store.db import utc_now


class AnalysisError(ValueError):
    pass


def start_analysis(
    rt: Runtime,
    symbol: str,
    timeframe: str,
    horizon: int | None = None,
    samples: int = 25,
) -> Job:
    if timeframe not in DEFAULT_LOOKBACK:
        raise AnalysisError(f"unsupported timeframe {timeframe!r}")
    if not 1 <= samples <= 100:
        raise AnalysisError("samples must be between 1 and 100")
    if horizon is not None and not 1 <= horizon <= 64:
        raise AnalysisError("horizon must be between 1 and 64")
    if not symbol:
        raise AnalysisError("symbol is required")

    job = Job(
        id=uuid.uuid4().hex,
        symbol=symbol,
        timeframe=timeframe,
        status="running",
        step="queued",
        message="queued",
        pct=1,
    )
    rt.register_job(job)
    rt.events.publish(
        "analysis.started",
        {"job_id": job.id, "symbol": symbol, "timeframe": timeframe},
    )
    thread = threading.Thread(
        target=_worker, args=(rt, job, horizon, samples), name=f"analysis-{job.id[:8]}"
    )
    thread.daemon = True
    thread.start()
    return job


def _worker(rt: Runtime, job: Job, horizon: int | None, samples: int) -> None:
    try:
        lookback = DEFAULT_LOOKBACK[job.timeframe]
        rt.job_progress(
            job, "bars", f"fetching {lookback} closed {job.timeframe} bars", 8
        )
        bars = fetch_bars(rt.mcp, rt.clock(), job.symbol, job.timeframe, lookback)
        last_bar = str(bars["time"].iloc[-1])

        cached = rt.store.find_analysis_for_bar(job.symbol, job.timeframe, last_bar)
        if cached is not None:
            job.analysis_id = cached["id"]
            job.cached = True
            job.status = "done"
            job.step = "cached"
            job.message = "reused the analysis for this bar"
            job.pct = 100
            rt.job_progress(job, "cached", "reused the analysis for this bar", 100)
            rt.events.publish(
                "analysis.done",
                {
                    "job_id": job.id,
                    "analysis_id": cached["id"],
                    "cached": True,
                    "symbol": job.symbol,
                    "timeframe": job.timeframe,
                },
            )
            return

        equity = float(rt.account().get("equity") or 0.0)
        if equity <= 0:
            raise AnalysisError("account equity is not available")

        result = run_analysis(
            rt.mcp,
            rt.clock(),
            rt.forecast,
            job.symbol,
            job.timeframe,
            equity,
            horizon=horizon or DEFAULT_HORIZON[job.timeframe],
            samples=samples,
            risk_config=rt.risk_config(),
            bars=bars,
            progress=lambda step, message, pct: rt.job_progress(job, step, message, pct),
        )
        rt.store.save_analysis(result, rt.settings.draft_ttl_s)

        job.analysis_id = result.analysis_id
        job.status = "done"
        job.step = "done"
        job.message = "analysis complete"
        job.pct = 100
        rt.events.publish(
            "analysis.done",
            {
                "job_id": job.id,
                "analysis_id": result.analysis_id,
                "cached": False,
                "symbol": job.symbol,
                "timeframe": job.timeframe,
                "side": result.signal.side,
            },
        )
    except Exception as exc:  # noqa: BLE001 - the job owns its failure
        job.status = "failed"
        job.error = str(exc)
        job.step = "failed"
        rt.events.publish(
            "analysis.failed",
            {
                "job_id": job.id,
                "symbol": job.symbol,
                "timeframe": job.timeframe,
                "error": str(exc),
            },
        )


def refresh_draft(rt: Runtime, analysis: dict[str, Any]) -> dict[str, Any]:
    """Mint a fresh draft for an existing analysis (explicit user action).

    The stored analysis stays untouched; only entry price, drift check and
    expiry are refreshed. Stale drafts are never resurrected silently.
    """
    side = analysis["signal"]
    if side not in ("long", "short"):
        raise AnalysisError("this analysis produced no trade")
    features = json.loads(analysis["features_json"])
    atr = float(features["atr"])
    last_close = float(features["last_close"])
    symbol = analysis["symbol"]

    spec = rt.spec(symbol)
    spread = rt.spread(symbol)
    equity = float(rt.account().get("equity") or 0.0)
    if equity <= 0:
        raise AnalysisError("account equity is not available")

    draft = build_draft(
        rt.mcp,
        symbol,
        side,
        atr,
        spread,
        equity,
        spec,
        rt.risk_config(),
        last_close=last_close,
    )
    return insert_draft(rt, analysis["id"], draft)


def insert_draft(rt: Runtime, analysis_id: str, draft: Any) -> dict[str, Any]:
    now = datetime.now().astimezone().replace(microsecond=0)
    created = utc_now()
    expires = (
        datetime.fromisoformat(created) + timedelta(seconds=rt.settings.draft_ttl_s)
    ).isoformat()
    draft_id = uuid.uuid4().hex
    rt.store.insert_draft(
        {
            "id": draft_id,
            "analysis_id": analysis_id,
            "created_at": created,
            "expires_at": expires,
            "state": "blocked" if draft.blocked else "draft",
            "side": draft.side,
            "lots": draft.lots,
            "reference_price": draft.reference_price,
            "sl": draft.sl,
            "tp": draft.tp,
            "risk_usd": draft.risk_usd,
            "risk_pct": draft.risk_pct,
            "rr": draft.rr,
            "margin": draft.margin,
            "worst_case_usd": draft.worst_case_usd,
            "blocked": int(draft.blocked),
            "block_reason": draft.block_reason,
            "idempotency_key": f"{analysis_id}:{now.timestamp()}:{draft.lots}",
        }
    )
    stored = rt.store.get_draft(draft_id)
    rt.events.publish(
        "draft.created",
        {
            "draft_id": draft_id,
            "analysis_id": analysis_id,
            "side": draft.side,
            "blocked": draft.blocked,
        },
    )
    return stored or {}
