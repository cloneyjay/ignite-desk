"""Execution guards, confirmation tokens and idempotency, against a fake broker."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from backend.ignite.analysis.risk import SymbolSpec, plan
from backend.ignite.config import MCPSettings, Settings
from backend.ignite.services.execution import (
    ExecutionError,
    evaluate_draft,
    execute_draft,
)
from backend.ignite.services.runtime import Runtime
from backend.ignite.store.db import utc_now
from tests.fakes import FakeForecast, FakeMCP

XAU = SymbolSpec(
    symbol="XAUUSD",
    digits=2,
    point=0.01,
    contract_size=100.0,
    tick_value=0.1,
    volume_min=0.01,
    volume_max=100.0,
    volume_step=0.01,
    stops_level=0,
)


@pytest.fixture()
def rt(tmp_path):
    settings = Settings(
        mcp=MCPSettings(url="http://fake", token="test-token"),
        db_path=tmp_path / "ignite-test.db",
        bind_host="127.0.0.1",
        bind_port=8000,
        kronos_worker_url="http://fake",
        kronos_model="fake",
        timezone="local",
    )
    runtime = Runtime(settings, mcp_client=FakeMCP(), forecast_client=FakeForecast())
    yield runtime
    runtime.shutdown()


def seed_draft(
    rt: Runtime,
    *,
    side: str = "long",
    reference: float = 3930.13,
    atr: float = 10.0,
    ttl_s: int = 90,
    blocked: bool = False,
) -> tuple[str, str]:
    draft = plan(side, reference, atr, 3000.0, XAU, 13.0)
    draft = replace(
        draft,
        margin=7.82,
        worst_case_usd=round(-draft.risk_usd, 2),
        blocked=blocked,
        block_reason="test block" if blocked else None,
    )
    signal = SimpleNamespace(
        side=side,
        p_up=0.8,
        edge=8.0,
        edge_atr=0.8,
        dispersion=1.0,
        reasons=("test",),
        version="signal.v1",
    )
    features = SimpleNamespace(
        atr=atr,
        last_close=3930.0,
        last_time="2026-11-12 08:30:00",
        ema_fast=3931.0,
        ema_slow=3925.0,
        realized_vol_pct=0.1,
        spread_points=13.0,
        trend="up",
    )
    result = SimpleNamespace(
        analysis_id=f"a{ttl_s}{side}"[:32].ljust(32, "0"),
        draft_id=f"d{ttl_s}{side}"[:32].ljust(32, "0"),
        created_at=utc_now(),
        symbol="XAUUSD",
        timeframe="M15",
        last_bar_time="2026-11-12 08:30:00",
        lookback=288,
        horizon=12,
        samples=25,
        model_id="fake-kronos",
        infer_s=0.1,
        features=features,
        signal=signal,
        paths=np.zeros((2, 2)),
        draft=draft,
        risk_version="risk.v1",
    )
    rt.store.save_analysis(result, ttl_s)
    return result.analysis_id, result.draft_id


def token_for(rt: Runtime, draft_id: str) -> str:
    draft = rt.store.get_draft(draft_id)
    assert draft is not None
    return rt.issue_token(draft_id, draft["expires_at"])


def test_happy_path_fills_and_records_the_order(rt):
    _, draft_id = seed_draft(rt)
    fake: FakeMCP = rt.mcp

    evaluation = evaluate_draft(rt, rt.store.get_draft(draft_id))
    assert evaluation["executable"] is True, evaluation["checks"]

    token = token_for(rt, draft_id)
    result = execute_draft(rt, draft_id, confirm=True, token=token)

    assert result["state"] == "filled"
    assert result["confirmed"] is True
    assert result["position"]["ticket"] == "900001"
    assert result["order"]["state"] == "filled"
    assert float(result["order"]["filled_price"]) == pytest.approx(3930.13)

    sent = fake.called("trade_send_market_order")
    assert len(sent) == 1
    assert sent[0]["sl"] and sent[0]["tp"]
    assert sent[0]["symbol"] == "XAUUSD"
    assert rt.store.get_draft(draft_id)["state"] == "filled"


def test_token_is_required(rt):
    _, draft_id = seed_draft(rt)
    with pytest.raises(ExecutionError) as exc:
        execute_draft(rt, draft_id, confirm=True, token=None)
    assert exc.value.status == 403
    assert exc.value.code == "token_invalid"
    assert not rt.mcp.called("trade_send_market_order")


def test_confirmation_is_required(rt):
    _, draft_id = seed_draft(rt)
    with pytest.raises(ExecutionError) as exc:
        execute_draft(rt, draft_id, confirm=False, token=token_for(rt, draft_id))
    assert exc.value.status == 400
    assert exc.value.code == "confirm_required"


def test_token_is_single_use(rt):
    _, draft_id = seed_draft(rt)
    token = token_for(rt, draft_id)
    execute_draft(rt, draft_id, confirm=True, token=token)
    with pytest.raises(ExecutionError) as exc:
        execute_draft(rt, draft_id, confirm=True, token=token)
    assert exc.value.status == 409
    assert exc.value.code == "draft_state"
    assert len(rt.mcp.called("trade_send_market_order")) == 1


def test_token_is_burned_even_when_a_guard_rejects(rt):
    _, draft_id = seed_draft(rt)
    token = token_for(rt, draft_id)
    rt.mcp.ask = 3935.0  # drift guard fires before the broker is touched
    with pytest.raises(ExecutionError) as first:
        execute_draft(rt, draft_id, confirm=True, token=token)
    assert first.value.code == "price_drift"
    with pytest.raises(ExecutionError) as second:
        execute_draft(rt, draft_id, confirm=True, token=token)
    assert second.value.code == "token_invalid"


def test_token_is_bound_to_its_draft(rt):
    _, first = seed_draft(rt, side="long")
    _, second = seed_draft(rt, side="short", reference=3929.87)
    with pytest.raises(ExecutionError) as exc:
        execute_draft(rt, second, confirm=True, token=token_for(rt, first))
    assert exc.value.code == "token_invalid"


def test_price_drift_blocks_execution(rt):
    _, draft_id = seed_draft(rt)
    rt.mcp.ask = 3935.0  # 0.49 ATR away from the 3930.13 reference
    with pytest.raises(ExecutionError) as exc:
        execute_draft(rt, draft_id, confirm=True, token=token_for(rt, draft_id))
    assert exc.value.status == 409
    assert exc.value.code == "price_drift"
    assert not rt.mcp.called("trade_send_market_order")


def test_open_position_on_symbol_blocks_a_second_entry(rt):
    _, draft_id = seed_draft(rt)
    rt.mcp.positions = [
        {
            "position_id": "111",
            "symbol": "XAUUSD",
            "action": "buy",
            "volume": 0.01,
            "price_open": 3900.0,
            "price_last": 3930.0,
            "profit": 30.0,
            "swaps": 0.0,
            "contract_size": 100.0,
            "create_time": "2026-11-12 07:00:00",
            "update_time": "2026-11-12 07:00:00",
        }
    ]
    with pytest.raises(ExecutionError) as exc:
        execute_draft(rt, draft_id, confirm=True, token=token_for(rt, draft_id))
    assert exc.value.code == "no_open_position"


def test_expired_draft_is_rejected(rt):
    _, draft_id = seed_draft(rt, ttl_s=0)
    with pytest.raises(ExecutionError) as exc:
        execute_draft(rt, draft_id, confirm=True, token=token_for(rt, draft_id))
    assert exc.value.code == "expired"


def test_blocked_draft_is_rejected(rt):
    _, draft_id = seed_draft(rt, blocked=True)
    with pytest.raises(ExecutionError) as exc:
        execute_draft(rt, draft_id, confirm=True, token=token_for(rt, draft_id))
    assert exc.value.code == "not_blocked"


def test_kill_switch_blocks_and_persists(rt):
    _, draft_id = seed_draft(rt)
    token = token_for(rt, draft_id)
    rt.set_kill_switch(True)
    with pytest.raises(ExecutionError) as exc:
        execute_draft(rt, draft_id, confirm=True, token=token)
    assert exc.value.code == "kill_switch"
    assert rt.store.kill_switch() is True

    rt.set_kill_switch(False)
    result = execute_draft(
        rt, draft_id, confirm=True, token=token_for(rt, draft_id)
    )
    assert result["state"] == "filled"


def test_broker_rejection_is_recorded_not_retried(rt):
    _, draft_id = seed_draft(rt)
    rt.mcp.send_ok = False
    with pytest.raises(ExecutionError) as exc:
        execute_draft(rt, draft_id, confirm=True, token=token_for(rt, draft_id))
    assert exc.value.status == 502
    assert exc.value.code == "order_rejected"
    assert rt.store.get_draft(draft_id)["state"] == "failed"
    orders = rt.store.orders_for_draft(draft_id)
    assert len(orders) == 1
    assert orders[0]["state"] == "failed"
    assert "market closed" in orders[0]["error"]
    assert len(rt.mcp.called("trade_send_market_order")) == 1


def test_order_is_never_sent_without_stops(rt):
    from backend.ignite.services.broker import send_market_order

    with pytest.raises(Exception):
        send_market_order(rt.mcp, "XAUUSD", "buy", 0.01, 0.0, 0.0, "test")
    assert not rt.mcp.called("trade_send_market_order")
