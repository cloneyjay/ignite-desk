"""Signal rule v1. Pure function over forecast paths, no I/O, no LLM.

LONG  if p_up >= 0.62 and edge_atr >= 0.60
SHORT if p_up <= 0.38 and edge_atr <= -0.60
else NO TRADE.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal

import numpy as np

Side = Literal["long", "short", "none"]


@dataclass(frozen=True)
class SignalConfig:
    version: str = "signal.v1"
    p_up_long: float = 0.62
    p_up_short: float = 0.38
    min_edge_atr: float = 0.60


@dataclass(frozen=True)
class Signal:
    side: Side
    p_up: float
    edge: float
    edge_atr: float
    dispersion: float
    target_close: float
    reasons: tuple[str, ...] = field(default_factory=tuple)
    version: str = "signal.v1"


class SignalError(RuntimeError):
    pass


def validate_against_desk(
    signal: Signal,
    *,
    trend: str,
    last_close: float,
    realtime_price: float,
    atr: float,
    calendar_events: list[dict[str, object]] | None = None,
) -> Signal:
    """Cross-check a forecast with live price action, trend and realised news.

    Kronos remains the source of the forecast, but a trade signal must agree
    with the current desk state. Calendar outcomes are recorded as evidence;
    the execution blackout remains the hard calendar safety gate.
    """
    if signal.side == "none":
        return signal

    reasons = list(signal.reasons)
    conflicts: list[str] = []
    if signal.side == "long" and trend == "down":
        conflicts.append("trend is down while Kronos points long")
    elif signal.side == "short" and trend == "up":
        conflicts.append("trend is up while Kronos points short")

    move_atr = (realtime_price - last_close) / atr
    if signal.side == "long" and move_atr < -0.25:
        conflicts.append(f"live price is {abs(move_atr):.2f} ATR below the last close")
    elif signal.side == "short" and move_atr > 0.25:
        conflicts.append(f"live price is {move_atr:.2f} ATR above the last close")

    recent_surprises = []
    for event in calendar_events or []:
        if str(event.get("impact") or "").lower() != "high":
            continue
        actual = event.get("actual")
        forecast = event.get("forecast")
        if actual is None or forecast is None:
            continue
        try:
            surprise = float(actual) - float(forecast)
        except (TypeError, ValueError):
            continue
        if surprise:
            recent_surprises.append(
                f"{event.get('name', 'high-impact event')} actual "
                f"{'beat' if surprise > 0 else 'missed'} forecast"
            )
    reasons.extend(recent_surprises[:2])

    if conflicts:
        return replace(
            signal,
            side="none",
            reasons=tuple(dict.fromkeys(reasons + conflicts)),
        )
    return replace(signal, reasons=tuple(dict.fromkeys(reasons)))


def evaluate(
    paths: np.ndarray,
    last_close: float,
    atr: float,
    config: SignalConfig = SignalConfig(),
) -> Signal:
    """paths: shape (samples, horizon), forecast close values."""
    if paths.ndim != 2 or paths.shape[0] < 1:
        raise SignalError(f"expected (samples, horizon) paths, got {paths.shape}")
    if not np.isfinite(paths).all():
        raise SignalError("forecast contains non-finite values")
    if last_close <= 0 or atr <= 0:
        raise SignalError("last_close and atr must be positive")

    ends = paths[:, -1]
    p_up = float((ends > last_close).mean())
    target = float(ends.mean())
    edge = target - last_close
    edge_atr = edge / atr
    dispersion = float(ends.std(ddof=1)) if len(ends) > 1 else 0.0

    reasons: list[str] = []
    eps = 1e-9
    if p_up >= config.p_up_long - eps and edge_atr >= config.min_edge_atr - eps:
        side: Side = "long"
        reasons.append(f"p_up {p_up:.2f} >= {config.p_up_long}")
        reasons.append(f"edge {edge_atr:.2f} ATR >= {config.min_edge_atr}")
    elif p_up <= config.p_up_short + eps and edge_atr <= -config.min_edge_atr + eps:
        side = "short"
        reasons.append(f"p_up {p_up:.2f} <= {config.p_up_short}")
        reasons.append(f"edge {edge_atr:.2f} ATR <= -{config.min_edge_atr}")
    else:
        side = "none"
        if config.p_up_short < p_up < config.p_up_long:
            reasons.append(f"p_up {p_up:.2f} in the neutral band")
        else:
            reasons.append(f"p_up {p_up:.2f} directionally OK but edge {edge_atr:.2f} ATR too small")
        if abs(edge_atr) < config.min_edge_atr:
            reasons.append(f"|edge| {abs(edge_atr):.2f} ATR < {config.min_edge_atr}")

    return Signal(
        side=side,
        p_up=p_up,
        edge=edge,
        edge_atr=edge_atr,
        dispersion=dispersion,
        target_close=target,
        reasons=tuple(dict.fromkeys(reasons)),
        version=config.version,
    )
