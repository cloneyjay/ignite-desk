"""Watchlist symbols and bars."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from backend.ignite.analysis.risk import SymbolSpec
from backend.ignite.api.deps import get_rt
from backend.ignite.api.errors import ApiError
from backend.ignite.api.serializers import bar_payload, iso
from backend.ignite.market.bars import TIMEFRAME_MINUTES, fetch_bars
from backend.ignite.market.symbols import add_to_watchlist, remove_from_watchlist
from backend.ignite.services.broker import BrokerError
from backend.ignite.services.runtime import Runtime

router = APIRouter(prefix="/api", tags=["market"])


def _spec_row(spec: SymbolSpec) -> dict[str, Any]:
    return {
        "symbol": spec.symbol,
        "digits": spec.digits,
        "point": spec.point,
        "contract_size": spec.contract_size,
        "tick_value": spec.tick_value,
        "volume_min": spec.volume_min,
        "volume_max": spec.volume_max,
        "volume_step": spec.volume_step,
        "stops_level": spec.stops_level,
    }


@router.get("/symbols")
def list_symbols(rt: Runtime = Depends(get_rt)) -> dict[str, Any]:
    out = []
    for row in rt.store.list_symbols():
        item = dict(row)
        try:
            bid, ask = rt.quote(item["symbol"])
            item["bid"] = bid
            item["ask"] = ask
            item["spread_points"] = round(
                (ask - bid) / float(item["point"]), 1
            ) if float(item["point"]) > 0 else None
        except BrokerError:
            item["bid"] = item["ask"] = item["spread_points"] = None
        out.append(item)
    return {"symbols": out}


class SymbolAdd(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)


@router.post("/symbols", status_code=201)
def add_symbol(body: SymbolAdd, rt: Runtime = Depends(get_rt)) -> dict[str, Any]:
    symbol = body.symbol.strip().upper()
    if not symbol:
        raise ApiError(400, "bad_symbol", "symbol is required")
    try:
        spec = add_to_watchlist(rt.mcp, symbol)
    except Exception as exc:  # noqa: BLE001
        raise ApiError(
            502,
            "symbol_add_failed",
            f"could not add {symbol} to MT5 Market Watch: {exc}",
        ) from exc
    rt.store.add_symbol(_spec_row(spec))
    rt.store.audit("api", "symbol_add", {"symbol": symbol})
    return {"symbol": _spec_row(spec)}


@router.delete("/symbols/{symbol}", status_code=200)
def delete_symbol(symbol: str, rt: Runtime = Depends(get_rt)) -> dict[str, Any]:
    symbol = symbol.upper()
    try:
        remove_from_watchlist(rt.mcp, symbol)
    except Exception as exc:  # noqa: BLE001 - DB cleanup still proceeds
        rt.store.audit("api", "symbol_remove_mt5_failed", {"symbol": symbol}, str(exc))
    rt.store.remove_symbol(symbol)
    rt.store.audit("api", "symbol_remove", {"symbol": symbol})
    return {"removed": symbol}


@router.get("/bars")
def bars(
    symbol: str = Query(..., min_length=1),
    tf: str = Query("M15"),
    count: int = Query(300, ge=16, le=1500),
    rt: Runtime = Depends(get_rt),
) -> dict[str, Any]:
    if tf not in TIMEFRAME_MINUTES:
        raise ApiError(400, "bad_timeframe", f"unsupported timeframe {tf!r}")
    try:
        frame = fetch_bars(rt.mcp, rt.clock(), symbol.upper(), tf, count)
    except Exception as exc:  # noqa: BLE001 - a data problem is a 502, not a crash
        raise ApiError(502, "bars_unavailable", str(exc)) from exc
    return {
        "symbol": symbol.upper(),
        "timeframe": tf,
        "count": len(frame),
        "last_bar_time": iso(frame["time"].iloc[-1]),
        "bars": bar_payload(frame),
    }
