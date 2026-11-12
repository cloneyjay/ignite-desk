"""System: health, settings, kill switch."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.ignite.analysis.risk import RiskConfig
from backend.ignite.api.deps import get_rt
from backend.ignite.api.errors import ApiError
from backend.ignite.forecasting.client import ForecastError
from backend.ignite.services.broker import BrokerError
from backend.ignite.services.runtime import Runtime

router = APIRouter(prefix="/api", tags=["system"])

ENABLED_TIMEFRAMES = ["M5", "M15", "M30", "H1"]


@router.get("/health")
def health(rt: Runtime = Depends(get_rt)) -> dict[str, Any]:
    mcp_ok = True
    mcp_error = None
    terminal: dict[str, Any] = {}
    tools = 0
    try:
        info = rt.call("terminal_get_info")
        terminal = info.get("terminal") or {}
        tools = len(rt.mcp.list_tools())
    except BrokerError as exc:
        mcp_ok = False
        mcp_error = str(exc)

    kronos: dict[str, Any] = {"ready": False, "error": "worker not reachable"}
    try:
        kronos = rt.forecast.health()
    except ForecastError as exc:
        kronos = {"ready": False, "error": str(exc)}

    clock = None
    offset_hours = None
    try:
        clock = rt.clock()
        offset_hours = clock.offset.total_seconds() / 3600.0
    except BrokerError:
        pass

    running = [j for j in rt.jobs.values() if j.status == "running"]
    return {
        "ok": mcp_ok and bool(kronos.get("ready")),
        "timezone": rt.local_zone(),
        "local_utc_offset_minutes": int(
            datetime.now().astimezone().utcoffset().total_seconds() // 60
        ),
        "server_time_utc": rt.now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "broker_time_server": clock.server_now().isoformat() if clock else None,
        "broker_offset_hours": offset_hours,
        "mcp": {
            "reachable": mcp_ok,
            "url": rt.settings.mcp.url,
            "tools": tools,
            "error": mcp_error,
        },
        "terminal": {
            "connected": (terminal.get("connection") or {}).get("state")
            in ("connected", "synchronized"),
            "state": (terminal.get("connection") or {}).get("state"),
            "build": terminal.get("build"),
            "trade_allowed": bool(terminal.get("mcp_trade_allowed")),
            "server": (terminal.get("connection") or {}).get("server"),
        },
        "kronos": kronos,
        "queue_depth": len(running),
        "kill_switch": rt.kill_switch(),
        "llm": {
            "nim": bool(os.getenv("NVIDIA_API_KEY")),
            "local": bool(os.getenv("OLLAMA_BASE_URL")),
        },
    }


@router.get("/settings")
def get_settings(rt: Runtime = Depends(get_rt)) -> dict[str, Any]:
    config = rt.risk_config()
    return {
        "kill_switch": rt.kill_switch(),
        "risk_pct": config.risk_pct,
        "max_risk_pct": config.max_risk_pct,
        "max_drift_atr": config.max_drift_atr,
        "max_spread_points": config.max_spread_points,
        "sl_atr": config.sl_atr,
        "tp_atr": config.tp_atr,
        "draft_ttl_s": rt.settings.draft_ttl_s,
        "timeframes": ENABLED_TIMEFRAMES,
        "news": {
            "pre_minutes": rt.news.pre.seconds // 60,
            "post_minutes": rt.news.post.seconds // 60,
            "currencies": list(rt.news.currencies),
        },
    }


class SettingsUpdate(BaseModel):
    kill_switch: bool | None = None
    risk_pct: float | None = Field(default=None, gt=0.0)


@router.put("/settings")
def update_settings(
    body: SettingsUpdate, rt: Runtime = Depends(get_rt)
) -> dict[str, Any]:
    if body.risk_pct is not None:
        if body.risk_pct > RiskConfig.max_risk_pct + 1e-12:
            raise ApiError(
                400,
                "risk_pct_above_cap",
                f"risk_pct {body.risk_pct:.4f} exceeds the hard cap "
                f"{RiskConfig.max_risk_pct:.4f}",
            )
        rt.store.set_setting("risk_pct", str(body.risk_pct))
        rt.store.audit("api", "risk_pct", {"risk_pct": body.risk_pct})
    if body.kill_switch is not None:
        rt.set_kill_switch(body.kill_switch)
        rt.store.audit("api", "kill_switch", {"enabled": body.kill_switch})
    return get_settings(rt)
