"""Economic calendar, blackout windows and terminal news."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query

from backend.ignite.api.deps import get_rt
from backend.ignite.api.errors import ApiError
from backend.ignite.api.serializers import iso
from backend.ignite.services.runtime import Runtime

router = APIRouter(prefix="/api", tags=["news"])

IMPACTS = {"high", "medium", "low", "none"}


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


def _window(from_: str | None, to: str | None, days: int) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    start = _parse(from_, now - timedelta(hours=2))
    end = _parse(to, now + timedelta(days=days))
    if start >= end:
        raise ApiError(400, "bad_range", "from must be earlier than to")
    return start, end


@router.get("/calendar")
def calendar(
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    impact: str | None = Query(None),
    currency: str | None = Query(None),
    rt: Runtime = Depends(get_rt),
) -> dict[str, Any]:
    start, end = _window(from_, to, 7)
    try:
        events = rt.news.calendar(start, end)
    except Exception as exc:  # noqa: BLE001
        raise ApiError(503, "calendar_unavailable", str(exc)) from exc

    if impact:
        wanted = {part.strip().lower() for part in impact.split(",") if part.strip()}
        if not wanted <= IMPACTS:
            raise ApiError(400, "bad_impact", f"impact must be within {sorted(IMPACTS)}")
        events = [event for event in events if event["impact"] in wanted]
    if currency:
        wanted_ccy = {part.strip().upper() for part in currency.split(",") if part.strip()}
        events = [event for event in events if event["currency"] in wanted_ccy]
    return {"from": iso(start), "to": iso(end), "events": events}


@router.get("/blackouts")
def blackouts(
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    rt: Runtime = Depends(get_rt),
) -> dict[str, Any]:
    start, end = _window(from_, to, 2)
    try:
        windows = rt.news.blackouts(start, end)
    except Exception as exc:  # noqa: BLE001
        raise ApiError(503, "calendar_unavailable", str(exc)) from exc
    return {
        "from": iso(start),
        "to": iso(end),
        "pre_minutes": rt.news.pre.seconds // 60,
        "post_minutes": rt.news.post.seconds // 60,
        "blackouts": windows,
    }


@router.get("/news")
def news(
    limit: int = Query(50, ge=1, le=500),
    hours: int = Query(48, ge=1, le=720),
    rt: Runtime = Depends(get_rt),
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    try:
        items = rt.news.news(now - timedelta(hours=hours), now + timedelta(minutes=5), limit)
    except Exception as exc:  # noqa: BLE001
        raise ApiError(503, "news_unavailable", str(exc)) from exc
    return {"news": items, "count": len(items)}


@router.get("/news/{news_id}")
def news_item(news_id: str, rt: Runtime = Depends(get_rt)) -> dict[str, Any]:
    try:
        return rt.news.news_body(news_id)
    except Exception as exc:  # noqa: BLE001
        raise ApiError(503, "news_unavailable", str(exc)) from exc
