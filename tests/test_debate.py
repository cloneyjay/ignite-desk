"""Tests for the multi-agent debate system."""

from __future__ import annotations

import numpy as np

from backend.ignite.agent.debate import (
    DebateContext,
    DebateEngine,
    analyse_paths,
)


def _make_paths(bullish: bool, last_close: float = 100.0, atr: float = 2.0):
    np.random.seed(42)
    loc = last_close + 6.0 if bullish else last_close - 6.0
    paths = np.random.normal(loc=loc, scale=1.5, size=(25, 12))
    paths[:, 0] = last_close
    return paths


def test_debate_long_approved():
    """Strong bullish setup should be approved for execution."""
    paths = _make_paths(bullish=True)
    context = DebateContext(
        symbol="XAUUSD",
        timeframe="M15",
        paths=paths,
        last_close=100.0,
        atr=2.0,
        equity=10000.0,
        daily_pnl=-100.0,
        daily_loss_limit=500.0,
        kill_switch=False,
        open_positions=0,
        max_positions=5,
        spread_points=10.0,
        max_spread_points=50.0,
        news_blackout=False,
        trend="up",
        calendar_high_impact=False,
    )

    engine = DebateEngine(None)  # type: ignore[arg-type]
    decision = engine.debate("XAUUSD", "M15", paths, 100.0, 2.0, context)

    assert decision.action == "enter"
    assert decision.side == "long"
    assert decision.lots is not None and decision.lots > 0
    assert decision.entry is not None
    assert decision.sl is not None
    assert decision.tp is not None


def test_debate_blocked_by_kill_switch():
    """Kill switch should block execution."""
    paths = _make_paths(bullish=True)
    context = DebateContext(
        symbol="XAUUSD",
        timeframe="M15",
        paths=paths,
        last_close=100.0,
        atr=2.0,
        equity=10000.0,
        daily_pnl=0.0,
        daily_loss_limit=500.0,
        kill_switch=True,
        open_positions=0,
        max_positions=5,
        spread_points=10.0,
        max_spread_points=50.0,
        news_blackout=False,
        trend="up",
        calendar_high_impact=False,
    )

    engine = DebateEngine(None)
    decision = engine.debate("XAUUSD", "M15", paths, 100.0, 2.0, context)

    assert decision.action == "blocked"
    assert "kill switch" in decision.narrative.lower()


def test_debate_blocked_by_daily_loss():
    """Daily loss limit should block execution."""
    paths = _make_paths(bullish=True)
    context = DebateContext(
        symbol="XAUUSD",
        timeframe="M15",
        paths=paths,
        last_close=100.0,
        atr=2.0,
        equity=10000.0,
        daily_pnl=-600.0,
        daily_loss_limit=500.0,
        kill_switch=False,
        open_positions=0,
        max_positions=5,
        spread_points=10.0,
        max_spread_points=50.0,
        news_blackout=False,
        trend="up",
        calendar_high_impact=False,
    )

    engine = DebateEngine(None)
    decision = engine.debate("XAUUSD", "M15", paths, 100.0, 2.0, context)

    assert decision.action == "blocked"
    assert "daily loss" in decision.narrative.lower()


def test_debate_skip_on_neutral():
    """Neutral Kronos signal should skip."""
    np.random.seed(42)
    last_close = 100.0
    atr = 2.0
    paths = np.random.normal(loc=100.0, scale=1.0, size=(25, 12))
    paths[:, 0] = last_close

    context = DebateContext(
        symbol="XAUUSD",
        timeframe="M15",
        paths=paths,
        last_close=100.0,
        atr=2.0,
        equity=10000.0,
        daily_pnl=0.0,
        daily_loss_limit=500.0,
        kill_switch=False,
        open_positions=0,
        max_positions=5,
        spread_points=10.0,
        max_spread_points=50.0,
        news_blackout=False,
        trend="choppy",
        calendar_high_impact=False,
    )

    engine = DebateEngine(None)
    decision = engine.debate("XAUUSD", "M15", paths, 100.0, 2.0, context)

    assert decision.action == "skip"


def test_debate_trace_non_empty():
    """Debate trace should contain all agent contributions."""
    paths = _make_paths(bullish=True)
    context = DebateContext(
        symbol="XAUUSD",
        timeframe="M15",
        paths=paths,
        last_close=100.0,
        atr=2.0,
        equity=10000.0,
        daily_pnl=0.0,
        daily_loss_limit=500.0,
        kill_switch=False,
        open_positions=0,
        max_positions=5,
        spread_points=10.0,
        max_spread_points=50.0,
        news_blackout=False,
        trend="up",
        calendar_high_impact=False,
    )

    engine = DebateEngine(None)
    decision = engine.debate("XAUUSD", "M15", paths, 100.0, 2.0, context)

    assert len(decision.debate_trace) > 3
    assert any("Researcher" in t for t in decision.debate_trace)
    assert any("Strategist" in t for t in decision.debate_trace)
    assert any("Risk Manager" in t for t in decision.debate_trace)
    assert any("Executor" in t for t in decision.debate_trace)
