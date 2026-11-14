from __future__ import annotations

import pandas as pd

from backend.ignite.agent.chat import route_chat
from backend.ignite.agent.skills.daily_brief import template_narrative
from backend.ignite.analysis.features import compute
from backend.ignite.analysis.signal import Signal, validate_against_desk
from backend.ignite.market.structure import compute_structure


def test_chat_routes_manual_desk_controls():
    assert route_chat("turn autonomous on").args == {"enabled": True}
    assert route_chat("close position 152900990451").args == {"ticket": "152900990451"}
    assert route_chat("add EURUSD to watchlist").skill == "add_symbol"
    assert route_chat("show calendar").skill == "calendar"
    assert route_chat("what is the open trade in MT5").skill == "positions"
    structure = route_chat("pull the current structure of XAUUSD on M15")
    assert structure.skill == "market_structure"
    assert structure.args == {"symbol": "XAUUSD", "timeframe": "M15"}


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
