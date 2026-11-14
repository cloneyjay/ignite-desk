"""Tests for execution intelligence module."""

from __future__ import annotations

import pytest
import tempfile
import os
import atexit
from pathlib import Path

from backend.ignite.agent.intelligence.execution_intel import ExecutionIntel
from backend.ignite.services.runtime import Runtime
from backend.ignite.config import Settings, MCPSettings
from tests.fakes import FakeMCP, FakeForecast
from pathlib import Path


# Global temp directory for test database
TEST_DB_DIR = tempfile.mkdtemp()
TEST_DB_PATH = Path(TEST_DB_DIR) / "test_execution_intel.db"

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


def test_slippage_prediction(rt):
    ei = ExecutionIntel(rt)
    pred = ei.predict_slippage("XAUUSD", 0.1, "buy")
    assert hasattr(pred, 'expected_slippage_bps')
    assert hasattr(pred, 'confidence')
    assert pred.expected_slippage_bps >= 0


def test_venue_selection(rt):
    ei = ExecutionIntel(rt)
    venue = ei.select_venue("XAUUSD", 0.1)
    assert hasattr(venue, 'venue')
    assert hasattr(venue, 'expected_fill_rate')
    assert venue.expected_fill_rate > 0


def test_twap_execution(rt):
    ei = ExecutionIntel(rt)
    plan = ei.create_twap("XAUUSD", 1.0, "buy", duration_min=60)
    assert hasattr(plan, 'slices')
    assert len(plan.slices) > 1
    total = sum(s.get('size', 0) for s in plan.slices)
    assert abs(total - 1.0) < 0.01