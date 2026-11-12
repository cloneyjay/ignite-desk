"""News and economic calendar.

Blackout windows are computed here from the MT5 calendar, deterministically.
No LLM is involved in deciding whether trading is allowed.

MT5 calendar/news times are trade-server wall clock. They are converted to UTC
at this boundary like every other timestamp.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from backend.ignite.market.time import Clock
from backend.ignite.mcp.client import MCPClient

IMPACT_MAP = {
    "high importance": "high",
    "medium importance": "medium",
    "low importance": "low",
}

DEFAULT_CURRENCIES = ("USD", "EUR", "CNH", "JPY")


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class NewsService:
    def __init__(
        self,
        mcp: MCPClient,
        clock: Callable[[], Clock],
        *,
        pre_minutes: int = 30,
        post_minutes: int = 15,
        currencies: tuple[str, ...] = DEFAULT_CURRENCIES,
    ) -> None:
        self._mcp = mcp
        self._clock = clock
        self.pre = timedelta(minutes=pre_minutes)
        self.post = timedelta(minutes=post_minutes)
        self.currencies = tuple(c.upper() for c in currencies)

        self._lock = threading.Lock()
        self._events: dict[str, dict[str, Any]] = {}
        self._events_ts = 0.0
        self._countries_ts = 0.0
        self._countries: dict[str, dict[str, Any]] = {}
        self._blackouts: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    # ------------------------------------------------------------------ lookups

    def _country_map(self) -> dict[str, dict[str, Any]]:
        now = time.monotonic()
        with self._lock:
            if self._countries and now - self._countries_ts < 3600:
                return self._countries
        payload = self._mcp.call_tool("economic_calendar_list_countries", {})
        mapping = {
            str(row["id"]): row
            for row in payload.get("countries") or []
            if row.get("id") is not None
        }
        with self._lock:
            self._countries = mapping
            self._countries_ts = now
        return mapping

    def _event_meta(self, event_id: str, preload: bool = True) -> dict[str, Any]:
        with self._lock:
            if event_id in self._events:
                return self._events[event_id]
        if preload:
            self._preload_events()
            with self._lock:
                if event_id in self._events:
                    return self._events[event_id]
        try:
            payload = self._mcp.call_tool(
                "economic_calendar_get_event_by_id", {"event_id": event_id}
            )
            event = payload.get("event") or {}
        except Exception:  # noqa: BLE001 - metadata is cosmetic, never fatal
            event = {}
        with self._lock:
            self._events[event_id] = event
        return event

    def _preload_events(self) -> None:
        """One call per currency beats hundreds of per-event lookups.

        The per-currency event list is also the only place that ties an event id
        to a currency: calendar *values* carry no country or currency field.
        """
        now = time.monotonic()
        with self._lock:
            if self._events_ts and now - self._events_ts < 3600:
                return
        events: dict[str, dict[str, Any]] = {}
        for code in self.currencies:
            try:
                payload = self._mcp.call_tool(
                    "economic_calendar_list_events_by_currency",
                    {"currency_code": code},
                )
            except Exception:  # noqa: BLE001
                continue
            for event in payload.get("events") or []:
                if event.get("id") is not None:
                    events[str(event["id"])] = dict(event, currency=code)
        with self._lock:
            self._events.update(events)
            self._events_ts = now

    @staticmethod
    def _impact(event: dict[str, Any], value: dict[str, Any]) -> str:
        raw = str(event.get("importance") or value.get("impact_type") or "").lower()
        return IMPACT_MAP.get(raw, "none")

    def _to_utc(self, value: str | None) -> str | None:
        if not value:
            return None
        naive = datetime.fromisoformat(value)
        return _iso(
            self._clock().server_to_utc(naive).replace(tzinfo=timezone.utc)
        )

    # ---------------------------------------------------------------- calendar

    def calendar(self, start_utc: datetime, end_utc: datetime) -> list[dict[str, Any]]:
        clock = self._clock()
        payload = self._mcp.call_tool(
            "economic_calendar_list_values",
            {
                "datetime_from": clock.utc_to_server(start_utc).strftime("%Y-%m-%dT%H:%M:%S"),
                "datetime_to": clock.utc_to_server(end_utc).strftime("%Y-%m-%dT%H:%M:%S"),
                "limit": 1000,
            },
        )
        values = payload.get("values") or []
        if values:
            self._preload_events()
        countries = self._country_map() if values else {}

        out: list[dict[str, Any]] = []
        for value in values:
            event_id = str(value.get("event_id") or "")
            event = self._event_meta(event_id, preload=False)
            currency = str(event.get("currency") or "").upper()
            # Only events that move gold; calendar values have no currency field.
            if self.currencies and currency not in self.currencies:
                continue
            if not event:
                continue
            country = countries.get(str(event.get("country_id") or ""), {})
            name = event.get("name") or value.get("name") or f"event {event_id}"
            out.append(
                {
                    "id": str(value.get("id")),
                    "event_id": event_id,
                    "time": self._to_utc(value.get("time")),
                    "currency": currency,
                    "country": country.get("name"),
                    "country_code": country.get("country_code"),
                    "name": name,
                    "impact": self._impact(event, value),
                    "actual": value.get("actual_value"),
                    "forecast": value.get("forecast_value"),
                    "previous": (
                        value.get("revised_prev_value")
                        if value.get("revised_prev_value") is not None
                        else value.get("prev_value")
                    ),
                    "unit": event.get("unit"),
                    "digits": event.get("digits"),
                    "sector": event.get("sector") or event.get("type"),
                    "time_unknown": bool(value.get("time_unknown")),
                }
            )
        out.sort(key=lambda item: item["time"] or "")
        return out

    # ---------------------------------------------------------------- blackout

    def blackouts(
        self, start_utc: datetime, end_utc: datetime, ttl_s: float = 300.0
    ) -> list[dict[str, Any]]:
        """High-impact windows for the currencies that move XAUUSD."""
        key = f"{start_utc.isoformat()}..{end_utc.isoformat()}"
        now = time.monotonic()
        with self._lock:
            cached = self._blackouts.get(key)
            if cached and now - cached[0] < ttl_s:
                return cached[1]

        try:
            events = self.calendar(start_utc - self.pre, end_utc + self.post)
        except Exception:  # noqa: BLE001 - callers decide whether this is fatal
            raise
        windows = []
        for event in events:
            if event["impact"] != "high" or not event["time"]:
                continue
            at = datetime.fromisoformat(event["time"])
            windows.append(
                {
                    "event_id": event["event_id"],
                    "name": event["name"],
                    "currency": event["currency"],
                    "impact": event["impact"],
                    "event_time": _iso(at),
                    "start": _iso(at - self.pre),
                    "end": _iso(at + self.post),
                }
            )
        windows.sort(key=lambda w: w["start"])
        with self._lock:
            self._blackouts[key] = (now, windows)
        return windows

    def blackout_at(
        self, at_utc: datetime, lookahead: timedelta = timedelta(hours=12)
    ) -> dict[str, Any] | None:
        # Bucket to the hour so the cache is actually hit during execution checks.
        anchor = at_utc.replace(minute=0, second=0, microsecond=0)
        for window in self.blackouts(anchor - self.post, anchor + lookahead):
            start = datetime.fromisoformat(window["start"])
            end = datetime.fromisoformat(window["end"])
            if start <= at_utc <= end:
                return window
        return None

    # -------------------------------------------------------------------- news

    def news(
        self, start_utc: datetime, end_utc: datetime, limit: int = 100
    ) -> list[dict[str, Any]]:
        clock = self._clock()
        payload = self._mcp.call_tool(
            "get_news_list",
            {
                "datetime_from": clock.utc_to_server(start_utc).strftime("%Y-%m-%dT%H:%M:%S"),
                "datetime_to": clock.utc_to_server(end_utc).strftime("%Y-%m-%dT%H:%M:%S"),
                "limit": max(1, min(limit, 2048)),
            },
        )
        items = []
        for row in payload.get("news") or []:
            items.append(
                {
                    "id": str(row.get("id") or row.get("news_id") or ""),
                    "time": self._to_utc(row.get("time") or row.get("datetime")),
                    "subject": row.get("subject") or row.get("title") or "(no subject)",
                    "category": row.get("category") or row.get("type"),
                    "priority": row.get("priority"),
                }
            )
        items.sort(key=lambda item: item["time"] or "", reverse=True)
        return items

    def news_body(self, news_id: str) -> dict[str, Any]:
        payload = self._mcp.call_tool("get_news_by_id", {"id": news_id})
        item = payload.get("news") or payload.get("item") or payload
        return {
            "id": news_id,
            "time": self._to_utc(item.get("time") or item.get("datetime")),
            "subject": item.get("subject") or item.get("title"),
            "category": item.get("category") or item.get("type"),
            "body": item.get("body") or item.get("text") or "",
        }
