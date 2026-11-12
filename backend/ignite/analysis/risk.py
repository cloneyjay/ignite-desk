"""Position sizing and pre-trade safety. Pure function, no I/O."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

Side = Literal["long", "short"]


@dataclass(frozen=True)
class SymbolSpec:
    symbol: str
    digits: int
    point: float
    contract_size: float
    tick_value: float
    volume_min: float
    volume_max: float
    volume_step: float
    stops_level: int


@dataclass(frozen=True)
class RiskConfig:
    version: str = "risk.v1"
    risk_pct: float = 0.005
    max_risk_pct: float = 0.010
    sl_atr: float = 1.5
    tp_atr: float = 3.0
    min_rr: float = 2.0
    max_spread_points: float = 30.0
    max_drift_atr: float = 0.30


@dataclass(frozen=True)
class DraftPlan:
    side: Side
    lots: float
    reference_price: float
    sl: float
    tp: float
    risk_usd: float
    risk_pct: float
    rr: float
    sl_distance: float
    tp_distance: float
    blocked: bool
    block_reason: str | None
    margin: float | None = None
    worst_case_usd: float | None = None
    reasons: tuple[str, ...] = field(default_factory=tuple)
    version: str = "risk.v1"


def _round_price(value: float, digits: int) -> float:
    return round(value, digits)


def _floor_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    return math.floor(value / step + 1e-9) * step


def plan(
    side: Side,
    reference_price: float,
    atr: float,
    equity: float,
    spec: SymbolSpec,
    spread_points: float,
    config: RiskConfig = RiskConfig(),
) -> DraftPlan:
    reasons: list[str] = []

    def blocked(reason: str) -> DraftPlan:
        return DraftPlan(
            side=side,
            lots=0.0,
            reference_price=reference_price,
            sl=0.0,
            tp=0.0,
            risk_usd=0.0,
            risk_pct=0.0,
            rr=0.0,
            sl_distance=0.0,
            tp_distance=0.0,
            blocked=True,
            block_reason=reason,
            reasons=tuple(reasons),
            version=config.version,
        )

    if not math.isfinite(atr) or atr <= 0:
        return blocked("ATR is not finite")
    if not math.isfinite(reference_price) or reference_price <= 0:
        return blocked("reference price is invalid")
    if equity <= 0:
        return blocked("account equity is not positive")
    if config.risk_pct > config.max_risk_pct + 1e-12:
        return blocked(f"risk_pct {config.risk_pct:.3f} exceeds cap {config.max_risk_pct:.3f}")
    if spread_points > config.max_spread_points:
        return blocked(f"spread {spread_points:.0f} points above cap {config.max_spread_points:.0f}")

    sl_distance = config.sl_atr * atr
    tp_distance = config.tp_atr * atr
    min_distance = spec.stops_level * spec.point
    if min_distance and sl_distance < min_distance:
        return blocked(
            f"SL distance {sl_distance:.2f} below broker minimum {min_distance:.2f}"
        )

    rr = tp_distance / sl_distance
    if rr + 1e-9 < config.min_rr:
        return blocked(f"R:R {rr:.2f} below minimum {config.min_rr:.2f}")

    risk_usd = equity * config.risk_pct
    raw_lots = risk_usd / (sl_distance * spec.contract_size)
    lots = _floor_step(raw_lots, spec.volume_step)
    lots = round(lots, 8)
    if lots < spec.volume_min:
        return blocked(
            f"size {raw_lots:.4f} lots below minimum {spec.volume_min} "
            f"(risk {risk_usd:.2f} USD over {sl_distance:.2f} SL)"
        )
    if lots > spec.volume_max:
        lots = spec.volume_max
        reasons.append(f"size clamped to broker maximum {spec.volume_max}")

    if side == "long":
        sl = _round_price(reference_price - sl_distance, spec.digits)
        tp = _round_price(reference_price + tp_distance, spec.digits)
    else:
        sl = _round_price(reference_price + sl_distance, spec.digits)
        tp = _round_price(reference_price - tp_distance, spec.digits)

    if side == "long" and not (sl < reference_price < tp):
        return blocked("invalid long price levels after rounding")
    if side == "short" and not (tp < reference_price < sl):
        return blocked("invalid short price levels after rounding")

    actual_risk = lots * sl_distance * spec.contract_size
    actual_risk_pct = actual_risk / equity
    reasons.append(f"risk {actual_risk_pct:.3%} of equity ({actual_risk:.2f} USD)")
    reasons.append(f"SL {config.sl_atr:g}xATR, TP {config.tp_atr:g}xATR, R:R {rr:.2f}")

    return DraftPlan(
        side=side,
        lots=lots,
        reference_price=_round_price(reference_price, spec.digits),
        sl=sl,
        tp=tp,
        risk_usd=round(actual_risk, 2),
        risk_pct=actual_risk_pct,
        rr=round(rr, 3),
        sl_distance=sl_distance,
        tp_distance=tp_distance,
        blocked=False,
        block_reason=None,
        reasons=tuple(reasons),
        version=config.version,
    )
