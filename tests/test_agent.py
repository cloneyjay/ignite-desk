"""Agent layer: grounding, card selection, fallback, caching and the API."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.ignite.agent import run_skill
from backend.ignite.agent.validators import (
    collect_numbers,
    numeric_grounding,
    style_check,
)
from backend.ignite.api.app import create_app
from backend.ignite.config import MCPSettings, Settings
from backend.ignite.llm.client import LLMResult, LLMUnavailable
from backend.ignite.services.runtime import Runtime
from tests.fakes import FakeForecast, FakeMCP
from tests.test_execution import seed_draft

VALID = (
    "Kronos gives XAUUSD M15 a 0.80 chance of a higher close and a +0.80 ATR edge, "
    "so the rule goes LONG. The draft is 0.01 lots at 3930.13 with a 3915.13 stop "
    "and a 3960.13 target, risking 0.50% of equity for 2.00 reward-to-risk. The "
    "entry is inside the 0.30 ATR drift limit."
)

HALLUCINATED = VALID.replace("3960.13 target", "3975.00 target")


class FakeLLM:
    def __init__(self, text: str | None = VALID, error: Exception | None = None) -> None:
        self.text = text
        self.error = error
        self.calls = 0

    def complete(self, messages, **kwargs) -> LLMResult:
        self.calls += 1
        if self.error:
            raise self.error
        return LLMResult(
            text=self.text or "",
            provider="fake",
            model="fake-1",
            latency_ms=5,
            prompt_tokens=100,
            completion_tokens=40,
        )

    def available(self) -> dict[str, bool]:
        return {"nim": False, "local": True, "extra": False}

    def close(self) -> None:
        pass


def make_settings(tmp_path) -> Settings:
    return Settings(
        mcp=MCPSettings(url="http://fake", token="test-token"),
        db_path=tmp_path / "agent-test.db",
        bind_host="127.0.0.1",
        bind_port=8000,
        kronos_worker_url="http://fake",
        kronos_model="fake",
        timezone="local",
    )


@pytest.fixture()
def env(tmp_path):
    fake = FakeLLM()
    runtime = Runtime(
        make_settings(tmp_path),
        mcp_client=FakeMCP(),
        forecast_client=FakeForecast(),
        llm_client=fake,
    )
    yield runtime, fake
    runtime.shutdown()


def test_numeric_grounding_accepts_rounding_and_percentages():
    allowed = {0.44, 4.1234, 3930.46, 15.0, 0.005}
    checks = numeric_grounding(
        "p_up 0.44, ATR 4.12, price 3930.5, risk 0.50%, and 44%.",
        allowed,
    )
    assert checks["ok"], checks


def test_numeric_grounding_rejects_invented_and_sign_flipped_numbers():
    allowed = {0.33, 3930.46}
    assert not numeric_grounding("target 3975.00", allowed)["ok"]
    assert not numeric_grounding("edge -0.33 ATR", allowed)["ok"]


def test_style_check_blocks_promises_and_markdown():
    assert not style_check("This is guaranteed to work.", 50)["ok"]
    assert not style_check("## Heading\nText", 50)["ok"]
    assert style_check("The rule stays flat.", 50)["ok"]


def test_collect_numbers_walks_json_and_text():
    numbers = collect_numbers(
        {"atr": 4.1234, "reason": "p_up 0.44", "nested": [13, "0.50%"]}
    )
    assert {4.1234, 0.44, 13.0, 0.5, 0.005} <= numbers


def test_runner_returns_validated_llm_text(env):
    rt, fake = env
    analysis_id, _ = seed_draft(rt)

    out = run_skill(rt, "analysis_narrative", analysis_id)

    assert out.provider == "fake"
    assert out.fallback is False
    assert out.narrative == VALID
    assert len(out.cards) == 7
    assert {card["scope"] for card in out.cards} == {
        "risk_manager",
        "market_analyst",
        "fundamentals_desk",
    }
    assert [card["id"] for card in out.cards[:3]] == [
        "risk.drift-guard",
        "risk.position-sizing",
        "risk.stop-placement",
    ]
    stored = rt.store.agent_run(out.run_id)
    assert stored["status"] == "ok"
    assert stored["checks"]["ok"] is True
    assert stored["prompt_tokens"] == 100


def test_runner_caches_until_refresh(env):
    rt, fake = env
    analysis_id, _ = seed_draft(rt)

    first = run_skill(rt, "analysis_narrative", analysis_id)
    second = run_skill(rt, "analysis_narrative", analysis_id)
    assert second.run_id == first.run_id
    assert fake.calls == 1

    third = run_skill(rt, "analysis_narrative", analysis_id, refresh=True)
    assert third.run_id != first.run_id
    assert fake.calls == 2


def test_runner_retries_then_falls_back_on_invented_number(env):
    rt, fake = env
    analysis_id, _ = seed_draft(rt)
    fake.text = HALLUCINATED

    out = run_skill(rt, "analysis_narrative", analysis_id)

    assert fake.calls == 2
    assert out.provider == "template"
    assert out.fallback is True
    assert out.checks["ok"] is True
    assert out.checks["rejected_text"] == HALLUCINATED
    assert "0.01 lots" in out.narrative


def test_runner_falls_back_when_every_provider_fails(env):
    rt, fake = env
    analysis_id, _ = seed_draft(rt)
    fake.error = LLMUnavailable("down", ["local: connection refused"])

    out = run_skill(rt, "analysis_narrative", analysis_id)

    assert fake.calls == 1
    assert out.provider == "template"
    assert out.fallback is True
    assert "connection refused" in (out.error or "")


def test_narrative_endpoint_and_run_log(tmp_path):
    runtime = Runtime(
        make_settings(tmp_path),
        mcp_client=FakeMCP(),
        forecast_client=FakeForecast(),
        llm_client=FakeLLM(),
    )
    analysis_id, _ = seed_draft(runtime)
    app = create_app(runtime=runtime)
    with TestClient(app) as client:
        missing = client.get(f"/api/analyses/{analysis_id}/narrative")
        assert missing.status_code == 200
        body = missing.json()
        assert body["status"] == "not_generated"
        assert body["narrative"] is None
        assert body["error"] is not None

        created = client.post(
            f"/api/analyses/{analysis_id}/narrative", json={"refresh": False}
        )
        assert created.status_code == 200, created.text
        body = created.json()
        assert body["provider"] == "fake"
        assert body["analysis_id"] == analysis_id
        assert body["fallback"] is False

        cached = client.get(f"/api/analyses/{analysis_id}/narrative")
        assert cached.status_code == 200
        assert cached.json()["run_id"] == body["run_id"]

        runs = client.get("/api/agent/runs").json()
        assert runs["count"] == 1
        assert runs["runs"][0]["cards"][0] == "risk.drift-guard"

        knowledge = client.get("/api/knowledge/status").json()
        assert knowledge["ok"] is True
        assert knowledge["cards"] >= 13
        assert knowledge["reviewed"] >= 13

        health = client.get("/api/health").json()
        assert health["llm"]["local"] is True
        assert health["knowledge"]["cards"] >= 13
