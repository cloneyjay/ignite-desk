"""Market intelligence: multi-timeframe synthesis and analysis."""

from __future__ import annotations

from typing import Any

from backend.ignite.agent.tools import ToolRegistry
from backend.ignite.services.runtime import Runtime
from backend.ignite.market.structure import compute_structure
from backend.ignite.market import bars as bar_mod


class MarketIntel:
    """Synthesizes market intelligence across multiple timeframes."""

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt

    def synthesize(self, symbol: str, timeframes: list[str]) -> dict[str, Any]:
        """Synthesize market intelligence across multiple timeframes."""
        results = {}
        for tf in timeframes:
            try:
                frame = bar_mod.fetch_bars(self.rt.mcp, self.rt.clock(), symbol, tf, 120)
                structure = compute_structure(frame)
                results[tf] = {
                    "trend": structure["trend"],
                    "last_close": structure["last_close"],
                    "ema_fast": structure["ema_fast"],
                    "ema_slow": structure["ema_slow"],
                    "atr": structure["atr"],
                    "vwap": structure["vwap"],
                    "price_vs_vwap": structure["price_vs_vwap"],
                    "swing_highs": structure["swing_highs"],
                    "swing_lows": structure["swing_lows"],
                    "recent_high": structure["recent_high"],
                    "recent_low": structure["recent_low"],
                }
            except Exception as e:
                results[tf] = {"error": str(e)}

        # Determine overall trend consensus
        trends = [r.get("trend") for r in results.values() if "trend" in r]
        trend_consensus = self._consensus(trends)

        return {
            "symbol": symbol,
            "timeframes": results,
            "trend_consensus": trend_consensus,
            "timeframes_analyzed": len(results),
        }

    def _consensus(self, trends: list[str]) -> str:
        """Determine trend consensus across timeframes."""
        if not trends:
            return "unknown"
        bullish = trends.count("bullish") + trends.count("up")
        bearish = trends.count("bearish") + trends.count("down")
        if bullish > bearish:
            return "bullish"
        elif bearish > bullish:
            return "bearish"
        return "neutral"

    def get_latest_structure(self, symbol: str, timeframe: str = "M15") -> dict[str, Any]:
        """Get latest market structure for a symbol/timeframe."""
        frame = bar_mod.fetch_bars(self.rt.mcp, self.rt.clock(), symbol, timeframe, 120)
        return compute_structure(frame)