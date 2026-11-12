"""Typed wrappers over the MT5 MCP tools used by the API.

All timestamps leaving this module are UTC ISO-8601. MT5 reports trade-server
wall clock without an offset, so every field is converted here, once.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.ignite.market.time import Clock
from backend.ignite.mcp.client import MCPClient, MCPError


class BrokerError(RuntimeError):
    """The terminal/MCP layer failed. Callers turn this into a 503."""


def _iso(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        return text
    return text + "Z"


def _server_to_utc(clock: Clock, value: str | None) -> str | None:
    if not value:
        return None
    naive = datetime.fromisoformat(value)
    return (
        clock.server_to_utc(naive)
        .replace(tzinfo=timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def account(mcp: MCPClient) -> dict[str, Any]:
    payload = mcp.call_tool("get_trading_account_info")
    acc = payload.get("account") or {}
    terminal = payload.get("terminal") or {}
    connection = terminal.get("connection") or {}
    return {
        "server": acc.get("server"),
        "login": acc.get("login"),
        "name": acc.get("name"),
        "type": acc.get("type"),
        "read_only": acc.get("read_only"),
        "margin_mode": acc.get("margin_mode"),
        "currency": acc.get("currency"),
        "balance": acc.get("balance"),
        "credit": acc.get("credit"),
        "equity": acc.get("equity"),
        "margin": acc.get("margin"),
        "margin_free": acc.get("margin_free"),
        "margin_level": (
            round(float(acc["equity"]) / float(acc["margin"]) * 100.0, 2)
            if acc.get("equity") and acc.get("margin")
            else None
        ),
        "profit": acc.get("profit"),
        "swaps": acc.get("swaps"),
        "commissions": acc.get("commissions"),
        "terminal": {
            "connected": connection.get("state") == "synchronized",
            "state": connection.get("state"),
            "ping_us": connection.get("ping_microseconds"),
            "build": terminal.get("build"),
            "trade_allowed": bool(terminal.get("mcp_trade_allowed")),
            "experts_trade_allowed": bool(terminal.get("experts_trade_allowed")),
            "server_time_utc": _iso(terminal.get("timestamp")),
        },
    }


def positions(mcp: MCPClient, clock: Clock, symbol: str | None = None) -> list[dict[str, Any]]:
    args: dict[str, Any] = {"include_orders": True}
    if symbol:
        args["symbol"] = symbol
    payload = mcp.call_tool("get_trading_open_positions", args)
    rows = payload.get("positions") or []
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "ticket": str(row.get("position_id")),
                "symbol": row.get("symbol"),
                "side": row.get("action"),
                "lots": float(row.get("volume") or 0.0),
                "price_open": row.get("price_open"),
                "price_current": row.get("price_last"),
                "sl": row.get("sl"),
                "tp": row.get("tp"),
                "profit": row.get("profit"),
                "swap": row.get("swaps"),
                "contract_size": row.get("contract_size"),
                "comment": row.get("comment"),
                "open_time": _server_to_utc(clock, row.get("create_time")),
                "update_time": _server_to_utc(clock, row.get("update_time")),
            }
        )
    return out


def history(
    mcp: MCPClient, clock: Clock, start_utc: datetime, end_utc: datetime, symbol: str | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Closed positions, orders and deals in a UTC window."""
    args = {
        "datetime_from": clock.utc_to_server(start_utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "datetime_to": clock.utc_to_server(end_utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "include_orders": True,
        "include_deals": True,
        "limit": 5000,
    }
    if symbol:
        args["symbol"] = symbol
    payload = mcp.call_tool("get_trading_history_orders", args)
    return {
        "positions": payload.get("positions") or [],
        "orders": payload.get("orders") or [],
        "deals": payload.get("deals") or [],
    }


def closed_trades(
    mcp: MCPClient, clock: Clock, start_utc: datetime, end_utc: datetime,
    symbol: str | None = None,
) -> list[dict[str, Any]]:
    """Reconstruct closed round-trips from deals (in/out pairs by position id)."""
    data = history(mcp, clock, start_utc, end_utc, symbol)
    grouped: dict[str, dict[str, Any]] = {}
    for deal in data["deals"]:
        position_id = str(deal.get("position_id") or "")
        if not position_id:
            continue
        trade = grouped.setdefault(
            position_id,
            {
                "ticket": position_id,
                "symbol": deal.get("symbol"),
                "side": None,
                "lots": 0.0,
                "entry": None,
                "exit": None,
                "gross": 0.0,
                "commission": 0.0,
                "swap": 0.0,
                "open_time": None,
                "close_time": None,
                "comment": deal.get("comment"),
            },
        )
        entry = str(deal.get("entry") or "")
        price = deal.get("price_open")
        stamp = _server_to_utc(clock, deal.get("open_time"))
        if entry == "in":
            trade["side"] = deal.get("action")
            trade["lots"] = float(deal.get("volume") or 0.0)
            trade["entry"] = price
            trade["open_time"] = stamp
        elif entry == "out":
            trade["exit"] = price
            trade["close_time"] = stamp
            trade["gross"] += float(deal.get("profit") or 0.0)
            trade["commission"] += float(deal.get("commission") or 0.0)
            trade["swap"] += float(deal.get("swap") or 0.0)

    trades = []
    for trade in grouped.values():
        if trade["close_time"] is None:
            continue
        trade["net"] = round(
            trade["gross"] + trade["commission"] + trade["swap"], 2
        )
        trade["duration_s"] = _duration_seconds(trade["open_time"], trade["close_time"])
        trades.append(trade)
    trades.sort(key=lambda t: t["close_time"] or "", reverse=True)
    return trades


def _duration_seconds(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return None
    try:
        a = datetime.fromisoformat(start)
        b = datetime.fromisoformat(end)
    except ValueError:
        return None
    return max(0, int((b - a).total_seconds()))


def check_market_order(
    mcp: MCPClient, symbol: str, side: str, volume: float, sl: float, tp: float
) -> dict[str, Any]:
    payload = mcp.call_tool(
        "trade_check_market_order",
        {"symbol": symbol, "type": side, "volume": volume, "sl": sl, "tp": tp},
    )
    if not payload.get("ok"):
        raise BrokerError(f"trade_check_market_order refused: {payload}")
    return payload


def send_market_order(
    mcp: MCPClient,
    symbol: str,
    side: str,
    volume: float,
    sl: float,
    tp: float,
    comment: str,
) -> dict[str, Any]:
    if not sl or not tp:
        raise BrokerError("refusing to send a market order without both SL and TP")
    payload = mcp.call_tool(
        "trade_send_market_order",
        {
            "symbol": symbol,
            "type": side,
            "volume": volume,
            "sl": sl,
            "tp": tp,
            "comment": comment[:31],
        },
    )
    if not payload.get("ok"):
        raise BrokerError(f"trade_send_market_order failed: {payload}")
    return payload


def extract_order_ticket(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    """Pull (order_id, position_id) out of the broker response, defensively."""
    candidates: list[dict[str, Any]] = []
    for key in ("result", "order", "data", "position"):
        value = payload.get(key)
        if isinstance(value, dict):
            candidates.append(value)
        elif isinstance(value, str) and value.isdigit():
            candidates.append({"order_id": value})
    candidates.append(payload)
    order_id = position_id = None
    for candidate in candidates:
        order_id = order_id or _digits(candidate.get("order_id") or candidate.get("order"))
        position_id = position_id or _digits(candidate.get("position_id"))
    return order_id, position_id


def _digits(value: Any) -> str | None:
    text = str(value) if value is not None else ""
    return text if text.isdigit() else None
