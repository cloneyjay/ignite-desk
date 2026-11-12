"""Shared test doubles. No network, no MT5, no torch."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

SPEC = {
    "symbol": "XAUUSD",
    "digits": 2,
    "point": 0.01,
    "contract_size": 100.0,
    "tick_value": 0.1,
    "volume_min": 0.01,
    "volume_max": 100.0,
    "volume_step": 0.01,
    "trade_stops_level": 0,
}


class FakeMCP:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.bid = 3930.0
        self.ask = 3930.13
        self.positions: list[dict[str, Any]] = []
        self.send_ok = True
        self.check_ok = True
        self.margin = 7.82
        self.next_ticket = "900001"
        self.blackout_events: list[dict[str, Any]] = []

    def initialize(self) -> dict[str, Any]:
        return {"serverInfo": {"name": "fake"}}

    def list_tools(self) -> list[dict[str, Any]]:
        return [{"name": "get_trading_account_info"}]

    def close(self) -> None:
        pass

    def called(self, name: str) -> list[dict[str, Any]]:
        return [args for tool, args in self.calls if tool == name]

    def _now(self) -> datetime:
        return datetime.now(timezone.utc).replace(microsecond=0)

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        args = arguments or {}
        self.calls.append((name, args))
        now = self._now()

        if name == "get_time_information":
            return {
                "utc_time": now.isoformat().replace("+00:00", "Z"),
                "trade_server_last_known_time": (now + timedelta(hours=2))
                .replace(tzinfo=None)
                .isoformat(),
            }
        if name == "get_marketwatch_symbols":
            row = dict(SPEC, bid=self.bid, ask=self.ask)
            return {"ok": True, "symbols": [row]}
        if name == "get_trading_account_info":
            return {
                "account": {
                    "server": "Fake-Demo",
                    "login": "1",
                    "currency": "USD",
                    "balance": 3000.0,
                    "equity": 3000.0,
                    "margin": 0.0,
                    "margin_free": 3000.0,
                    "profit": 0.0,
                    "type": "demo",
                    "read_only": False,
                },
                "terminal": {"connection": {"state": "synchronized"}, "build": 1},
            }
        if name == "get_trading_open_positions":
            return {"positions": [dict(p) for p in self.positions]}
        if name == "trade_order_calc_margin":
            return {"ok": True, "margin": self.margin, "currency": "USD"}
        if name == "trade_order_calc_profit":
            direction = 1.0 if str(args["type"]).lower() == "buy" else -1.0
            volume = float(args["volume"])
            delta = (float(args["price_close"]) - float(args["price_open"])) * direction
            return {"ok": True, "profit": round(delta * volume * 100.0, 2)}
        if name == "trade_check_market_order":
            return {"ok": self.check_ok, "result": {"retcode": 0 if self.check_ok else 10018}}
        if name == "trade_send_market_order":
            if not self.send_ok:
                return {"ok": False, "error": {"retcode": 10018, "comment": "market closed"}}
            ticket = self.next_ticket
            self.positions.append(
                {
                    "position_id": ticket,
                    "symbol": args["symbol"],
                    "action": args["type"],
                    "volume": args["volume"],
                    "price_open": self.ask if args["type"] == "buy" else self.bid,
                    "price_last": self.ask,
                    "profit": 0.0,
                    "swaps": 0.0,
                    "contract_size": 100.0,
                    "comment": args.get("comment"),
                    "create_time": now.replace(tzinfo=None).isoformat(),
                    "update_time": now.replace(tzinfo=None).isoformat(),
                }
            )
            return {
                "ok": True,
                "result": {"order_id": ticket, "position_id": ticket, "retcode": 0},
            }
        if name == "economic_calendar_list_values":
            return {"ok": True, "values": list(self.blackout_events)}
        if name == "economic_calendar_list_countries":
            return {
                "ok": True,
                "countries": [
                    {"id": "840", "name": "United States", "country_code": "US", "currency": "USD"}
                ],
            }
        if name == "economic_calendar_list_events_by_currency":
            return {
                "ok": True,
                "events": [
                    {
                        "id": "840010001",
                        "name": "Nonfarm Payrolls",
                        "importance": "High importance",
                        "unit": "Thousand",
                        "digits": 0,
                        "sector": "Labour",
                    }
                ],
            }
        if name == "economic_calendar_get_event_by_id":
            return {
                "ok": True,
                "event": {
                    "id": args.get("event_id"),
                    "name": "Nonfarm Payrolls",
                    "importance": "High importance",
                },
            }
        if name == "get_news_list":
            return {"ok": True, "news": []}
        if name == "get_trading_history_orders":
            return {"orders": [], "deals": [], "positions": []}
        if name == "terminal_get_info":
            return {"ok": True, "terminal": {"connection": {"state": "synchronized"}}}
        if name == "add_marketwatch_symbol":
            return {"ok": True}
        if name == "remove_marketwatch_symbol":
            return {"ok": True}
        raise AssertionError(f"unexpected MCP tool {name} {args}")


class FakeForecast:
    def __init__(self) -> None:
        self.calls = 0

    def health(self) -> dict[str, Any]:
        return {"ready": True, "model": "fake-kronos", "load_s": 0.1, "threads": 2}

    def close(self) -> None:
        pass

    def forecast(self, bars, future_timestamps, samples=25, lookback=288, **_: Any):
        self.calls += 1
        last = float(bars["close"].iloc[-1])
        # 70% of paths end 8 points higher: a clean LONG under signal.v1.
        paths = np.array(
            [[last + 8.0] if i < int(samples * 0.7) else [last - 8.0] for i in range(samples)]
        )
        return paths, list(future_timestamps), {
            "model_id": "fake-kronos",
            "infer_s": 0.01,
            "samples": samples,
        }
