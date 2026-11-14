"""Order flow analysis: CVD, delta, absorption detection."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from backend.ignite.services.runtime import Runtime
from backend.ignite.market import bars as bar_mod


class OrderFlowAnalyzer:
    """Analyzes order flow from tick/Level 2 data."""

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt

    def analyze(self, symbol: str, depth: int = 10, timeframe: str = "M5") -> dict[str, Any]:
        """Analyze order flow for a symbol."""
        # For now, use bar data as proxy (tick data would be better)
        frame = bar_mod.fetch_bars(self.rt.mcp, self.rt.clock(), symbol, timeframe, 200)
        if frame is None or len(frame) < 20:
            return {"error": "Insufficient data"}

        # Calculate CVD (Cumulative Volume Delta)
        cvd = self._calculate_cvd(frame)
        
        # Calculate delta (buy volume - sell volume)
        delta = self._calculate_delta(frame)
        
        # Detect absorption
        absorption = self._detect_absorption(frame)
        
        # Volume profile
        volume_profile = self._volume_profile(frame)

        return {
            "symbol": symbol,
            "cvd": cvd,
            "delta": delta,
            "absorption": absorption,
            "volume_profile": volume_profile,
            "timeframe": "M1",
        }

    def _calculate_cvd(self, frame: pd.DataFrame) -> dict[str, Any]:
        """Calculate Cumulative Volume Delta."""
        # Approximate buy/sell volume from price action
        # In real implementation, would use tick data with buy/sell classification
        frame = frame.copy()
        frame["delta"] = np.where(
            frame["close"] > frame["open"],
            frame["volume"],
            np.where(frame["close"] < frame["open"], -frame["volume"], 0)
        )
        frame["cvd"] = frame["delta"].cumsum()
        
        return {
            "current": frame["cvd"].iloc[-1],
            "change_24h": frame["cvd"].iloc[-1] - frame["cvd"].iloc[-min(1440, len(frame))],
            "trend": "increasing" if frame["cvd"].iloc[-1] > frame["cvd"].iloc[-2] else "decreasing",
        }

    def _calculate_delta(self, frame: pd.DataFrame) -> dict[str, Any]:
        """Calculate buy/sell volume delta."""
        buy_vol = frame.loc[frame["close"] > frame["open"], "volume"].sum()
        sell_vol = frame.loc[frame["close"] < frame["open"], "volume"].sum()
        total = buy_vol + sell_vol
        
        return {
            "buy_volume": float(buy_vol),
            "sell_volume": float(sell_vol),
            "delta": float(buy_vol - sell_vol),
            "delta_pct": float((buy_vol - sell_vol) / total * 100) if total > 0 else 0,
        }

    def _detect_absorption(self, frame: pd.DataFrame) -> dict[str, Any]:
        """Detect absorption (large volume with small price move)."""
        # Look for bars with high volume but small range
        frame = frame.copy()
        frame["range"] = frame["high"] - frame["low"]
        frame["volume_zscore"] = (frame["volume"] - frame["volume"].rolling(20).mean()) / frame["volume"].rolling(20).std()
        frame["range_zscore"] = (frame["range"] - frame["range"].rolling(20).mean()) / frame["range"].rolling(20).std()
        
        # Absorption: high volume (z > 2) but small range (z < 0.5)
        absorption_bars = frame[
            (frame["volume_zscore"] > 2) & (frame["range_zscore"] < 0.5)
        ]
        
        return {
            "detected": len(absorption_bars) > 0,
            "count": len(absorption_bars),
            "last_absorption": absorption_bars.iloc[-1].to_dict() if len(absorption_bars) > 0 else None,
        }

    def _volume_profile(self, frame: pd.DataFrame, bins: int = 20) -> dict[str, Any]:
        """Calculate volume profile (volume at price)."""
        price_min = frame["low"].min()
        price_max = frame["high"].max()
        bin_edges = np.linspace(price_min, price_max, bins + 1)
        
        volume_at_price = np.zeros(bins)
        for _, row in frame.iterrows():
            # Distribute volume across price range of the bar
            bar_min, bar_max = row["low"], row["high"]
            vol = row["volume"]
            
            # Find bins that overlap with bar range
            for i in range(bins):
                bin_min, bin_max = bin_edges[i], bin_edges[i + 1]
                if bin_max >= bar_min and bin_min <= bar_max:
                    overlap = min(bin_max, bar_max) - max(bin_min, bar_min)
                    bar_range = bar_max - bar_min
                    if bar_range > 0:
                        volume_at_price[i] += vol * (overlap / bar_range)
        
        # Find POC (Point of Control)
        poc_idx = np.argmax(volume_at_price)
        poc_price = (bin_edges[poc_idx] + bin_edges[poc_idx + 1]) / 2
        
        # Value Area (70% of volume)
        total_vol = volume_at_price.sum()
        sorted_idx = np.argsort(volume_at_price)[::-1]
        cumsum = 0
        value_area_bins = []
        for idx in sorted_idx:
            cumsum += volume_at_price[idx]
            value_area_bins.append(idx)
            if cumsum >= 0.7 * total_vol:
                break
        
        va_high = max(bin_edges[i + 1] for i in value_area_bins)
        va_low = min(bin_edges[i] for i in value_area_bins)
        
        return {
            "poc": poc_price,
            "va_high": va_high,
            "va_low": va_low,
            "total_volume": float(total_vol),
        }