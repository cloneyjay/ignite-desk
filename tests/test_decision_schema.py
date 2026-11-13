"""Tests for structured decision schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.ignite.agent.decision import Decision, DecisionError, parse_decision


def test_valid_long_decision_passes():
    d = Decision(
        symbol="XAUUSD",
        timeframe="M15",
        action="LONG",
        conviction=0.82,
        thesis="Test thesis",
        evidence=["evidence 1", "evidence 2"],
        failed_conditions=[],
        entry={"type": "market", "price": 0.0},
        risk={"lots": 0.02, "sl": 3920.0, "tp": 3950.0},
        expected_rr=2.5,
        invalidate_if=["condition 1"],
        links={"analysis_id": "a1", "draft_id": "d1", "decision_id": "dec1"},
    )
    assert d.action == "LONG"
    assert d.conviction == 0.82
    assert d.entry.type == "market"
    assert d.risk.lots == 0.02


def test_valid_short_decision_passes():
    d = Decision(
        symbol="EURUSD",
        timeframe="H1",
        action="SHORT",
        conviction=0.75,
        thesis="Short thesis",
        evidence=["evidence 1"],
        failed_conditions=[],
        entry={"type": "limit", "price": 1.0850},
        risk={"lots": 0.1, "sl": 1.0900, "tp": 1.0700},
        expected_rr=1.5,
        invalidate_if=["price above 1.09"],
        links={"analysis_id": "a2", "draft_id": "d2", "decision_id": "dec2"},
    )
    assert d.action == "SHORT"
    assert d.entry.type == "limit"
    assert d.entry.price == 1.0850


def test_no_trade_decision_passes():
    d = Decision(
        symbol="XAUUSD",
        timeframe="M15",
        action="NO_TRADE",
        conviction=0.0,
        thesis="No setup",
        evidence=[],
        failed_conditions=["spread too wide"],
        entry={"type": "market", "price": 0.0},
        risk={"lots": 0.0, "sl": 0.0, "tp": 0.0},
        expected_rr=0.0,
        invalidate_if=[],
        links={"analysis_id": "a3", "draft_id": None, "decision_id": "dec3"},
    )
    assert d.action == "NO_TRADE"


def test_invalid_action_rejected():
    with pytest.raises(ValidationError):
        Decision(
            symbol="XAUUSD",
            timeframe="M15",
            action="BUY",  # not in enum
            conviction=0.8,
            thesis="...",
            evidence=[],
            failed_conditions=[],
            entry={"type": "market", "price": 0.0},
            risk={"lots": 0.02, "sl": 3920.0, "tp": 3950.0},
            expected_rr=2.0,
            invalidate_if=[],
            links={},
        )


def test_missing_required_field_rejected():
    with pytest.raises(ValidationError):
        Decision(symbol="XAUUSD", timeframe="M15")  # missing action, etc.


def test_extra_field_rejected():
    with pytest.raises(ValidationError):
        Decision(
            symbol="XAUUSD",
            timeframe="M15",
            action="LONG",
            conviction=0.8,
            thesis="...",
            evidence=[],
            failed_conditions=[],
            entry={"type": "market", "price": 0.0},
            risk={"lots": 0.02, "sl": 3920.0, "tp": 3950.0},
            expected_rr=2.0,
            invalidate_if=[],
            links={},
            extra_field="not allowed",
        )


def test_parse_decision_valid_json():
    json_str = """{
        "symbol": "XAUUSD",
        "timeframe": "M15",
        "action": "LONG",
        "conviction": 0.8,
        "thesis": "test",
        "evidence": ["e1"],
        "failed_conditions": [],
        "entry": {"type": "market", "price": 0.0},
        "risk": {"lots": 0.01, "sl": 3900.0, "tp": 3950.0},
        "expected_rr": 2.0,
        "invalidate_if": [],
        "links": {"analysis_id": "a", "draft_id": "d", "decision_id": "dec"}
    }"""
    result = parse_decision(json_str)
    assert isinstance(result, Decision)
    assert result.action == "LONG"


def test_parse_decision_invalid_json():
    result = parse_decision("not json")
    assert isinstance(result, DecisionError)
    assert "invalid json" in str(result).lower()


def test_parse_decision_invalid_schema():
    json_str = '{"symbol": "XAUUSD", "timeframe": "M15", "action": "INVALID"}'
    result = parse_decision(json_str)
    assert isinstance(result, DecisionError)