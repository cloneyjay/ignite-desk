"""Signal rule v1. Pure function over forecast paths, no I/O, no LLM.

LONG  if p_up >= 0.62 and edge_atr >= 0.60
SHORT if p_up <= 0.38 and edge_atr <= -0.60
else NO TRADE.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
