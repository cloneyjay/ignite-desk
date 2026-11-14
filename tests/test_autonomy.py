"""Tests for autonomy graduation and policy engine."""

from __future__ import annotations

import pytest
import tempfile
import os
import atexit
from pathlib import Path

from backend.ignite.agent.policy.autonomy import AutonomyEngine
from backend.ignite.agent.policy.policy_engine import PolicyEngine, PolicyValidationResult
from backend.ignite.agent.config import AgentConfig
from backend.ignite.services.runtime import Runtime
from backend.ignite.config import Settings, MCPSettings
from tests.fakes import FakeMCP, FakeForecast
from pathlib import Path


# Global temp directory for test database
TEST_DB_DIR = tempfile.mkdtemp()
TEST_DB_PATH = Path(TEST_DB_DIR) / "test_autonomy.db"

def cleanup_test_db():
    """Cleanup test database on exit."""
    try:
        if os.path.exists(TEST_DB_PATH):
            os.unlink(TEST_DB_PATH)
        os.rmdir(TEST_DB_DIR)
    except:
        pass

atexit.register(cleanup_test_db)


def create_test_runtime():
    """Create a minimal test runtime with fake dependencies."""
    settings = Settings(
        mcp=MCPSettings(url="http://fake", token="test-token"),
        db_path=TEST_DB_PATH,
        bind_host="127.0.0.1",
        bind_port=8000,
        kronos_worker_url="http://fake",
        kronos_model="fake",
        timezone="local",
    )
    rt = Runtime(
        settings,
        mcp_client=FakeMCP(),
        forecast_client=FakeForecast(),
    )
    rt.seed_symbols()
    rt.config_service.update({"enabled": True, "operating_mode": "autonomous", "execution_mode": "live"})
    return rt


def test_autonomy_levels(rt):
    rt.config_service.update({"autonomy_level": 2, "operating_mode": "autonomous", "execution_mode": "live"})
    tools = rt.tool_registry.get_available("autonomous", False, 2)
    execute_tools = [t for t in tools if t.permission == "execute"]
    assert any(t.name == "execution.place_order" for t in execute_tools)
    
    # Level 0 should not have execute tools
    rt.config_service.update({"autonomy_level": 0})
    tools = rt.tool_registry.get_available("autonomous", False, 0)
    execute_tools = [t for t in tools if t.permission == "execute"]
    assert not any(t.name == "execution.place_order" for t in execute_tools)


def test_policy_enforcement(rt):
    rt.config_service.update({"autonomy_level": 3, "operating_mode": "autonomous", "execution_mode": "live"})
    pe = PolicyEngine(rt)
    # Load a test policy with forbidden symbols
    import tempfile
    import json
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump({"forbidden_symbols": ["BTCUSD"]}, f)
        policy_path = f.name
    try:
        rt.config_service.update({"policy_path": policy_path})
        pe.load_policy(policy_path)
        
        # Test forbidden symbol
        result = pe.validate({"symbol": "BTCUSD", "size": 1.0, "leverage": 20})
        assert not result.ok
        assert "forbidden" in result.error.lower()
    finally:
        os.unlink(policy_path)


def test_policy_drawdown_limit(rt):
    rt.config_service.update({"autonomy_level": 3, "operating_mode": "autonomous", "execution_mode": "live"})
    pe = PolicyEngine(rt)
    # Load a test policy with daily loss limit
    import tempfile
    import json
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump({"daily_loss_limit_pct": 0.05}, f)
        policy_path = f.name
    try:
        pe.load_policy(policy_path)
        rt.realised_override = -600.0  # Simulate 6% loss on 10k equity
        
        result = pe.validate({"symbol": "XAUUSD", "size": 0.1, "leverage": 10})
        assert not result.ok
        assert "drawdown" in result.error.lower() or "loss" in result.error.lower()
    finally:
        os.unlink(policy_path)


def test_autonomy_level_gating(rt):
    rt.config_service.update({"autonomy_level": 1, "operating_mode": "autonomous"})
    tools = rt.tool_registry.get_available("autonomous", False, 1)
    # Level 1 should not have execute tools
    execute_tools = [t for t in tools if t.permission == "execute"]
    assert len(execute_tools) == 0
    
    rt.config_service.update({"autonomy_level": 2})
    tools = rt.tool_registry.get_available("autonomous", False, 2)
    execute_tools = [t for t in tools if t.permission == "execute"]
    assert any(t.name == "execution.place_order" for t in execute_tools)