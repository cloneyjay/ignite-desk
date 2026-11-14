"""Deterministic intraday structure readings from closed OHLCV bars."""

from __future__ import annotations

from typing import Any

import pandas as pd

from backend.ignite.analysis.features import Features, compute


def read_structure(frame: pd.DataFrame, features: Features) -> dict[str, Any]:
    """Return swing, level, VWAP and current price-action facts."""
    highs = frame["high"].astype(float)
    lows = frame["low"].astype(float)
    swings_high: list[dict[str, Any]] = []
    swings_low: list[dict[str, Any]] = []
    for index in range(2, len(frame) - 2):
        if highs.iloc[index] >= highs.iloc[index - 2:index + 3].max():
            swings_high.append({"time": str(frame["time"].iloc[index]), "price": float(highs.iloc[index])})
        if lows.iloc[index] <= lows.iloc[index - 2:index + 3].min():
            swings_low.append({"time": str(frame["time"].iloc[index]), "price": float(lows.iloc[index])})

    typical = (frame["high"] + frame["low"] + frame["close"]) / 3.0
    today = frame[frame["time"].dt.date == frame["time"].iloc[-1].date()]
    vwap_frame = today if len(today) >= 3 else frame.tail(48)
    volume = vwap_frame["volume"].astype(float).clip(lower=1.0)
    vwap = float((typical.loc[vwap_frame.index] * volume).sum() / volume.sum())
    last = frame.iloc[-1]
    candle_range = float(last["high"] - last["low"])
    close_location = (
        (float(last["close"]) - float(last["low"])) / candle_range
        if candle_range > 0 else 0.5
    )
    return {
        "last_close": features.last_close,
        "last_bar_time": str(features.last_time),
        "trend": features.trend,
        "atr": features.atr,
        "ema_fast": features.ema_fast,
        "ema_slow": features.ema_slow,
        "realized_vol_pct": features.realized_vol_pct,
        "vwap": vwap,
        "price_vs_vwap": "above" if features.last_close >= vwap else "below",
        "recent_high": float(highs.tail(20).max()),
        "recent_low": float(lows.tail(20).min()),
        "swing_highs": swings_high[-3:],
        "swing_lows": swings_low[-3:],
        "last_candle": {
            "open": float(last["open"]),
            "high": float(last["high"]),
            "low": float(last["low"]),
            "close": float(last["close"]),
            "close_location": close_location,
        },
    }


def compute_structure(frame: pd.DataFrame) -> dict[str, Any]:
    return read_structure(frame, compute(frame))
