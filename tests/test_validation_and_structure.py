"""Tests for market structure, forecast validation, and the daily brief."""

from __future__ import annotations

import pandas as pd

from backend.ignite.agent.skills.daily_brief import template_narrative
from backend.ignite.analysis.signal import Signal, validate_against_desk
from backend.ignite.market.structure import compute_structure


def test_structure_reading_contains_levels_and_vwap():
    rows = []
    for index in range(60):
        close = 1900.0 + index * 0.2
        rows.append(
            {
                "time": pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=15 * index),
                "open": close - 0.1,
                "high": close + 0.3,
                "low": close - 0.3,
                "close": close,
                "volume": 100 + index,
                "spread": 10,
            }
        )
    frame = pd.DataFrame(rows)
    structure = compute_structure(frame)
    assert structure["atr"] > 0
    assert structure["vwap"] > 0
    assert "swing_highs" in structure and "swing_lows" in structure


def test_forecast_validation_blocks_conflicting_live_context():
    signal = Signal(
        side="long",
        p_up=0.8,
        edge=8.0,
        edge_atr=0.8,
        dispersion=1.0,
        target_close=100.0,
        reasons=("forecast supports long",),
    )

    validated = validate_against_desk(
        signal,
        trend="down",
        last_close=100.0,
        realtime_price=98.0,
        atr=4.0,
    )

    assert validated.side == "none"
    assert any("trend is down" in reason for reason in validated.reasons)
    assert any("below the last close" in reason for reason in validated.reasons)


def test_daily_brief_template_is_plain_english():
    class Pack:
        payload = {
            "timeframes": [
                {"timeframe": "M15", "signal": "short", "p_up": 0.35, "edge_atr": -0.4},
            ],
            "calendar": [],
        }

    text = template_narrative(Pack())

    assert "Here is the desk picture" in text
    assert "leaning lower" in text
    assert "p_up" not in text
    assert "edge" not in text
    assert "ATR" not in text
