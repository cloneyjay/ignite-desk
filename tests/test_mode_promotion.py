"""Tests for mode promotion/demotion API.

Goal 5 "earned autonomy": promotion requires measured evidence that meets the
pre-committed thresholds (``PROMOTION_THRESHOLDS_V1``) — the operator confirms,
the numbers gate. Demotion never requires evidence (it only reduces risk).
"""

from __future__ import annotations

import pytest

from backend.ignite.agent.config import ExecutionMode
from backend.ignite.agent.evaluation import (
    max_drawdown_r,
    promotion_eligibility,
)
from backend.ignite.store.db import utc_now


def _seed_trade(
    rt, n: int, r_multiple: float, side: str = "buy"
) -> None:
    """Journal one closed decision→order→position→outcome chain."""
    dec_id = f"dec{n}"
    ticket = str(900000 + n)
    rt.store.insert_agent_decision({
        "id": dec_id, "created_at": utc_now(), "symbol": "XAUUSD",
        "timeframe": "M15", "analysis_id": None, "signal_side": "LONG",
        "p_up": 0.6, "edge_atr": 0.5, "decision": "LONG", "confidence": 0.7,
        "reasoning": "seeded", "executed": True, "execution_error": None,
        "draft_id": None,
    })
    rt.store.begin_order(dec_id, "XAUUSD", side, 0.01)
    rt.store.update_order(dec_id, state="filled", position_id=ticket)
    rt.store.upsert_agent_position({
        "ticket": ticket, "symbol": "XAUUSD", "side": side,
        "entry_price": 3930.0, "volume": 0.01, "opened_at": utc_now(),
        "decision_id": dec_id,
    })
    rt.store.close_agent_position(ticket, "TP", r_multiple * 30.0, r_multiple)


def _seed_qualifying_evidence(rt) -> None:
    """30 closed trades that pass PROMOTION_THRESHOLDS_V1.

    20 wins (+1.5R), 5 losses (-1.0R), 5 wins (+1.5R): sum +32.5R,
    win rate 0.833, drawdown 5R (peak 30 → trough 25).
    """
    n = 0
    for r in [1.5] * 20 + [-1.0] * 5 + [1.5] * 5:
        _seed_trade(rt, n, r)
        n += 1


def test_max_drawdown_r_peak_to_trough():
    assert max_drawdown_r([1.0, 1.0, -3.0, 5.0]) == 3.0
    assert max_drawdown_r([]) == 0.0
    assert max_drawdown_r([-1.0, -1.0]) == 2.0  # peak starts at 0


def test_promotion_eligibility_rejects_empty_desk():
    result = promotion_eligibility([], "shadow")
    assert result["eligible"] is False
    assert result["target_mode"] == "demo"
    unmet = {c["criterion"] for c in result["checks"] if not c["met"]}
    assert "min_closed_trades" in unmet


def test_promote_shadow_to_demo(client, rt):
    _seed_qualifying_evidence(rt)
    rt.config_service.update({"execution_mode": "shadow", "operating_mode": "autonomous"})
    # debug
    from backend.ignite.agent.evaluation import promotion_eligibility
    elig = promotion_eligibility(rt.store.agent_position_outcomes(limit=500), "shadow")
    print("eligibility", elig)
    resp = client.post("/api/mode/promote", json={"target": "demo", "confirm": True, "account_number": "12345"})
    if resp.status_code != 200:
        print("ERROR", resp.text)
    assert resp.status_code == 200
    assert resp.json()["mode"] == "demo"
    assert rt.config().execution_mode == "demo"
    audit = rt.store.get_audit_log()[-1]
    assert audit["action"] == "mode_promoted"
    assert audit["payload"]["from"] == "shadow"
    assert audit["payload"]["to"] == "demo"


