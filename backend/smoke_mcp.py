"""P1 smoke test: prove the MCP client works against the live terminal.

Run from the repo root:
  .\\.venv\\Scripts\\python.exe -m backend.smoke_mcp
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from backend.ignite.config import load_settings
from backend.ignite.mcp.client import MCPClient


def main() -> None:
    settings = load_settings()
    with MCPClient(settings.mcp.url, settings.mcp.headers, settings.mcp.timeout_s) as mcp:
        info = mcp.initialize()
        print("server:", json.dumps(info.get("serverInfo", {}), ensure_ascii=False))

        tools = mcp.list_tools()
        names = sorted(t["name"] for t in tools)
        print(f"tools: {len(names)}")
        print("  ", ", ".join(names[:8]), "...")

        account = mcp.call_tool("get_trading_account_info")
        acc = account.get("account", {})
        print("account:", acc.get("server"), acc.get("login"), acc.get("currency"),
              acc.get("balance"), "equity", acc.get("equity"))

        clock = mcp.call_tool("get_time_information")
        print("time:", json.dumps(clock, ensure_ascii=False)[:400])

        now = datetime.now(timezone.utc)
        bars = mcp.call_tool(
            "get_chart_history",
            {
                "symbol": "XAUUSD",
                "period": "M15",
                "datetime_from": (now - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S"),
                "datetime_to": now.strftime("%Y-%m-%dT%H:%M:%S"),
                "limit": 5,
            },
        )
        print("bars_ok:", bars.get("ok"), "count:", len(bars.get("history", [])))
        for row in bars.get("history", [])[:2]:
            print("  ", row)

        ticks = mcp.call_tool(
            "get_chart_ticks_history",
            {
                "symbol": "XAUUSD",
                "datetime_from": (now - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S"),
                "datetime_to": now.strftime("%Y-%m-%dT%H:%M:%S"),
                "limit": 5,
            },
        )
        print("ticks:", json.dumps(ticks, ensure_ascii=False)[:400])


if __name__ == "__main__":
    main()
