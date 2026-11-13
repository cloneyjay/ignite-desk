"""Tests for position status lifecycle and events."""

from __future__ import annotations

import pytest

from backend.ignite.agent.position_manager import PositionManager, AgentPosition
from backend.ignite.services.reconciliation import ReconciliationService


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


def test_position_status_transitions(rt):
    # New position from gateway
    rt.store.upsert_agent_position(_create_position_dict(status="pending"))
    pos = rt.store.agent_position("12345")
    assert pos["status"] == "pending"
    
    # After protection confirmed
    rt.store.upsert_agent_position(_create_position_dict(status="protected"))
    pos = rt.store.agent_position("12345")
    assert pos["status"] == "protected"
    
    # After trailing
    rt.store.upsert_agent_position(_create_position_dict(status="trailing"))
    pos = rt.store.agent_position("12345")
    assert pos["status"] == "trailing"
    
    # After scale-out
    rt.store.upsert_agent_position(_create_position_dict(status="partial"))
    pos = rt.store.agent_position("12345")
    assert pos["status"] == "partial"
    
    # After close
    rt.store.close_agent_position("12345", "AGENT_EXIT", 45.0, 1.0)
    pos = rt.store.agent_position("12345")
    assert pos["status"] == "closed"


def test_position_opened_event_on_sync(rt):
    # When a new position is adopted from broker, it should have status="adopted"
    from tests.test_reconciliation import _create_live_position
    rt.mcp.positions_override = [_create_live_position(ticket="55555", side="buy", volume=0.01)]
    
    ReconciliationService(rt).run()
    pos = rt.store.agent_position("55555")
    assert pos is not None
    assert pos["status"] == "adopted"


def test_position_orphaned_event(rt):
    # Position in store but not in broker -> orphaned
    rt.store.upsert_agent_position(_create_position_dict(ticket="99999"))
    rt.mcp.positions_override = []
    
    ReconciliationService(rt).run()
    pos = rt.store.agent_position("99999")
    assert pos["status"] == "orphaned"


def test_position_closed_event(rt):
    # Position closed via reconciliation
    rt.store.upsert_agent_position(_create_position_dict(ticket="12345"))
    
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    rt.mcp.closed_trades_override = [
        {'position_id': '12345', 'symbol': 'XAUUSD', 'action': 'buy', 'entry': 'in', 'volume': 0.01, 'price_open': 3930.0, 'open_time': (now - timedelta(hours=2)).isoformat(), 'profit': 0.0, 'commission': 0.0, 'swap': 0.0, 'comment': 'ignite agent'},
        {'position_id': '12345', 'symbol': 'XAUUSD', 'action': 'buy', 'entry': 'out', 'volume': 0.01, 'price_open': 3940.0, 'open_time': now.isoformat(), 'profit': 45.50, 'commission': 0.0, 'swap': 0.0, 'comment': 'ignite agent'},
    ]
    
    ReconciliationService(rt).run()
    pos = rt.store.agent_position("12345")
    assert pos["status"] == "closed"


def test_position_protected_event_on_scale(rt):
    # Scale out creates partial status
    from tests.test_gateway_scale import _add_position, _create_position_dict
    rt.config_service.update({"operating_mode": "autonomous", "execution_mode": "live"})
    from tests.test_reconciliation import _create_position_dict as _create_pos
    _add_position(rt, ticket="12345", volume=0.03)
    rt.store.upsert_agent_position(_create_pos(ticket="12345", volume=0.03))
    
    result = rt.gateway.scale("12345", "reduce", 0.01, None, None)
    assert result.ok is True
    
    # Old position closed, new position with partial status
    old_pos = rt.store.agent_position("12345")
    assert old_pos["status"] == "closed"
    
    all_positions = rt.store.agent_positions(managed_only=True)
    new_pos = next((p for p in all_positions if p["status"] == "partial"), None)
    assert new_pos is not None
    assert new_pos["status"] == "partial"