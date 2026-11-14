"""Dynamic risk intelligence: decomposition, sizing, exits, hedging."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from backend.ignite.services.runtime import Runtime
from backend.ignite.services.ledger import DailyPnl
from backend.ignite.agent.intelligence.market_intel import MarketIntel
from backend.ignite.agent.intelligence.regime import RegimeClassifier


@dataclass(frozen=True)
class RiskDecomposition:
    """Portfolio risk decomposition."""
    var_95: float
    var_99: float
    es_95: float
    es_99: float
    tail_risk: float
    correlation_risk: float
    concentration_risk: float
    total_risk_usd: float
    risk_pct: float


@dataclass(frozen=True)
class DynamicSizing:
    """Dynamic position sizing result."""
    size: float
    max_size: float
    rationale: str
    kelly_fraction: float
    regime_multiplier: float
    correlation_penalty: float
    volatility_scaling: float


@dataclass(frozen=True)
class AdaptiveExit:
    """Adaptive exit plan."""
    trail_type: str  # atr, structure, time
    trail_param: float
    partial_tps: list[dict[str, float]]  # [{"level": 0.5, "r_multiple": 1.0}, ...]
    time_stop_bars: int | None = None


@dataclass(frozen=True)
class CorrelationHedge:
    """Correlation hedge recommendation."""
    hedge_instrument: str
    hedge_ratio: float
    cost_estimate_usd: float
    correlation: float


class RiskIntel:
    """Dynamic risk intelligence: decomposition, sizing, exits, hedging."""

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt
        self.market_intel = MarketIntel(rt)
        self.regime_classifier = RegimeClassifier(rt)

    def decompose(self, positions: list[dict[str, Any]]) -> RiskDecomposition:
        """Decompose portfolio risk into components."""
        if not positions:
            return RiskDecomposition(
                var_95=0.0, var_99=0.0, es_95=0.0, es_99=0.0,
                tail_risk=0.0, correlation_risk=0.0,
                concentration_risk=0.0, total_risk_usd=0.0, risk_pct=0.0
            )

        # Calculate individual position risks
        position_risks = []
        for pos in positions:
            risk = self._position_risk(pos)
            position_risks.append(risk)

        total_risk = sum(position_risks)
        
        # VaR (parametric, 95% and 99%)
        portfolio_std = np.std([r / self._equity() for r in position_risks]) if position_risks else 0.0
        var_95 = 1.645 * portfolio_std * self._equity()
        var_99 = 2.326 * portfolio_std * self._equity()

        # Expected Shortfall (CVaR)
        es_95 = var_95 * 1.3  # approximation for normal dist
        es_99 = var_99 * 1.3

        # Tail risk (max single position risk)
        tail_risk = max(position_risks) if position_risks else 0.0

        # Correlation risk
        correlation_risk = self._correlation_risk()

        # Concentration risk (Herfindahl index)
        sizes = [abs(self._position_value(p)) for p in self.rt.positions()]
        total = sum(sizes)
        hhi = sum((s / total) ** 2 for s in sizes) if total > 0 else 0.0
        concentration_risk = hhi

        return RiskDecomposition(
            var_95=var_95,
            var_99=var_99,
            es_95=es_95,
            es_99=es_99,
            tail_risk=tail_risk,
            correlation_risk=correlation_risk,
            concentration_risk=concentration_risk,
            total_risk_usd=total_risk,
            risk_pct=total_risk / self._equity() if self._equity() > 0 else 0.0,
        )

    def size(self, symbol: str, side: str, signal_strength: float = 1.0) -> DynamicSizing:
        """Calculate dynamic position size based on signal, regime, and risk."""
        config = self.rt.config()
        equity = self._equity()
        if equity <= 0:
            return DynamicSizing(0.0, 0.0, "no equity", 0.0, 0.0, 0.0, 0.0)

        # Base Kelly fraction (simplified)
        risk_per_trade = config.risk_pct * signal_strength
        max_risk = config.max_risk_pct * signal_strength

        # Regime multiplier
        regime = self.regime_classifier.classify(symbol)
        regime_multiplier = self._regime_multiplier(regime.regime)

        # Correlation penalty
        correlation_penalty = self._correlation_penalty(symbol)

        # Volatility scaling
        atr = self.market_intel.get_latest_structure(symbol, "M15").get("atr", 0.0)
        spec = self.rt.spec(symbol)
        vol_scaling = min(1.0, (atr / (spec.point * 1000)) if spec.point else 1.0) if atr else 1.0

        # Kelly fraction (simplified: edge / odds)
        kelly = signal_strength * 0.5  # simplified

        # Base size from risk
        risk_per_lot = self._risk_per_lot(symbol)
        base_size = (equity * risk_per_trade) / risk_per_lot if risk_per_lot > 0 else 0.0

        # Apply all adjustments
        size = base_size * regime_multiplier * correlation_penalty * vol_scaling
        size = min(size, equity * max_risk / max(1e-9, self._risk_per_lot(symbol)))

        # Round to lot step
        spec = self.rt.spec(symbol)
        step = spec.volume_step if spec else 0.01
        size = max(0.0, round(size / step) * step)

        max_size = equity * max_risk / max(1e-9, self._risk_per_lot(symbol))
        max_size = max(0.0, round(max_size / (spec.volume_step if spec else 0.01)) * (spec.volume_step if spec else 0.01))

        rationale = f"kelly={self._kelly_fraction():.3f} regime={regime.regime} mult={regime_multiplier:.2f} corr_pen={correlation_penalty:.2f} vol={vol_scaling:.2f}"

        return DynamicSizing(
            size=min(size, max_size),
            max_size=max_size,
            rationale=rationale,
            kelly_fraction=self._kelly_fraction(),
            regime_multiplier=regime_multiplier,
            correlation_penalty=correlation_penalty,
            volatility_scaling=vol_scaling,
        )

    def exit_plan(self, position: dict[str, Any]) -> AdaptiveExit:
        """Generate adaptive exit plan for a position."""
        symbol = position.get("symbol", "")
        side = position.get("side", "buy")
        entry = float(position.get("entry", 0.0))
        sl = float(position.get("sl", 0.0))
        tp = float(position.get("tp", 0.0))

        # Classify regime
        regime = self.regime_classifier.classify(position.get("symbol", ""))
        atr = self.market_intel.get_latest_structure(position.get("symbol", ""), "M15").get("atr", 0.0)

        # Trail type based on regime
        if regime.regime in ("trend_up", "trend_down"):
            trail_type = "atr"
            trail_param = self.rt.config().trail_sl_atr
        elif regime.regime == "range":
            trail_type = "structure"
            trail_param = 0.0  # structure-based
        else:
            trail_type = "atr"
            trail_param = self.rt.config().trail_sl_atr * 0.5  # tighter in volatile

        # Partial TPs at R-multiples
        risk_per_lot = abs(entry - sl) if sl else 0.0
        partial_tps = []
        for r_mult in [0.5, 1.0, 2.0, 3.0]:
            if side == "buy":
                tp_price = entry + risk_per_lot * r_mult
            else:
                tp_price = entry - risk_per_lot * r_mult
            partial_tps.append({
                "level": r_mult,
                "price": round(tp_price, 2),
                "portion": 0.25,  # 25% each level
            })

        # Time stop (max hold in bars)
        time_stop = 288 if regime.regime == "range" else None  # 48h on M15

        return AdaptiveExit(
            trail_type=trail_type,
            trail_param=trail_param,
            partial_tps=partial_tps,
            time_stop_bars=time_stop,
        )

    def hedge(self, positions: list[dict[str, Any]]) -> CorrelationHedge | None:
        """Recommend correlation hedge."""
        # Simplified: find most correlated liquid instrument
        # In production, would use correlation matrix
        return None

    # --- Helpers ---

    def _equity(self) -> float:
        return float(self.rt.account_payload().get("equity") or 0.0)

    def _position_value(self, pos: dict[str, Any]) -> float:
        return abs(float(pos.get("volume", 0)) * self.rt.spec(pos.get("symbol", "")).contract_size)

    def _position_value(self, pos: dict[str, Any]) -> float:
        return abs(float(pos.get("volume", 0)) * self.rt.spec(pos.get("symbol", "")).contract_size)

    def _position_risk(self, pos: dict[str, Any]) -> float:
        """Risk of a single position at SL."""
        sl = float(pos.get("sl") or 0.0)
        entry = float(pos.get("entry_price") or pos.get("price_open") or 0.0)
        volume = float(pos.get("volume") or 0.0)
        spec = self.rt.spec(pos.get("symbol", ""))
        if not sl or not spec:
            return 0.0
        return abs(entry - sl) * float(pos.get("volume", 0)) * spec.contract_size

    def _equity(self) -> float:
        return float(self.rt.account_payload().get("equity") or 0.0)

    def _risk_per_lot(self, symbol: str) -> float:
        spec = self.rt.spec(symbol)
        atr = self.market_intel.get_latest_structure(symbol, "M15").get("atr", 0.0)
        return atr * self.rt.config().trail_sl_atr * (spec.contract_size if spec else 1.0)

    def _kelly_fraction(self) -> float:
        # Simplified Kelly: win_rate * avg_win / avg_loss - (1 - win_rate)
        # Would use actual trade history in production
        return 0.2

    def _regime_multiplier(self, regime: str) -> float:
        multipliers = {
            "trend_up": 1.0,
            "trend_down": 1.0,
            "range": 0.5,
            "volatile": 0.3,
            "breakout": 0.8,
            "unknown": 0.3,
        }
        return multipliers.get(regime, 0.3)

    def _correlation_penalty(self, symbol: str) -> float:
        # Simplified: check existing positions in correlated symbols
        # In production, would use correlation matrix
        return 1.0

    def _correlation_risk(self) -> float:
        # Portfolio correlation risk (0-1)
        positions = self.rt.positions()
        if len(positions) < 2:
            return 0.0
        # Simplified: check if too many positions in same direction
        buys = sum(1 for p in positions if p.get("side") == "buy")
        sells = sum(1 for p in positions if p.get("side") == "sell")
        total = len(positions)
        imbalance = abs(buys - sells) / total if total > 0 else 0.0
        return imbalance * 0.5

    def _correlation_penalty(self, symbol: str) -> float:
        return 1.0 - self._correlation_risk()

    def _position_value(self, pos: dict[str, Any]) -> float:
        return abs(float(pos.get("volume", 0)) * self.rt.spec(pos.get("symbol", "")).contract_size)

    def _equity(self) -> float:
        return float(self.rt.account_payload().get("equity") or 0.0)

    def _risk_per_lot(self, symbol: str) -> float:
        spec = self.rt.spec(symbol)
        atr = self.market_intel.get_latest_structure(symbol, "M15").get("atr", 0.0)
        return atr * self.rt.config().trail_sl_atr * (spec.contract_size if spec else 1.0)

    def _kelly_fraction(self) -> float:
        return 0.2  # simplified

    def _regime_multiplier(self, regime: str) -> float:
        multipliers = {
            "trend_up": 1.0,
            "trend_down": 1.0,
            "range": 0.5,
            "volatile": 0.3,
            "breakout": 0.8,
            "unknown": 0.3,
        }
        return multipliers.get(regime, 0.3)

    def _correlation_penalty(self, symbol: str) -> float:
        return 1.0

    def _correlation_risk(self) -> float:
        return 0.0