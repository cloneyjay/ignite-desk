"""Tests for dynamic risk intelligence module."""

from __future__ import annotations

import pytest
import tempfile
import os
import atexit
from pathlib import Path

from backend.ignite.agent.intelligence.risk_intel import RiskIntel, RiskDecomposition, DynamicSizing, AdaptiveExit, CorrelationHedge
from backend.ignite.services.runtime import Runtime
from backend.ignite.config import Settings, MCPSettings
from tests.fakes import FakeMCP, FakeForecast
from pathlib import Path


# Global temp directory for test database
TEST_DB_DIR = tempfile.mkdtemp()
TEST_DB_PATH = Path(TEST_DB_DIR) / "test_risk_intel.db"

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
    rt.config_service.update({"operating_mode": "autonomous", "execution_mode": "live"})
    return rt


def test_risk_decomposition():
    rt = create_test_runtime()
    ri = RiskIntel(rt)
    result = ri.decompose(rt.positions())
    assert hasattr(result, 'var_95')
    assert hasattr(result, 'es_95')
    assert hasattr(result, 'correlation_risk')
    assert result.var_95 >= 0
    assert result.es_95 >= 0
    assert 0 <= result.correlation_risk <= 1


def test_dynamic_sizing():
    rt = create_test_runtime()
    ri = RiskIntel(rt)
    result = ri.size("XAUUSD", "long", signal_strength=0.8)
    assert hasattr(result, 'size')
    assert hasattr(result, 'max_size')
    assert hasattr(result, 'rationale')
    assert result.size >= 0
    assert result.max_size >= 0


def test_adaptive_exit():
    rt = create_test_runtime()
    ri = RiskIntel(rt)
    result = ri.exit_plan({"symbol": "XAUUSD", "side": "buy", "entry": 3930, "sl": 3920, "tp": 3950})
    assert hasattr(result, 'trail_type')
    assert hasattr(result, 'trail_param')
    assert hasattr(result, 'partial_tps')
    assert result.trail_type in ('atr', 'structure')