def test_promote_demo_to_live(client, rt):
    _seed_qualifying_evidence(rt)
    rt.config_service.update({"execution_mode": "demo", "operating_mode": "autonomous"})
    resp = client.post("/api/mode/promote", json={"target": "live", "confirm": True, "account_number": "12345"})
    assert resp.status_code == 200
    assert resp.json()["mode"] == "live"
    assert rt.config().execution_mode == "live"
    audit = rt.store.get_audit_log()[-1]
    assert audit["action"] == "mode_promoted"
    assert audit["payload"]["from"] == "demo"
    assert audit["payload"]["to"] == "live"
    assert audit["payload"]["account"] == "12345"


def test_promote_blocked_without_evidence(client, rt):
    """The evidence gate fails closed: no journaled results, no promotion."""
    rt.config_service.update({"execution_mode": "shadow", "operating_mode": "autonomous"})
    resp = client.post("/api/mode/promote", json={"target": "demo", "confirm": True})
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["message"] == "promotion thresholds not met"
    assert rt.config().execution_mode == "shadow"
    audits = rt.store.get_audit_log(limit=5)
    blocked = [a for a in audits if a["action"] == "mode_promotion_blocked"]
    assert blocked and "min_closed_trades" in blocked[0]["payload"]["unmet"]


def test_promotion_eligibility_endpoint(client, rt):
    rt.config_service.update({"execution_mode": "shadow"})
    resp = client.get("/api/agent/evaluation/promotion")
    assert resp.status_code == 200
    data = resp.json()
    assert data["thresholds_version"] == "promotion.v1"
    assert data["current_mode"] == "shadow"
    assert data["target_mode"] == "demo"
    assert data["eligible"] is False
    assert {c["criterion"] for c in data["checks"]} == {
        "min_closed_trades", "min_sum_r", "min_avg_r", "min_win_rate", "max_drawdown_r",
    }


def test_promote_requires_confirmation(client, rt):
    resp = client.post("/api/mode/promote", json={"target": "live", "confirm": False, "account_number": "12345"})
    assert resp.status_code == 400


def test_promote_live_requires_account_number(client, rt):
    rt.config_service.update({"execution_mode": "demo", "operating_mode": "autonomous"})
    resp = client.post("/api/mode/promote", json={"target": "live", "confirm": True})
    assert resp.status_code == 400


def test_promote_skips_not_allowed(client, rt):
    """Cannot promote from shadow directly to live."""
    rt.config_service.update({"execution_mode": "shadow", "operating_mode": "autonomous"})
    resp = client.post("/api/mode/promote", json={"target": "live", "confirm": True, "account_number": "12345"})
    assert resp.status_code == 400


def test_demote_live_to_shadow(client, rt):
    rt.config_service.update({"execution_mode": "live", "operating_mode": "autonomous"})
    resp = client.post("/api/mode/demote", json={"confirm": True})
    assert resp.status_code == 200
    assert resp.json()["mode"] == "shadow"
    assert rt.config().execution_mode == "shadow"
    audit = rt.store.get_audit_log()[-1]
    assert audit["action"] == "mode_demoted"
    assert audit["payload"]["from"] == "live"
    assert audit["payload"]["to"] == "shadow"


def test_demote_requires_confirmation(client, rt):
    rt.config_service.update({"execution_mode": "live", "operating_mode": "autonomous"})
    resp = client.post("/api/mode/demote", json={"confirm": False})
    assert resp.status_code == 400


def test_promote_not_allowed_in_prepare_mode(client, rt):
    """Cannot promote when operating_mode is prepare."""
    rt.config_service.update({"execution_mode": "shadow", "operating_mode": "prepare"})
    resp = client.post("/api/mode/promote", json={"target": "demo", "confirm": True, "account_number": "12345"})
    assert resp.status_code == 400


def test_promote_invalid_target(client, rt):
    rt.config_service.update({"execution_mode": "shadow", "operating_mode": "autonomous"})
    resp = client.post("/api/mode/promote", json={"target": "invalid", "confirm": True, "account_number": "12345"})
    assert resp.status_code == 400