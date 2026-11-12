"""FastAPI dependencies."""

from __future__ import annotations

from fastapi import Request

from backend.ignite.services.runtime import Runtime


def get_rt(request: Request) -> Runtime:
    return request.app.state.runtime
