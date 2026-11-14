"""Tests for the Analyst unit: multi-source market read → deterministic analysis → draft."""

from __future__ import annotations

from backend.ignite.agent.analyst import Analyst, AnalystResult


def test_analyst_returns_structured_result(rt):
    """Analyst.assess returns a structured result with signal, levels, and draft."""
    analyst = Analyst(rt)
    result = analyst.assess("XAUUSD", "M15")

    assert isinstance(result, AnalystResult)
    assert result.symbol == "XAUUSD"
    assert result.timeframe == "M15"
    assert result.signal in {"LONG", "SHORT", "NONE"}
    assert 0.0 <= result.p_up <= 1.0
    assert result.draft_id is None or isinstance(result.draft_id, str)
    assert isinstance(result.rationale, str) and len(result.rationale) > 0
    assert isinstance(result.data, dict)
