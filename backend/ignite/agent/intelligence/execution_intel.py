"""Execution intelligence: slippage prediction, venue selection, TWAP/VWAP/iceberg execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from backend.ignite.services.runtime import Runtime
from backend.ignite.market import bars as bar_mod


@dataclass(frozen=True)
class SlippagePrediction:
    """Predicted slippage for an order."""
    expected_slippage_bps: float
    confidence: float
    venue: str
    model_version: str = "v1"


@dataclass(frozen=True)
class VenueScore:
    """Venue selection score."""
    venue: str
    expected_fill_rate: float
    latency_ms: float
    rebate_bps: float
    toxicity_score: float
    composite_score: float


@dataclass(frozen=True)
class ExecutionPlan:
    """Execution plan for TWAP/VWAP/iceberg orders."""
    symbol: str
    side: str
    total_size: float
    slices: list[dict[str, Any]]  # [{"size": 0.1, "time_offset_min": 5, "type": "market"}, ...]
    total_duration_min: int
    strategy: str  # "twap", "vwap", "iceberg", "sniper"


class ExecutionIntel:
    """Execution quality intelligence: slippage, venue, TWAP/VWAP, fill management."""

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt

    def predict_slippage(self, symbol: str, size: float, side: str) -> SlippagePrediction:
        """Predict slippage for a given order size."""
        # Historical slippage model by venue/size/volatility/time
        spec = self.rt.spec(symbol)
        atr = self._get_atr(symbol)
        
        # Base slippage model: spread + size impact + volatility
        spread_bps = (spec.point * 10) if spec else 10  # approximate
        size_impact_bps = min(50, (size / 10.0) * 5)  # 5 bps per lot
        vol_impact_bps = self._get_vol_impact(symbol)
        
        expected = spread_bps + size_impact_bps + vol_impact_bps
        
        return SlippagePrediction(
            expected_slippage_bps=expected,
            confidence=0.7,
            venue="primary",
            model_version="v1",
        )

    def select_venue(self, symbol: str, size: float) -> VenueScore:
        """Select best venue for execution."""
        # Score venues by fill rate, latency, rebate, toxicity
        venues = ["primary", "secondary", "dark_pool"]
        scores = []
        
        for venue in venues:
            fill_rate = 0.95 if venue == "primary" else 0.85
            latency = 5 if venue == "primary" else 15
            rebate = 0.5 if venue == "primary" else 1.0
            toxicity = 0.1 if venue == "primary" else 0.3
            
            # Composite score (higher is better)
            score = (
                fill_rate * 0.4 +
                (1 - latency / 100) * 0.3 +
                rebate * 0.2 +
                (1 - toxicity) * 0.1
            )
            
            scores.append(VenueScore(
                venue=venue,
                expected_fill_rate=fill_rate,
                latency_ms=latency,
                rebate_bps=rebate,
                toxicity_score=toxicity,
                composite_score=score,
            ))
        
        return max(scores, key=lambda v: v.composite_score)

    def create_twap(self, symbol: str, total_size: float, side: str, duration_min: int, slices: int = 10) -> ExecutionPlan:
        """Create TWAP execution plan."""
        slice_size = total_size / slices
        interval = duration_min / slices
        
        slices_list = []
        for i in range(slices):
            slices_list.append({
                "size": round(total_size / slices, 2),
                "time_offset_min": i * (duration_min / slices),
                "type": "market",
                "urgency": "normal",
            })
        
        return ExecutionPlan(
            symbol=symbol,
            side=side,
            total_size=total_size,
            slices=slices_list,
            total_duration_min=duration_min,
            strategy="twap",
        )

    def create_vwap(self, symbol: str, total_size: float, side: str, duration_min: int, profile: list[float] | None = None) -> ExecutionPlan:
        """Create VWAP execution plan with volume profile."""
        if profile is None:
            # Default U-shape profile
            profile = [0.15, 0.10, 0.08, 0.07, 0.07, 0.07, 0.07, 0.07, 0.07, 0.10, 0.10, 0.10]
        
        slices_list = []
        for i, weight in enumerate(profile):
            slices_list.append({
                "size": round(total_size * weight, 2),
                "time_offset_min": i * (duration_min / len(profile)),
                "type": "market",
                "urgency": "normal",
            })
        
        return ExecutionPlan(
            symbol=symbol,
            side=side,
            total_size=sum(s["size"] for s in slices_list),
            slices=slices_list,
            total_duration_min=duration_min,
            strategy="vwap",
        )

    def create_iceberg(self, symbol: str, total_size: float, side: str, visible_size: float, duration_min: int) -> ExecutionPlan:
        """Create iceberg execution plan."""
        num_slices = int(np.ceil(total_size / visible_size))
        slice_size = total_size / num_slices
        
        slices_list = []
        for i in range(num_slices):
            slices_list.append({
                "size": round(slice_size, 2),
                "time_offset_min": i * (duration_min / num_slices),
                "type": "iceberg",
                "visible_size": visible_size,
            })
        
        return ExecutionPlan(
            symbol=symbol,
            side=side,
            total_size=total_size,
            slices=slices_list,
            total_duration_min=duration_min,
            strategy="iceberg",
        )

    def _get_atr(self, symbol: str) -> float:
        """Get ATR for symbol."""
        try:
            spec = self.rt.spec(symbol)
            if spec:
                return spec.atr if hasattr(spec, 'atr') else 0.0
        except Exception:
            pass
        return 0.0

    def _get_vol_impact(self, symbol: str) -> float:
        """Get volatility impact on slippage."""
        try:
            structure = self.rt.market_intel.get_latest_structure(symbol, "M15")
            atr = structure.get("atr", 0.0)
            return atr * 10  # rough conversion
        except Exception:
            return 5.0  # default 5 bps

    def _get_vol_impact(self, symbol: str) -> float:
        """Get volatility impact on slippage."""
        try:
            structure = self.rt.market_intel.get_latest_structure(symbol, "M15")
            atr = structure.get("atr", 0.0)
            return atr * 10  # rough conversion
        except Exception:
            return 5.0  # default 5 bps