"""Regime adapter: online regime detection and policy parameter swapping."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.ignite.agent.intelligence.regime import RegimeClassifier
from backend.ignite.services.runtime import Runtime


@dataclass(frozen=True)
class RegimePolicy:
    """Policy parameters for a specific regime."""
    regime: str
    risk_multiplier: float
    trail_multiplier: float
    scale_in_multiplier: float
    scale_out_multiplier: float
    max_position_pct: float
    max_concurrent: int
    max_per_symbol: int
    min_conviction: float


class RegimeAdapter:
    """Adapts policy parameters based on detected market regime."""

    # Default policies per regime
    DEFAULT_POLICIES = {
        "trend_up": RegimePolicy(
            regime="trend_up",
            risk_multiplier=1.0,
            trail_multiplier=1.0,
            scale_in_multiplier=1.0,
            scale_out_multiplier=1.0,
            max_position_pct=0.02,
            max_concurrent=10,
            max_per_symbol=2,
            min_conviction=0.6,
        ),
        "trend_down": RegimePolicy(
            regime="trend_down",
            risk_multiplier=1.0,
            trail_multiplier=1.0,
            scale_in_multiplier=1.0,
            scale_out_multiplier=1.0,
            max_position_pct=0.02,
            max_concurrent=10,
            max_per_symbol=2,
            min_conviction=0.6,
        ),
        "range": RegimePolicy(
            regime="range",
            risk_multiplier=0.5,
            trail_multiplier=0.5,
            scale_in_multiplier=0.5,
            scale_out_multiplier=1.5,
            max_position_pct=0.01,
            max_concurrent=5,
            max_per_symbol=1,
            min_conviction=0.7,
        ),
        "volatile": RegimePolicy(
            regime="volatile",
            risk_multiplier=0.3,
            trail_multiplier=0.5,
            scale_in_multiplier=0.3,
            scale_out_multiplier=1.0,
            max_position_pct=0.01,
            max_concurrent=3,
            max_per_symbol=1,
            min_conviction=0.8,
        ),
        "breakout": RegimePolicy(
            regime="breakout",
            risk_multiplier=0.8,
            trail_multiplier=0.8,
            scale_in_multiplier=1.5,
            scale_out_multiplier=0.8,
            max_position_pct=0.015,
            max_concurrent=5,
            max_per_symbol=2,
            min_conviction=0.55,
        ),
    }

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt
        self.regime_classifier = RegimeClassifier(rt)
        self.current_policy = self.DEFAULT_POLICIES["range"]  # default

    def get_current_policy(self) -> RegimePolicy:
        """Get the policy for the current market regime."""
        try:
            regime_result = self.regime_classifier.classify("XAUUSD", lookback=500)
            regime = regime_result.regime
            return self.DEFAULT_POLICIES.get(regime, self.DEFAULT_POLICIES["range"])
        except Exception:
            return self.DEFAULT_POLICIES["range"]

    def apply_policy(self, base_config: dict[str, Any]) -> dict[str, Any]:
        """Apply current regime policy to base configuration."""
        policy = self.get_current_policy()
        
        adapted = base_config.copy()
        adapted["risk_pct"] = base_config.get("risk_pct", 0.02) * policy.risk_multiplier
        adapted["trail_sl_atr"] = base_config.get("trail_sl_atr", 1.5) * policy.trail_multiplier
        adapted["scale_in_atr"] = base_config.get("scale_in_atr", 1.5) * policy.scale_in_multiplier
        adapted["scale_out_levels"] = [
            l * policy.scale_out_multiplier for l in base_config.get("scale_out_levels", [1.0, 2.0, 3.0])
        ]
        adapted["max_position_pct"] = policy.max_position_pct
        adapted["max_concurrent_positions"] = policy.max_concurrent
        adapted["max_positions_per_symbol"] = policy.max_per_symbol
        adapted["min_conviction"] = policy.min_conviction
        
        return adapted

    def get_regime_info(self) -> dict[str, Any]:
        """Get current regime information."""
        try:
            regime_result = self.rt.regime_classifier.classify("XAUUSD", lookback=500)
            return {
                "regime": regime_result.regime,
                "confidence": regime_result.confidence,
                "duration_estimate": regime_result.duration_estimate,
            }
        except Exception:
            return {"regime": "unknown", "confidence": 0.0}