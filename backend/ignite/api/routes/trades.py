"""Trade history and statistics.

Closed trades come from MT5 deals (the terminal is the source of truth); our
own orders table adds the risk that was planned when the trade was taken, so
R-multiples are real rather than reconstructed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query

from backend.ignite.api.deps import get_rt
from backend.ignite.api.errors import ApiError
from backend.ignite.api.serializers import iso
from backend.ignite.services import broker
from backend.ignite.services.runtime import Runtime

router = APIRouter(prefix="/api", tags=["trades"])


def _parse(value: str | None, default: datetime) -> datetime:
    if not value:
        return default
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApiError(400, "bad_datetime", f"invalid datetime {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _window(from_: str | None, to: str | None) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    start = _parse(from_, now - timedelta(days=30))
    end = _parse(to, now)
    if start >= end:
        raise ApiError(400, "bad_range", "from must be earlier than to")
    return start, end


def _trades(rt: Runtime, start: datetime, end: datetime, symbol: str | None) -> list[dict[str, Any]]:
    trades = broker.closed_trades(rt.mcp, rt.clock(), start, end, symbol)
    for trade in trades:
        risk = rt.store.order_risk(trade["ticket"])
        trade["risk_usd"] = risk
        trade["r_multiple"] = (
            round(float(trade["net"]) / risk, 2) if risk and risk > 0 else None
        )
    return trades


@router.get("/trades")
def trades(
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    symbol: str | None = Query(None),
    side: str | None = Query(None),
    result: str | None = Query(None),
    rt: Runtime = Depends(get_rt),
) -> dict[str, Any]:
    start, end = _window(from_, to)
    rows = _trades(rt, start, end, symbol.upper() if symbol else None)
    if side:
        rows = [row for row in rows if row["side"] == side.lower()]
    if result == "win":
        rows = [row for row in rows if float(row["net"]) > 0]
    elif result == "loss":
        rows = [row for row in rows if float(row["net"]) <= 0]
    return {
        "from": iso(start),
        "to": iso(end),
        "trades": rows,
        "orders": rt.store.recent_orders(100),
    }


@router.get("/stats")
def stats(
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    rt: Runtime = Depends(get_rt),
) -> dict[str, Any]:
    start, end = _window(from_, to)
    rows = _trades(rt, start, end, None)
    nets = [float(row["net"]) for row in rows]
    wins = [value for value in nets if value > 0]
    losses = [value for value in nets if value <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    total = sum(nets)

    curve = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in nets:
        curve += value
        peak = max(peak, curve)
        max_dd = max(max_dd, peak - curve)

    r_values = [float(row["r_multiple"]) for row in rows if row["r_multiple"] is not None]
    durations = [row["duration_s"] for row in rows if row["duration_s"] is not None]

    return {
        "from": iso(start),
        "to": iso(end),
        "trades": len(rows),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(rows), 4) if rows else None,
        "net_usd": round(total, 2),
        "gross_win_usd": round(gross_win, 2),
        "gross_loss_usd": round(gross_loss, 2),
        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else None,
        "average_win_usd": round(gross_win / len(wins), 2) if wins else None,
        "average_loss_usd": round(-gross_loss / len(losses), 2) if losses else None,
        "average_r": round(sum(r_values) / len(r_values), 3) if r_values else None,
        "expectancy_usd": round(total / len(rows), 2) if rows else None,
        "max_drawdown_usd": round(max_dd, 2),
        "average_hold_s": int(sum(durations) / len(durations)) if durations else None,
    }


@router.get("/orders")
def orders(
    limit: int = Query(100, ge=1, le=500), rt: Runtime = Depends(get_rt)
) -> dict[str, Any]:
    return {"orders": rt.store.recent_orders(limit)}
