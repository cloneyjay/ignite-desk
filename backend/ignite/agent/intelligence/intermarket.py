"""Intermarket analysis: correlations and lead/lag relationships."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from backend.ignite.services.runtime import Runtime
from backend.ignite.market import bars as bar_mod


class IntermarketAnalyzer:
    """Analyzes intermarket relationships and correlations."""

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt

    def analyze(self, symbol: str, peers: list[str], timeframe: str = "H1", lookback: int = 500) -> dict[str, Any]:
        """Analyze intermarket relationships."""
        # Fetch data for all symbols
        data = {}
        for sym in [symbol] + peers:
            try:
                frame = bar_mod.fetch_bars(self.rt.mcp, self.rt.clock(), sym, timeframe, lookback)
                if frame is not None and len(frame) > 10:
                    data[sym] = frame["close"]
            except Exception:
                pass

        if symbol not in data:
            return {"error": f"Could not fetch data for {symbol}"}

        # Align all series
        df = pd.DataFrame(data).dropna()
        if len(df) < 30:
            return {"error": "Insufficient aligned data"}

        # Compute correlations
        corr_matrix = df.corr()
        symbol_corr = corr_matrix[symbol].drop(symbol).to_dict()

        # Lead/lag analysis (Granger causality simplified)
        lead_lag = {}
        for peer in peers:
            if peer in df.columns:
                lead_lag = self._lead_lag_analysis(df[symbol], df[peer], max_lag=5)
                lead_lag[peer] = lead_lag

        return {
            "symbol": symbol,
            "peers": peers,
            "correlation": symbol_corr,
            "lead_lag": lead_lag,
            "timeframe": timeframe,
            "lookback": lookback,
        }

    def _lead_lag_analysis(self, series_a: pd.Series, series_b: pd.Series, max_lag: int = 5) -> dict[str, Any]:
        """Simplified lead/lag analysis using cross-correlation."""
        returns_a = series_a.pct_change().dropna()
        returns_b = series_b.pct_change().dropna()
        
        # Align
        common_idx = returns_a.index.intersection(returns_b.index)
        returns_a = returns_a.loc[common_idx]
        returns_b = returns_b.loc[common_idx]
        
        if len(returns_a) < 20:
            return {"max_correlation": 0, "lag": 0}
        
        max_corr = 0
        best_lag = 0
        for lag in range(-max_lag, max_lag + 1):
            if lag < 0:
                corr = returns_a.shift(-lag).corr(returns_b)
            elif lag > 0:
                corr = returns_a.corr(returns_b.shift(-lag))
            else:
                corr = returns_a.corr(returns_b)
            
            if abs(corr) > abs(max_corr):
                max_corr = corr
                best_lag = lag
        
        return {
            "max_correlation": max_corr,
            "lag_bars": best_lag,
            "interpretation": "A leads B" if best_lag > 0 else ("B leads A" if best_lag < 0 else "synchronous"),
        }

    def get_correlation_matrix(self, symbols: list[str], timeframe: str = "H1", lookback: int = 500) -> dict[str, Any]:
        """Get correlation matrix for a set of symbols."""
        data = {}
        for sym in symbols:
            try:
                frame = bar_mod.fetch_bars(self.rt.mcp, self.rt.clock(), sym, timeframe, lookback)
                if frame is not None and len(frame) > 10:
                    data[sym] = frame["close"]
            except Exception:
                pass
        
        df = pd.DataFrame(data).dropna()
        if len(df) < 30:
            return {"error": "Insufficient data"}
        
        corr = df.corr()
        return {
            "matrix": corr.to_dict(),
            "symbols": symbols,
            "timeframe": timeframe,
            "lookback": lookback,
        }