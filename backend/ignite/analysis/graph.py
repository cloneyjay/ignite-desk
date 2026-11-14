"""The analysis graph.

bars -> features -> forecast -> signal -> risk -> draft.

Everything here is deterministic given the same bars and model. No LLM touches
these numbers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Callable

import numpy as np
import pandas as pd

from backend.ignite.analysis import features as feat
from backend.ignite.analysis.risk import DraftPlan, RiskConfig, SymbolSpec, plan
from backend.ignite.analysis.signal import (
    Signal,
    SignalConfig,
    Side,
    evaluate,
    validate_against_desk,
)
from backend.ignite.forecasting.client import ForecastClient
from backend.ignite.market.bars import fetch_bars, future_timestamps
from backend.ignite.market.symbols import calc_margin, calc_profit, get_spec, quote
from backend.ignite.market.time import Clock
from backend.ignite.mcp.client import MCPClient

DEFAULT_LOOKBACK = {"M5": 288, "M15": 288, "M30": 288, "H1": 512}
DEFAULT_HORIZON = {"M5": 12, "M15": 12, "M30": 8, "H1": 8}

Progress = Callable[[str, str, int], None]


def _tick(progress: Progress | None, step: str, message: str, pct: int) -> None:
    if progress is not None:
        progress(step, message, pct)


def _attach_economics(
    mcp: MCPClient, symbol: str, draft: DraftPlan, spec: SymbolSpec, reference: float
) -> DraftPlan:
    """Fill in broker margin and the exact worst-case loss at the stop."""
    if draft.blocked:
        return draft
    margin = worst = None
    try:
        margin = calc_margin(mcp, symbol, draft.side, draft.lots, reference)
        worst = calc_profit(mcp, symbol, draft.side, draft.lots, reference, draft.sl)
    except Exception:  # noqa: BLE001 - economics are informative, not blocking
        pass
    return replace(draft, margin=margin, worst_case_usd=worst)


def build_draft(
    mcp: MCPClient,
    symbol: str,
    side: Side,
    atr: float,
    spread_points: float,
    equity: float,
    spec: SymbolSpec,
    risk_config: RiskConfig = RiskConfig(),
    last_close: float | None = None,
) -> DraftPlan:
    """Create a fresh draft against the live quote, with the drift guard applied.

    Used both by the analysis graph and by "refresh draft" on an existing
    analysis. The reference price always comes from the live market, never from
    the last closed bar.
    """
    if side not in ("long", "short"):
        raise ValueError(f"cannot draft a {side!r} signal")
    bid, ask = quote(mcp, symbol)
    reference = ask if side == "long" else bid
    draft = plan(side, reference, atr, equity, spec, spread_points, risk_config)
    if last_close is not None:
        draft = drift_block(
            draft, reference, last_close, atr, risk_config.max_drift_atr
        )
    return _attach_economics(mcp, symbol, draft, spec, reference)


def drift_block(
    draft: DraftPlan, reference: float, last_close: float, atr: float, max_drift_atr: float
) -> DraftPlan:
    if atr <= 0:
        return draft
    drift_atr = abs(reference - last_close) / atr
    if drift_atr <= max_drift_atr:
        return draft
    return replace(
        draft,
        blocked=True,
        block_reason=(
            f"price drifted {drift_atr:.2f} ATR from the last closed bar "
            f"({last_close:.2f} -> {reference:.2f}), max {max_drift_atr:.2f}"
        ),
    )


@dataclass
class AnalysisResult:
    analysis_id: str
    draft_id: str | None
    created_at: str
    symbol: str
    timeframe: str
    lookback: int
    horizon: int
    samples: int
    model_id: str
    infer_s: float
    last_bar_time: pd.Timestamp
    bars: pd.DataFrame
    features: feat.Features
    paths: np.ndarray
    future: list[pd.Timestamp]
    signal: Signal
    draft: DraftPlan | None
    risk_version: str
    equity: float


def run_analysis(
    mcp: MCPClient,
    clock: Clock,
    forecast_client: ForecastClient,
    symbol: str,
    timeframe: str,
    equity: float,
    *,
    horizon: int | None = None,
    samples: int = 25,
    signal_config: SignalConfig = SignalConfig(),
    risk_config: RiskConfig = RiskConfig(),
    bars: pd.DataFrame | None = None,
    realtime_price: float | None = None,
    calendar_events: list[dict[str, object]] | None = None,
    progress: Progress | None = None,
) -> AnalysisResult:
    if timeframe not in DEFAULT_LOOKBACK:
        raise ValueError(f"unsupported timeframe {timeframe!r}")

    lookback = DEFAULT_LOOKBACK[timeframe]
    horizon = horizon or DEFAULT_HORIZON[timeframe]

    _tick(progress, "symbol", f"validating {symbol}", 5)
    spec: SymbolSpec = get_spec(mcp, symbol)

    if bars is None:
        _tick(progress, "bars", f"fetching {lookback} closed {timeframe} bars", 10)
        bars = fetch_bars(mcp, clock, symbol, timeframe, lookback)
    _tick(progress, "features", "computing ATR, EMAs, realised volatility", 20)
    features = feat.compute(bars)
    future = future_timestamps(bars["time"].iloc[-1], timeframe, horizon)

    _tick(progress, "forecast", f"sampling {samples} Kronos paths", 30)
    paths, _stamps, meta = forecast_client.forecast(
        bars,
        future,
        samples=samples,
        lookback=lookback,
        on_progress=lambda done, total: _tick(
            progress,
            "forecast",
            f"forecast {done}/{total} paths",
            30 + int(55 * done / max(total, 1)),
        ),
    )

    _tick(progress, "signal", "evaluating signal.v1", 85)
    signal = evaluate(paths, features.last_close, features.atr, signal_config)
    if realtime_price is not None:
        signal = validate_against_desk(
            signal,
            trend=features.trend,
            last_close=features.last_close,
            realtime_price=realtime_price,
            atr=features.atr,
            calendar_events=calendar_events,
        )

    draft: DraftPlan | None = None
    draft_id: str | None = None
    if signal.side in ("long", "short"):
        _tick(progress, "risk", "sizing position and placing stops", 92)
        draft = build_draft(
            mcp,
            symbol,
            signal.side,
            features.atr,
            features.spread_points,
            equity,
            spec,
            risk_config,
            last_close=features.last_close,
        )
        draft_id = uuid.uuid4().hex

    _tick(progress, "done", "analysis complete", 100)

    return AnalysisResult(
        analysis_id=uuid.uuid4().hex,
        draft_id=draft_id,
        created_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        symbol=symbol,
        timeframe=timeframe,
        lookback=lookback,
        horizon=horizon,
        samples=samples,
        model_id=meta["model_id"],
        infer_s=meta["infer_s"],
        last_bar_time=bars["time"].iloc[-1],
        bars=bars,
        features=features,
        paths=paths,
        future=future,
        signal=signal,
        draft=draft,
        risk_version=risk_config.version,
        equity=equity,
    )
