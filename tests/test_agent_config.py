"""Tests for agent configuration."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from backend.ignite.agent.config import AgentConfig


def test_agent_config_defaults():
    cfg = AgentConfig()
    assert cfg.enabled is False
    assert cfg.cycle_interval_min == 30
    assert cfg.session_open_hour == 3
    assert cfg.daily_loss_limit_pct == 0.03
    assert cfg.trail_sl_atr == 1.5
    assert cfg.scale_in_atr == 1.5
    assert cfg.scale_out_levels == (1.0, 2.0, 3.0)
    assert cfg.max_correlation == 0.7
    assert cfg.session_end_hour == 21


def test_agent_config_from_env(monkeypatch):
    monkeypatch.setenv("IGNITE_AGENT_ENABLED", "true")
    monkeypatch.setenv("IGNITE_AGENT_CYCLE_INTERVAL_MIN", "15")
    monkeypatch.setenv("IGNITE_AGENT_SESSION_OPEN_HOUR", "4")
    monkeypatch.setenv("IGNITE_AGENT_DAILY_LOSS_PCT", "0.05")
    monkeypatch.setenv("IGNITE_AGENT_TRAIL_SL_ATR", "2.0")
    monkeypatch.setenv("IGNITE_AGENT_SCALE_IN_ATR", "2.0")
    monkeypatch.setenv("IGNITE_AGENT_SCALE_OUT_LEVELS", "1.0,2.0")
    monkeypatch.setenv("IGNITE_AGENT_MAX_CORRELATION", "0.8")
    monkeypatch.setenv("IGNITE_AGENT_SESSION_END_HOUR", "22")
    monkeypatch.setenv("IGNITE_AGENT_TIMEFRAME", "M5")
    monkeypatch.setenv("IGNITE_AGENT_SYMBOLS", "XAUUSD,EURUSD")
    monkeypatch.setenv("IGNITE_AGENT_MAX_CONCURRENT", "5")
    monkeypatch.setenv("IGNITE_AGENT_POSITION_CHECK_SEC", "30")

    cfg = AgentConfig.from_env()
    assert cfg.enabled is True
    assert cfg.cycle_interval_min == 15
    assert cfg.session_open_hour == 4
    assert cfg.daily_loss_limit_pct == 0.05
    assert cfg.trail_sl_atr == 2.0
    assert cfg.scale_in_atr == 2.0
    assert cfg.scale_out_levels == (1.0, 2.0)
    assert cfg.max_correlation == 0.8
    assert cfg.session_end_hour == 22
    assert cfg.timeframe == "M5"
    assert cfg.symbols == ("XAUUSD", "EURUSD")
    assert cfg.max_concurrent_analyses == 5
    assert cfg.position_check_interval_sec == 30


def test_agent_config_from_env_partial(monkeypatch):
    """Test that unset env vars fall back to defaults."""
    monkeypatch.setenv("IGNITE_AGENT_ENABLED", "true")
    # Don't set others - should use defaults
    cfg = AgentConfig.from_env()
    assert cfg.enabled is True
    assert cfg.cycle_interval_min == 30
    assert cfg.session_open_hour == 3
    assert cfg.daily_loss_limit_pct == 0.03