"""The analysis graph.

bars -> features -> forecast -> signal -> risk -> draft.

Everything here is deterministic given the same bars and model. No LLM touches
these numbers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from backend.ignite.analysis import features as feat
from backend.ignite.analysis.risk import DraftPlan, RiskConfig, SymbolSpec, plan
from backend.ignite.analysis.signal import Signal, SignalConfig, evaluate
from backend.ignite.forecasting.client import ForecastClient
from backend.ignite.market.bars import fetch_bars, future_timestamps
from backend.ignite.market.symbols import get_spec, quote
from backend.ignite.market.time import Clock
from backend.ignite.mcp.client import MCPClient

DEFAULT_LOOKBACK = {"M5": 288, "M15": 288, "M30": 288, "H1": 512}
DEFAULT_HORIZON = {"M5": 12, "M15": 12, "M30": 8, "H1": 8}


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
) -> AnalysisResult:
    if timeframe not in DEFAULT_LOOKBACK:
        raise ValueError(f"unsupported timeframe {timeframe!r}")

    lookback = DEFAULT_LOOKBACK[timeframe]
    horizon = horizon or DEFAULT_HORIZON[timeframe]

    spec: SymbolSpec = get_spec(mcp, symbol)
    bars = fetch_bars(mcp, clock, symbol, timeframe, lookback)
    features = feat.compute(bars)
    future = future_timestamps(bars["time"].iloc[-1], timeframe, horizon)

    paths, _stamps, meta = forecast_client.forecast(
        bars, future, samples=samples, lookback=lookback
    )
    signal = evaluate(paths, features.last_close, features.atr, signal_config)

    draft: DraftPlan | None = None
    draft_id: str | None = None
    if signal.side in ("long", "short"):
        bid, ask = quote(mcp, symbol)
        reference = ask if signal.side == "long" else bid
        draft = plan(
            signal.side,
            reference,
            features.atr,
            equity,
            spec,
            features.spread_points,
            risk_config,
        )
        # The forecast is anchored on the last closed bar; if the live price has
        # already travelled, the signal is stale. Block rather than chase it.
        drift_atr = abs(reference - features.last_close) / features.atr
        if drift_atr > risk_config.max_drift_atr:
            draft = replace(
                draft,
                blocked=True,
                block_reason=(
                    f"price drifted {drift_atr:.2f} ATR from the last closed bar "
                    f"({features.last_close:.2f} -> {reference:.2f}), "
                    f"max {risk_config.max_drift_atr:.2f}"
                ),
            )
        draft_id = uuid.uuid4().hex

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
