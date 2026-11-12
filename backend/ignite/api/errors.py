"""Error types and JSON error envelopes for the API."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.ignite.forecasting.client import ForecastError
from backend.ignite.services.analysis_service import AnalysisError
from backend.ignite.services.broker import BrokerError
from backend.ignite.services.execution import ExecutionError

log = logging.getLogger("ignite.api")


class ApiError(Exception):
    def __init__(
        self, status: int, code: str, message: str, detail: Any = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail


def envelope(code: str, message: str, detail: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if detail is not None:
        body["error"]["detail"] = detail
    return body


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content=envelope(exc.code, exc.message, exc.detail),
        )

    @app.exception_handler(ExecutionError)
    async def _execution_error(request: Request, exc: ExecutionError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content=envelope(exc.code, exc.message, exc.detail),
        )

    @app.exception_handler(BrokerError)
    async def _broker_error(request: Request, exc: BrokerError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content=envelope(
                "broker_unavailable",
                str(exc),
                {"hint": "is the MT5 terminal running with the MCP server on :22346?"},
            ),
        )

    @app.exception_handler(ForecastError)
    async def _forecast_error(request: Request, exc: ForecastError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content=envelope(
                "kronos_unavailable",
                str(exc),
                {"hint": "start the worker: python -m backend.ignite.forecasting.worker"},
            ),
        )

    @app.exception_handler(AnalysisError)
    async def _analysis_error(request: Request, exc: AnalysisError) -> JSONResponse:
        return JSONResponse(
            status_code=400, content=envelope("invalid_request", str(exc))
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500, content=envelope("internal_error", str(exc))
        )
