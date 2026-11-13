"""Shared runtime/client fixtures for the agent API and gateway suites."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.ignite.api.app import create_app
from backend.ignite.config import MCPSettings, Settings
from backend.ignite.services.runtime import Runtime
from tests.fakes import FakeForecast, FakeMCP


def build_runtime(tmp_path) -> Runtime:
    settings = Settings(
        mcp=MCPSettings(url="http://fake", token="test-token"),
        db_path=tmp_path / "ignite.db",
        bind_host="127.0.0.1",
        bind_port=8000,
        kronos_worker_url="http://fake",
        kronos_model="fake",
        timezone="local",
    )
    return Runtime(settings, mcp_client=FakeMCP(), forecast_client=FakeForecast())


@pytest.fixture()
def runtime(tmp_path):
    rt = build_runtime(tmp_path)
    rt.realised_override = None
    original = rt.realised_today

    def realised_today():
        if rt.realised_override is not None:
            return {"realised_usd": rt.realised_override}
        return original()

    rt.realised_today = realised_today  # type: ignore[method-assign]
    rt.seed_symbols()
    rt.config_service.update({"operating_mode": "autonomous"})
    yield rt


@pytest.fixture()
def rt(runtime):
    return runtime


@pytest.fixture()
def client(runtime):
    app = create_app(runtime=runtime)
    with TestClient(app) as test_client:
        yield test_client
