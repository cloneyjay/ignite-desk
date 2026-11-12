"""Clock handling: MT5 speaks trade-server time, we store UTC.

The offset is derived from `get_time_information` (server last-known time minus
UTC time), rounded to 15 minutes. It is re-read periodically because server DST
changes twice a year.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from backend.ignite.mcp.client import MCPClient

ROUND = timedelta(minutes=15)


def parse_dt(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


@dataclass(frozen=True)
class Clock:
    offset: timedelta
    utc_at_read: datetime

    @classmethod
    def from_mcp(cls, mcp: MCPClient) -> "Clock":
        info = mcp.call_tool("get_time_information")
        utc = parse_dt(info["utc_time"])
        if utc.tzinfo is None:
            utc = utc.replace(tzinfo=timezone.utc)
        server_raw = info.get("trade_server_last_known_time")
        if not server_raw:
            raise RuntimeError("terminal did not report trade server time")
        server = parse_dt(server_raw)
        if server.tzinfo is None:
            server = server.replace(tzinfo=timezone.utc)

        raw = server - utc
        rounded_minutes = round(raw.total_seconds() / ROUND.total_seconds()) * 15
        return cls(offset=timedelta(minutes=rounded_minutes), utc_at_read=utc)

    def server_now(self) -> datetime:
        """Trade-server wall clock, naive."""
        return (datetime.now(timezone.utc) + self.offset).replace(tzinfo=None)

    def server_to_utc(self, naive_server: datetime) -> datetime:
        return naive_server - self.offset

    def utc_to_server(self, utc: datetime) -> datetime:
        if utc.tzinfo is not None:
            utc = utc.astimezone(timezone.utc).replace(tzinfo=None)
        return utc + self.offset
