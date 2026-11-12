"""Account, positions and the equity series."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query

from backend.ignite.api.deps import get_rt
from backend.ignite.api.errors import ApiError
from backend.ignite.api.serializers import iso
from backend.ignite.services.broker import BrokerError
from backend.ignite.services.runtime import Runtime

router = APIRouter(prefix="/api", tags=["account"])

RANGES = {"1d": 1, "1w": 7, "1m": 30, "all": None}


@router.get("/account")
def account(rt: Runtime = Depends(get_rt)) -> dict[str, Any]:
    payload = rt.account_payload()
    try:
        positions = rt.positions()
    except BrokerError:
        positions = []

    enriched = []
    risk_at_stop = 0.0
    unprotected = []
    for position in positions:
        item = dict(position)
        contract = float(item.get("contract_size") or 0.0)
        lots = float(item.get("lots") or 0.0)
        price = item.get("price_current")
        sl = item.get("sl")
        if sl and price:
            risk = abs(float(price) - float(sl)) * contract * lots
            item["risk_at_stop_usd"] = round(risk, 2)
            risk_at_stop += risk
        else:
            item["risk_at_stop_usd"] = None
            unprotected.append(item["ticket"])
        try:
            atr = rt.atr(item["symbol"])
            item["atr"] = round(atr, 4)
            if sl and price and atr > 0:
                item["distance_to_stop_atr"] = round(
                    abs(float(price) - float(sl)) / atr, 2
                )
            else:
                item["distance_to_stop_atr"] = None
        except Exception:  # noqa: BLE001 - chart decoration only
            item["atr"] = None
            item["distance_to_stop_atr"] = None
        enriched.append(item)

    equity = float(payload.get("equity") or 0.0)
    realised = rt.realised_today()
    return {
        "account": payload,
        "positions": enriched,
        "risk": {
            "open_risk_usd": round(risk_at_stop, 2),
            "open_risk_pct": round(risk_at_stop / equity, 6) if equity > 0 else None,
            "cap_pct": rt.risk_config().max_risk_pct,
            "unprotected_tickets": unprotected,
        },
        "today": realised,
        "server_time_utc": iso(rt.now_utc()),
    }


@router.get("/positions")
def positions(rt: Runtime = Depends(get_rt)) -> dict[str, Any]:
    return {"positions": rt.positions()}


@router.get("/portfolio/equity")
def equity(
    range: str = Query("1d"),
    rt: Runtime = Depends(get_rt),
) -> dict[str, Any]:
    if range not in RANGES:
        raise ApiError(400, "bad_range", f"range must be one of {list(RANGES)}")
    days = RANGES[range]
    since = (
        (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        if days is not None
        else None
    )
    points = rt.store.equity_series(since)
    return {
        "range": range,
        "points": [
            {
                "ts": iso(point["ts"]),
                "balance": point["balance"],
                "equity": point["equity"],
                "margin": point["margin"],
                "free_margin": point["free_margin"],
            }
            for point in points
        ],
    }
