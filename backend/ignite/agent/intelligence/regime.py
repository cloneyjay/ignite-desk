"""Regime classification using HMM and statistical methods."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from backend.ignite.services.runtime import Runtime
from backend.ignite.market import bars as bar_mod
from backend.ignite.market.structure import compute_structure


@dataclass(frozen=True)
class RegimeResult:
    """Result of regime classification."""
    regime: str  # trend_up, trend_down, range, volatile, breakout
    confidence: float
    duration_estimate: int | None = None  # bars
    metadata: dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            object.__setattr__(self, "metadata", {})


class RegimeClassifier:
    """Classifies market regime using HMM and statistical methods."""

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt
        self._model = None

    def classify(self, symbol: str, timeframe: str = "M15", lookback: int = 500) -> RegimeResult:
        """Classify the current market regime."""
        # Fetch bars
        frame = bar_mod.fetch_bars(self.rt.mcp, self.rt.clock(), symbol, timeframe, lookback)
        if frame is None or len(frame) < 50:
            return RegimeResult(regime="unknown", confidence=0.0)

        # Compute features
        structure = compute_structure(frame)
        
        # Simple rule-based regime classification (HMM would be more sophisticated)
        regime, confidence = self._classify_regime(frame, structure)
        
        return RegimeResult(
            regime=regime,
            confidence=confidence,
            metadata={
                "symbol": symbol,
                "timeframe": timeframe,
                "lookback": lookback,
                "trend": structure["trend"],
                "atr": structure["atr"],
                "price_vs_vwap": structure["price_vs_vwap"],
            }
        )

    def _classify_regime(self, frame: pd.DataFrame, structure: dict[str, Any]) -> tuple[str, float]:
        """Classify regime using price action and volatility."""
        trend = structure["trend"]
        atr = structure["atr"]
        last_close = structure["last_close"]
        vwap = structure["vwap"]
        price_vs_vwap = structure["price_vs_vwap"]
        
        # Calculate volatility regime
        returns = frame["close"].pct_change().dropna()
        vol = returns.std() * np.sqrt(252)  # annualized
        
        # Trend strength
        ema_fast = structure["ema_fast"]
        ema_slow = structure["ema_slow"]
        trend_strength = abs(ema_fast - ema_slow) / last_close if last_close else 0
        
        # Classify
        # price_vs_vwap is "above" or "below" from compute_structure
        price_above_vwap = price_vs_vwap == "above"
        
        if trend_strength > 0.02 and trend == "bullish":
            return "trend_up", min(0.9, 0.5 + trend_strength * 10)
        elif trend_strength > 0.02 and trend == "bearish":
            return "trend_down", min(0.9, 0.5 + trend_strength * 10)
        elif vol > 0.30:  # High volatility
            return "volatile", 0.7
        elif price_above_vwap is False and trend_strength < 0.01:
            return "range", 0.7
        else:
            return "breakout", 0.5