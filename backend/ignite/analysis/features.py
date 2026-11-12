"""Deterministic feature set computed from closed bars only."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


class FeatureError(RuntimeError):
    pass


@dataclass(frozen=True)
class Features:
    last_close: float
    last_time: pd.Timestamp
    atr: float
    ema_fast: float
    ema_slow: float
    realized_vol_pct: float
    spread_points: float
    trend: str


def compute(df: pd.DataFrame, atr_period: int = 14, fast: int = 20, slow: int = 50) -> Features:
    if len(df) < max(slow, atr_period) + 2:
        raise FeatureError(f"need at least {slow + 2} bars, got {len(df)}")

    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)

    true_range = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    atr = float(true_range.rolling(atr_period).mean().iloc[-1])
    if not np.isfinite(atr) or atr <= 0:
        raise FeatureError("ATR is not finite")

    ema_fast = float(close.ewm(span=fast, adjust=False).mean().iloc[-1])
    ema_slow = float(close.ewm(span=slow, adjust=False).mean().iloc[-1])

    log_returns = np.log(close / prev_close).dropna()
    realized_vol_pct = float(log_returns.tail(50).std() * 100.0)

    spread_points = float(df["spread"].iloc[-1]) if "spread" in df else 0.0
    if ema_fast > ema_slow * 1.0005:
        trend = "up"
    elif ema_fast < ema_slow * 0.9995:
        trend = "down"
    else:
        trend = "flat"

    return Features(
        last_close=float(close.iloc[-1]),
        last_time=df["time"].iloc[-1],
        atr=atr,
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        realized_vol_pct=realized_vol_pct,
        spread_points=spread_points,
        trend=trend,
    )
