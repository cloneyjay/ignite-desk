"""Server-sent events: analysis progress, drafts, fills, kill switch."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from backend.ignite.api.deps import get_rt
from backend.ignite.services.runtime import Runtime

router = APIRouter(prefix="/api", tags=["events"])

HEARTBEAT_S = 10.0


@router.get("/events")
async def events(
    request: Request, rt: Runtime = Depends(get_rt)
) -> StreamingResponse:
    queue = rt.events.subscribe()

    async def stream():
        try:
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_S)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                payload = json.dumps(event, default=str)
                yield f"event: {event['type']}\ndata: {payload}\n\n"
        finally:
            rt.events.unsubscribe(queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/events/recent")
def recent(rt: Runtime = Depends(get_rt)) -> dict:
    return {"events": rt.events.recent(100), "dropped": rt.events.dropped}
