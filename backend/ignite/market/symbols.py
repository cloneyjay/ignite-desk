"""Symbol specification and watchlist operations over MCP."""

from __future__ import annotations

from backend.ignite.analysis.risk import SymbolSpec
from backend.ignite.mcp.client import MCPClient, MCPError


class SymbolError(RuntimeError):
    pass


def get_spec(mcp: MCPClient, symbol: str) -> SymbolSpec:
    payload = mcp.call_tool("get_marketwatch_symbols", {"symbol": symbol})
    rows = payload.get("symbols") or []
    if not rows:
        raise SymbolError(f"{symbol} is not in Market Watch")
    row = rows[0]

    required = ("digits", "point", "contract_size", "volume_min", "volume_max", "volume_step")
    missing = [k for k in required if row.get(k) is None]
    if missing:
        raise SymbolError(f"{symbol} specification is missing {missing}")

    return SymbolSpec(
        symbol=str(row["symbol"]),
        digits=int(row["digits"]),
        point=float(row["point"]),
        contract_size=float(row["contract_size"]),
        tick_value=float(row.get("tick_value") or 0.0),
        volume_min=float(row["volume_min"]),
        volume_max=float(row["volume_max"]),
        volume_step=float(row["volume_step"]),
        stops_level=int(row.get("trade_stops_level") or 0),
    )


def quote(mcp: MCPClient, symbol: str) -> tuple[float, float]:
    payload = mcp.call_tool("get_marketwatch_symbols", {"symbol": symbol})
    rows = payload.get("symbols") or []
    if not rows:
        raise SymbolError(f"{symbol} is not in Market Watch")
    bid = rows[0].get("bid")
    ask = rows[0].get("ask")
    if bid is None or ask is None:
        raise SymbolError(f"{symbol} has no live quote")
    return float(bid), float(ask)


def spread_points(bid: float, ask: float, point: float) -> float:
    if point <= 0:
        return 0.0
    return max(0.0, (ask - bid) / point)


def calc_margin(
    mcp: MCPClient, symbol: str, side: str, volume: float, price: float
) -> float:
    payload = mcp.call_tool(
        "trade_order_calc_margin",
        {"symbol": symbol, "type": side, "volume": volume, "price": price},
    )
    if not payload.get("ok") or payload.get("margin") is None:
        raise SymbolError(f"margin calculation failed: {payload}")
    return float(payload["margin"])


def calc_profit(
    mcp: MCPClient,
    symbol: str,
    side: str,
    volume: float,
    price_open: float,
    price_close: float,
) -> float:
    payload = mcp.call_tool(
        "trade_order_calc_profit",
        {
            "symbol": symbol,
            "type": side,
            "volume": volume,
            "price_open": price_open,
            "price_close": price_close,
        },
    )
    if not payload.get("ok") or payload.get("profit") is None:
        raise SymbolError(f"profit calculation failed: {payload}")
    return float(payload["profit"])


def add_to_watchlist(mcp: MCPClient, symbol: str) -> SymbolSpec:
    try:
        mcp.call_tool("add_marketwatch_symbol", {"symbol": symbol, "show": True})
    except MCPError as exc:
        raise SymbolError(f"could not add {symbol}: {exc}") from exc
    return get_spec(mcp, symbol)


def remove_from_watchlist(mcp: MCPClient, symbol: str) -> None:
    mcp.call_tool("remove_marketwatch_symbol", {"symbol": symbol})
