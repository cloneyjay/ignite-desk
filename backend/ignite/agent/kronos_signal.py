"""Kronos probabilistic forecast analysis.

Takes raw Kronos forecast paths (samples, horizon) and produces a rich,
probabilistic signal with:
- p_up: probability close > last_close at horizon
- edge_atr: expected edge in ATR units
- dispersion: forecast uncertainty
- confidence bands: p10/p50/p90 close prices
- regime classification: trend / mean-reversion / breakout
- confidence score: 0-1 based on dispersion vs edge

All pure functions over numpy arrays — no I/O, no LLM, fully testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np


@dataclass(frozen=True)
class KronosSignal:
    """Probabilistic forecast signal from Kronos paths."""

    side: Literal["long", "short", "none"]
    p_up: float
    edge_atr: float
    dispersion: float
    target_close: float
    p10_close: float
    p50_close: float
    p90_close: float
    regime: Literal["trend", "mean_reversion", "breakout", "choppy"]
    confidence: float  # 0.0 to 1.0
    reasons: tuple[str, ...]
    version: str = "kronos_signal.v1"


def analyse_paths(
    paths: np.ndarray,
    last_close: float,
    atr: float,
    *,
    p_up_long: float = 0.62,
    p_up_short: float = 0.38,
    min_edge_atr: float = 0.60,
    max_dispersion_atr: float = 1.50,
) -> KronosSignal:
    """Analyse Kronos forecast paths into a trading signal.

    Parameters
    ----------
    paths : np.ndarray
        Shape (samples, horizon) forecast close values.
    last_close : float
        Last observed close price.
    atr : float
        Current ATR for normalisation.
    p_up_long / p_up_short : float
        Probability thresholds for long/short.
    min_edge_atr : float
        Minimum edge (in ATR) required to trade.
    max_dispersion_atr : float
        Maximum dispersion (in ATR) before classifying as choppy/uncertain.
    """
    if paths.ndim != 2 or paths.shape[0] < 2:
        raise ValueError(f"expected (samples, horizon) paths, got {paths.shape}")
    if not np.isfinite(paths).all():
        raise ValueError("forecast contains non-finite values")
    if last_close <= 0 or atr <= 0:
        raise ValueError("last_close and atr must be positive")

    samples, horizon = paths.shape
    ends = paths[:, -1]

    # --- Core probabilities ---
    p_up = float((ends > last_close).mean())
    target = float(ends.mean())
    edge = target - last_close
    edge_atr = edge / atr
    dispersion = float(ends.std(ddof=1))

    # --- Confidence bands ---
    p10_close = float(np.percentile(ends, 10))
    p50_close = float(np.percentile(ends, 50))
    p90_close = float(np.percentile(ends, 90))

    # --- Regime classification ---
    path_changes = np.diff(paths, axis=1)
    directional_consistency = float(
        np.mean(np.all(path_changes > 0, axis=1) | np.all(path_changes < 0, axis=1))
    )
    volatility_ratio = float(dispersion / atr)

    if dispersion < 0.30 * atr:
        regime = "mean_reversion"
    elif directional_consistency > 0.70:
        regime = "trend"
    elif volatility_ratio > max_dispersion_atr:
        regime = "breakout"
    else:
        regime = "choppy"

    # --- Signal decision ---
    reasons: list[str] = []
    side: Literal["long", "short", "none"] = "none"

    # Confidence: high when dispersion is low relative to edge, and p_up is extreme
    confidence = _compute_confidence(p_up, edge_atr, dispersion, atr, directional_consistency)

    if p_up >= p_up_long and edge_atr >= min_edge_atr and dispersion <= max_dispersion_atr * atr:
        side = "long"
        reasons.append(f"p_up {p_up:.2f} >= {p_up_long}")
        reasons.append(f"edge {edge_atr:+.2f} ATR >= {min_edge_atr}")
        reasons.append(f"dispersion {dispersion/atr:.2f} ATR <= {max_dispersion_atr}")
    elif p_up <= p_up_short and edge_atr <= -min_edge_atr and dispersion <= max_dispersion_atr * atr:
        side = "short"
        reasons.append(f"p_up {p_up:.2f} <= {p_up_short}")
        reasons.append(f"edge {edge_atr:+.2f} ATR <= -{min_edge_atr}")
        reasons.append(f"dispersion {dispersion/atr:.2f} ATR <= {max_dispersion_atr}")
    else:
        if p_up_short < p_up < p_up_long:
            reasons.append(f"p_up {p_up:.2f} in neutral band")
        if abs(edge_atr) < min_edge_atr:
            reasons.append(f"|edge| {abs(edge_atr):.2f} ATR < {min_edge_atr}")
        if dispersion > max_dispersion_atr * atr:
            reasons.append(f"dispersion {dispersion/atr:.2f} ATR too high (> {max_dispersion_atr})")

    return KronosSignal(
        side=side,
        p_up=p_up,
        edge_atr=edge_atr,
        dispersion=dispersion,
        target_close=target,
        p10_close=p10_close,
        p50_close=p50_close,
        p90_close=p90_close,
        regime=regime,
        confidence=confidence,
        reasons=tuple(dict.fromkeys(reasons)),
        version="kronos_signal.v1",
    )


def _compute_confidence(
    p_up: float,
    edge_atr: float,
    dispersion: float,
    atr: float,
    directional_consistency: float,
) -> float:
    """Compute confidence score 0-1.

    Factors:
    - p_up extremity: how far from 0.5
    - edge strength: |edge_atr|
    - dispersion: lower is better (normalised by ATR)
    - path consistency: do all paths agree on direction?
    """
    p_extremity = abs(p_up - 0.5) * 2.0  # 0 to 1
    edge_strength = min(abs(edge_atr) / 2.0, 1.0)  # cap at 2 ATR
    dispersion_penalty = max(0.0, 1.0 - dispersion / (2.0 * atr))  # 0 at 2 ATR
    consistency = directional_consistency  # 0 to 1

    return float(
        0.30 * p_extremity
        + 0.30 * edge_strength
        + 0.20 * dispersion_penalty
        + 0.20 * consistency
    )


def signal_to_narrative(
    signal: KronosSignal,
    symbol: str,
    timeframe: str,
    atr: float,
) -> str:
    """Convert a KronosSignal to a plain-English narrative."""
    side_word = {
        "long": "LONG",
        "short": "SHORT",
        "none": "NO TRADE",
    }[signal.side]

    dispersion_atr = signal.dispersion / atr if atr > 0 else 0.0

    parts = [
        f"Kronos {side_word} for {symbol} {timeframe}:",
        f"  p_up {signal.p_up:.0%} (probability close > last close)",
        f"  edge {signal.edge_atr:+.2f} ATR (expected move)",
        f"  dispersion {dispersion_atr:.2f} ATR (uncertainty)",
        f"  regime: {signal.regime}",
        f"  confidence: {signal.confidence:.0%}",
        f"  target close: {signal.target_close:.2f}",
        f"  p10/p50/p90: {signal.p10_close:.2f} / {signal.p50_close:.2f} / "
        f"{signal.p90_close:.2f}",
    ]
    if signal.reasons:
        parts.append("  reasons: " + "; ".join(signal.reasons))
    return "\n".join(parts)


def atr_if_positive(atr: float) -> float:
    return atr if atr > 0 else 1.0
