"""Tests for market intelligence module."""

from __future__ import annotations

import pytest
import tempfile
import os
import atexit
from pathlib import Path

from backend.ignite.agent.intelligence.market_intel import MarketIntel
from backend.ignite.agent.intelligence.regime import RegimeClassifier, RegimeResult
from backend.ignite.agent.intelligence.intermarket import IntermarketAnalyzer
from backend.ignite.agent.intelligence.order_flow import OrderFlowAnalyzer
from backend.ignite.services.runtime import Runtime
from backend.ignite.config import Settings, MCPSettings
from tests.fakes import FakeMCP, FakeForecast
from pathlib import Path


# Global temp directory for test database
TEST_DB_DIR = tempfile.mkdtemp()
TEST_DB_PATH = Path(TEST_DB_DIR) / "test_market_intel.db"

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


def test_multi_tf_synthesis():
    rt = create_test_runtime()
    intel = MarketIntel(rt)
    result = intel.synthesize("XAUUSD", ["M5", "M15", "H1", "H4", "D1"])
    assert "symbol" in result
    assert "timeframes" in result
    assert "trend_consensus" in result
    assert "timeframes_analyzed" in result


def test_regime_classification():
    rt = create_test_runtime()
    regime = RegimeClassifier(rt)
    result = regime.classify("XAUUSD", lookback=500)
    assert result.regime in ("trend_up", "trend_down", "range", "volatile", "breakout")
    assert 0 <= result.confidence <= 1


def test_intermarket_correlation():
    rt = create_test_runtime()
    im = IntermarketAnalyzer(rt)
    result = im.analyze("XAUUSD", ["DXY", "US10Y", "US500"])
    assert "correlation" in result and "lead_lag" in result


def test_order_flow_analysis():
    rt = create_test_runtime()
    of = OrderFlowAnalyzer(rt)
    result = of.analyze("XAUUSD", depth=10)
    assert "cvd" in result and "delta" in result and "absorption" in result