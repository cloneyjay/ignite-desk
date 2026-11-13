"""Tests for broker reconciliation service."""

from __future__ import annotations

import pytest

from backend.ignite.services.reconciliation import ReconciliationService, ReconciliationResult
from backend.ignite.agent.position_manager import AgentPosition


def _create_position_dict(ticket="12345", symbol="XAUUSD", side="BUY", entry=3930.0, volume=0.01, sl=3920.0, tp=3950.0, status="open"):
    return {
        "ticket": ticket,
        "symbol": symbol,
        "side": side,
        "entry_price": entry,
        "volume": volume,
        "sl": sl,
        "tp": tp,
        "opened_at": "2026-01-01T00:00:00Z",
        "managed_by_agent": 1,
        "trail_sl": sl,
        "scale_in_count": 0,
        "scale_out_count": 0,
        "max_favourable_atr": 0.0,
        "max_adverse_atr": 0.0,
        "last_managed_at": "2026-01-01T00:00:00Z",
        "closed_at": None,
        "close_reason": None,
        "realised_pnl": None,
        "r_multiple": None,
        "status": status,
    }


def _create_live_position(ticket="12345", symbol="XAUUSD", side="buy", volume=0.01):
    return {
        "position_id": ticket,
        "symbol": symbol,
        "action": side,
        "volume": volume,
        "price_open": 3930.0,
        "price_last": 3930.0,
        "sl": 3920.0,
        "tp": 3950.0,
        "comment": "ignite agent",
        "create_time": "2026-01-01T00:00:00",
        "update_time": "2026-01-01T00:00:00",
    }


def test_reconcile_broker_closed_position(rt):
    # Position in store, closed in broker
    rt.store.upsert_agent_position(_create_position_dict(ticket="12345"))
    
    # Broker deal history shows closed trade (properly formatted as deals)
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    rt.mcp.closed_trades_override = [
        # Entry deal (in)
        {
            "position_id": "12345",
            "symbol": "XAUUSD",
            "action": "buy",
            "entry": "in",
            "volume": 0.01,
            "price_open": 3930.0,
            "open_time": (now - timedelta(hours=2)).isoformat(),
            "profit": 0.0,
            "commission": 0.0,
            "swap": 0.0,
            "comment": "ignite agent",
        },
        # Exit deal (out)
        {
            "position_id": "12345",
            "symbol": "XAUUSD",
            "action": "buy",
            "entry": "out",
            "volume": 0.01,
            "price_open": 3940.0,
            "open_time": now.isoformat(),
            "profit": 45.50,
            "commission": 0.0,
            "swap": 0.0,
            "comment": "ignite agent",
        },
    ]
    
    result = ReconciliationService(rt).run()
    pos = rt.store.agent_position("12345")
    
    assert pos["status"] == "closed"
    assert pos["realised_pnl"] == 45.50
    # Risk = (3930 - 3920) * 0.01 * 100 = 10 USD
    # R = 45.50 / 10 = 4.55
    assert abs(pos["r_multiple"] - 4.55) < 0.01


def test_reconcile_orphan_position(rt):
    # Position in store but not in broker
    rt.store.upsert_agent_position(_create_position_dict(ticket="99999"))
    rt.mcp.positions_override = []  # No positions in broker
    
    result = ReconciliationService(rt).run()
    pos = rt.store.agent_position("99999")
    
    assert pos["status"] == "orphaned"


def test_reconcile_adopts_ignite_position_from_broker(rt):
    # Position exists in broker with "ignite" comment but not in store
    rt.mcp.positions_override = [_create_live_position(ticket="55555", side="buy", volume=0.01)]
    
    result = ReconciliationService(rt).run()
    pos = rt.store.agent_position("55555")
    
    assert pos is not None
    assert pos["status"] == "adopted"
    assert pos["symbol"] == "XAUUSD"
    assert pos["volume"] == 0.01


def test_reconcile_updates_live_position_sl_tp(rt):
    # Position in store with old SL/TP, broker has updated SL/TP
    rt.store.upsert_agent_position(_create_position_dict(ticket="12345", sl=3920.0, tp=3950.0))
    rt.mcp.positions_override = [_create_live_position(ticket="12345", side="buy", volume=0.01)]
    # Override with new SL/TP
    rt.mcp.positions_override[0]["sl"] = 3925.0
    rt.mcp.positions_override[0]["tp"] = 3955.0
    
    result = ReconciliationService(rt).run()
    pos = rt.store.agent_position("12345")
    
    assert pos["sl"] == 3925.0
    assert pos["tp"] == 3955.0
    assert pos["last_synced_at"] is not None