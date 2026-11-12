"""Walk-forward validation framework.

Validates the deterministic signal engine against historical data.
Produces a report comparing Kronos + signal vs baselines.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backend.ignite.analysis.graph import DEFAULT_HORIZON, DEFAULT_LOOKBACK, run_analysis
from backend.ignite.analysis.risk import RiskConfig
from backend.ignite.config import ROOT, load_settings
from backend.ignite.forecasting.client import ForecastClient
from backend.ignite.market.bars import fetch_bars
from backend.ignite.market.time import Clock
from backend.ignite.mcp.client import MCPClient
from backend.ignite.store.db import Store


@dataclass
class WalkForwardResult:
    period_start: str
    period_end: str
    total_bars: int
    analyses: int
    signals: dict[str, int]
    baselines: dict[str, dict[str, float]]
    output_path: str


def _utc_midnight(days_ago: int) -> datetime:
    now = datetime.now(timezone.utc)
    return (now - timedelta(days=days_ago)).replace(hour=0, minute=0, second=0, microsecond=0)


def _collect_bars(
    mcp: MCPClient,
    clock: Clock,
    symbol: str,
    timeframe: str,
    start_utc: datetime,
    end_utc: datetime,
) -> pd.DataFrame:
    """Fetch bars for a UTC range, return DataFrame with 'time' column."""
    bars_list = []
    current_end = end_utc
    while current_end > start_utc:
        batch = fetch_bars(mcp, clock, symbol, timeframe, 500, current_end)
        if batch.empty:
            break
        bars_list.append(batch)
        current_end = batch["time"].iloc[0] - timedelta(minutes=1)
    if not bars_list:
        return pd.DataFrame()
    return pd.concat(reversed(bars_list), ignore_index=True)


def run_walk_forward(
    symbol: str = "XAUUSD",
    timeframe: str = "M15",
    days_back: int = 180,
    min_bars: int = DEFAULT_LOOKBACK["M15"],
) -> WalkForwardResult:
    """Run walk-forward validation on historical data."""
    settings = load_settings()
    store = Store(settings.db_path)
    mcp = MCPClient(settings.mcp.url, settings.mcp.headers, settings.mcp.timeout_s)
    forecast = ForecastClient(settings.kronos_worker_url)
    clock = Clock.from_mcp(mcp)

    end_utc = _utc_midnight(0)
    start_utc = _utc_midnight(days_back)

    print(f"Fetching {days_back} days of {timeframe} bars for {symbol}...")
    bars = _collect_bars(mcp, clock, symbol, timeframe, start_utc, end_utc)
    print(f"Collected {len(bars)} bars")

    if len(bars) < min_bars * 2:
        raise ValueError(f"Insufficient bars: {len(bars)} < {min_bars * 2}")

    # Split into rolling windows
    horizon = DEFAULT_HORIZON[timeframe]
    step = horizon  # advance by horizon bars each step
    lookback = DEFAULT_LOOKBACK[timeframe]

    equity = 10000.0  # fixed equity for sizing consistency
    risk_config = RiskConfig()

    results = []
    for i in range(lookback, len(bars) - horizon, step):
        window = bars.iloc[i - lookback:i]
        if len(window) < lookback:
            continue

        try:
            result = run_analysis(
                mcp,
                clock,
                forecast,
                symbol,
                timeframe,
                equity,
                horizon=horizon,
                samples=25,
                risk_config=risk_config,
                bars=window,
            )
            signal = result.signal.side
            p_up = result.signal.p_up
            edge_atr = result.signal.edge_atr
            realised_close = bars.iloc[i + horizon]["close"] if i + horizon < len(bars) else None
            last_close = window["close"].iloc[-1]
            realised_move = (realised_close - last_close) / result.features.atr if realised_close else None

            results.append({
                "bar_idx": i,
                "bar_time": window["time"].iloc[-1].isoformat(),
                "signal": signal,
                "p_up": p_up,
                "edge_atr": edge_atr,
                "realised_move_atr": realised_move,
                "draft": result.draft.__dict__ if result.draft else None,
            })
        except Exception as exc:  # noqa: BLE001
            print(f"  Bar {i}: {exc}")

    # Compute baselines
    closes = bars["close"].values
    returns = np.diff(closes) / closes[:-1]
    always_long = np.sum(returns > 0) / len(returns) if len(returns) else 0
    always_short = np.sum(returns < 0) / len(returns) if len(returns) else 0
    buy_hold = (closes[-1] - closes[0]) / closes[0] if closes[0] else 0

    signal_counts = {}
    for r in results:
        signal_counts[r["signal"]] = signal_counts.get(r["signal"], 0) + 1

    baselines = {
        "always_long": {"win_rate": always_long, "total_return": buy_hold},
        "always_short": {"win_rate": always_short, "total_return": -buy_hold},
        "buy_hold": {"win_rate": 0.5, "total_return": buy_hold},
    }

    # Compute signal stats
    signal_returns = [r["realised_move_atr"] for r in results if r["realised_move_atr"] is not None]
    signal_stats = {
        "count": len(signal_returns),
        "win_rate": np.mean([x > 0 for x in signal_returns]) if signal_returns else 0,
        "avg_return_atr": np.mean(signal_returns) if signal_returns else 0,
        "expectancy_atr": np.mean([x for x in signal_returns if x > 0]) * np.mean([x > 0 for x in signal_returns])
                        + np.mean([x for x in signal_returns if x < 0]) * np.mean([x < 0 for x in signal_returns])
        if signal_returns else 0,
    }

    output = {
        "symbol": symbol,
        "timeframe": timeframe,
        "period": {"start": start_utc.isoformat(), "end": end_utc.isoformat()},
        "lookback": lookback,
        "horizon": horizon,
        "total_bars": len(bars),
        "analyses": len(results),
        "signals": signal_counts,
        "signal_stats": signal_stats,
        "baselines": baselines,
        "results": results,
    }

    out_path = ROOT / "data" / f"walkforward_{symbol}_{timeframe}_{days_back}d.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, default=str))

    print(f"Walk-forward complete: {len(results)} analyses")
    print(f"  Signals: {signal_counts}")
    print(f"  Signal expectancy: {signal_stats['expectancy_atr']:.4f} ATR")
    print(f"  Always long: {baselines['always_long']}")
    print(f"  Results saved to {out_path}")

    return WalkForwardResult(
        period_start=start_utc.isoformat(),
        period_end=end_utc.isoformat(),
        total_bars=len(bars),
        analyses=len(results),
        signals=signal_counts,
        baselines=baselines,
        output_path=str(out_path),
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--tf", default="M15")
    parser.add_argument("--days", type=int, default=180)
    args = parser.parse_args()

    run_walk_forward(args.symbol, args.tf, args.days)