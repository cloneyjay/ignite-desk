"""Tests for learning loop — backtest, A/B test, policy gradient, regime adapter."""

from __future__ import annotations

import pytest
import tempfile
import os
import atexit
from pathlib import Path

from backend.ignite.agent.learning.backtest_integration import BacktestIntegration, BacktestReport
from backend.ignite.agent.learning.ab_test import ABTest, ABTestReport
from backend.ignite.agent.learning.policy_gradient import PolicyGradient, PolicyUpdate
from backend.ignite.agent.learning.regime_adapter import RegimeAdapter, RegimePolicy
from backend.ignite.services.runtime import Runtime
from backend.ignite.config import Settings, MCPSettings
from tests.fakes import FakeMCP, FakeForecast
from pathlib import Path


# Global temp directory for test database
TEST_DB_DIR = tempfile.mkdtemp()
TEST_DB_PATH = Path(TEST_DB_DIR) / "test_learning.db"

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


def test_continuous_backtest():
    rt = create_test_runtime()
    bt = BacktestIntegration(rt)
    report = bt.run(counterfactual_decisions=100)
    assert hasattr(report, 'sharpe')
    assert hasattr(report, 'max_drawdown')
    assert hasattr(report, 'win_rate')


def test_ab_test():
    rt = create_test_runtime()
    ab = ABTest(rt)
    ab.register_variant("control", {"risk_pct": 0.02})
    ab.register_variant("treatment", {"risk_pct": 0.03})
    report = ab.run(days=30)
    assert "winner" in report and "p_value" in report


def test_policy_gradient():
    rt = create_test_runtime()
    pg = PolicyGradient(rt)
    update = pg.update({"risk_pct": 0.02}, reward=0.5)
    assert "risk_pct" in update
    result = update["risk_pct"]
    assert "parameter" in result and result["parameter"] == "risk_pct"
    assert "new_value" in result and result["new_value"] > 0