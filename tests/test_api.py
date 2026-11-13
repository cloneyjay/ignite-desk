"""HTTP surface: confirmation flow, error envelopes, read endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.ignite.api.app import create_app
from backend.ignite.config import MCPSettings, Settings
from backend.ignite.services.runtime import Runtime
from tests.fakes import FakeForecast, FakeMCP
from tests.test_execution import seed_draft


@pytest.fixture()
def env(tmp_path):
    settings = Settings(
        mcp=MCPSettings(url="http://fake", token="test-token"),
        db_path=tmp_path / "api-test.db",
        bind_host="127.0.0.1",
        bind_port=8000,
        kronos_worker_url="http://fake",
        kronos_model="fake",
        timezone="local",
    )
    runtime = Runtime(settings, mcp_client=FakeMCP(), forecast_client=FakeForecast())
    app = create_app(runtime=runtime)
    with TestClient(app) as client:
        yield client, runtime


def test_health_reports_both_sides(env):
    client, _ = env
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["mcp"]["reachable"] is True
    assert body["kronos"]["ready"] is True
    assert body["ok"] is True
    assert body["kill_switch"] is False


def test_account_and_settings(env):
    client, _ = env
    account = client.get("/api/account").json()
    assert account["account"]["equity"] == 3000.0
    assert account["risk"]["cap_pct"] == pytest.approx(0.02)

    settings = client.get("/api/settings").json()
    assert settings["draft_ttl_s"] == 90
    assert "M15" in settings["timeframes"]


def test_risk_above_cap_is_refused(env):
    client, _ = env
    response = client.put("/api/settings", json={"risk_pct": 0.05})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "risk_pct_above_cap"


def test_confirm_then_execute_over_http(env):
    client, runtime = env
    _, draft_id = seed_draft(runtime)

    detail = client.get(f"/api/drafts/{draft_id}")
    assert detail.status_code == 200
    assert detail.json()["draft"]["executable"] is True

    confirmed = client.post(f"/api/drafts/{draft_id}/confirm", json={"confirm": True})
    assert confirmed.status_code == 200, confirmed.text
    token = confirmed.json()["token"]

    executed = client.post(
        f"/api/drafts/{draft_id}/execute", json={"confirm": True, "token": token}
    )
    assert executed.status_code == 200, executed.text
    assert executed.json()["state"] == "filled"

    again = client.post(
        f"/api/drafts/{draft_id}/execute", json={"confirm": True, "token": token}
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "draft_state"


def test_execute_without_confirm_is_a_clean_400(env):
    client, runtime = env
    _, draft_id = seed_draft(runtime)
    response = client.post(f"/api/drafts/{draft_id}/execute", json={"confirm": False})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "confirm_required"


def test_missing_draft_is_a_clean_404(env):
    client, _ = env
    response = client.post(
        "/api/drafts/nope/execute", json={"confirm": True, "token": "x"}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "draft_not_found"


def test_kill_switch_over_http(env):
    client, _ = env
    response = client.put("/api/settings", json={"kill_switch": True})
    assert response.status_code == 200
    assert response.json()["kill_switch"] is True
    events = client.get("/api/events/recent").json()["events"]
    assert any(event["type"] == "kill_switch" for event in events)


def test_latest_analysis_404_is_explicit(env):
    client, _ = env
    response = client.get("/api/analyses/latest?symbol=XAUUSD&tf=M15")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "no_analysis"
