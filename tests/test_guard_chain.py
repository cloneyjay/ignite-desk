"""Tests for hardened guard chain in gateway."""

from __future__ import annotations

import pytest

from backend.ignite.services.gateway import OrderRequest


def _add_position(rt, ticket="12345", symbol="XAUUSD", side="buy", volume=0.01, sl=3920.0, tp=3950.0):
    rt.mcp.positions.append({
        "position_id": ticket,
        "symbol": symbol,
        "action": side,
        "volume": volume,
        "price_open": 3930.0,
        "price_last": 3930.0,
        "sl": sl,
        "tp": tp,
        "comment": "ignite agent",
        "create_time": "2026-01-01T00:00:00",
        "update_time": "2026-01-01T00:00:00",
    })


def test_guard_chain_order(rt):
    """Guards evaluated in correct order: kill_switch -> mode -> watchlist -> spec -> spread -> news -> daily_loss -> exposure -> margin -> lots -> stops."""
    rt.config_service.update({"operating_mode": "autonomous", "execution_mode": "live"})
    rt.realised_override = -700.0  # Triggers daily loss
    req = OrderRequest("XAUUSD", "buy", 0.01, 3920.0, 3950.0, "d1")
    result = rt.gateway.validate(req)
    # Daily loss should be checked AFTER spread/news but BEFORE exposure/margin
    assert result.code == "DAILY_LOSS"


def test_shadow_mode_rejection(rt):
    rt.config_service.update({"operating_mode": "autonomous", "execution_mode": "shadow"})
    req = OrderRequest("XAUUSD", "buy", 0.01, 3920.0, 3950.0, "d1")
    result = rt.gateway.validate(req)
    assert result.code == "SHADOW_MODE"


def test_kill_switch_blocks_risk_increase_only(rt):
    _add_position(rt, ticket="12345")
    rt.store.set_kill_switch(True)
    # Close should still work (reduces risk)
    result = rt.gateway.close("12345", "MANUAL")
    assert result.ok is True
    # Place should fail
    req = OrderRequest("XAUUSD", "buy", 0.01, 3920.0, 3950.0, "d1")
    assert rt.gateway.validate(req).code == "KILL_SWITCH"


def test_kill_switch_blocks_modify_that_increases_risk(rt):
    _add_position(rt, ticket="12345", side="buy", sl=3920.0, tp=3950.0)
    rt.store.set_kill_switch(True)
    # Modify that tightens SL (reduces risk) should work
    result = rt.gateway.modify("12345", sl=3925.0, tp=3950.0)
    assert result.code == "OK"
    # Modify that widens SL (increases risk) should fail
    result = rt.gateway.modify("12345", sl=3915.0, tp=3950.0)
    assert result.code == "KILL_SWITCH"


def test_mode_not_autonomous_blocks(rt):
    rt.config_service.update({"operating_mode": "prepare", "execution_mode": "live"})
    req = OrderRequest("XAUUSD", "buy", 0.01, 3920.0, 3950.0, "d1")
    result = rt.gateway.validate(req)
    assert result.code == "MODE"


def test_watchlist_blocks_unknown_symbol(rt):
    rt.config_service.update({"operating_mode": "autonomous", "execution_mode": "live"})
    req = OrderRequest("UNKNOWNSYM", "buy", 0.01, 3920.0, 3950.0, "d1")
    result = rt.gateway.validate(req)
    assert result.code == "NOT_WATCHED"