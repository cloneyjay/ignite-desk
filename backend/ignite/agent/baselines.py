"""Goal 5 (d): baseline comparisons — no-trade, follow-Kronos, random.

PRD Goal 5: results are compared against baselines — no-trade, always-follow-
Kronos with the same risk rules, and random with the same risk rules — after
spread, slippage and swap.

Honesty rules (PRD: "Do not claim profit, edge, or validated without evidence;
backtesting on history the model was trained on is leaky — a mechanics test
only"):

- The follow-Kronos baseline replays the desk's OWN journaled forecasts from
  the ``analyses`` table. Those were made live without future data, so the
  replay is out-of-sample by construction. No refitting, no signal research.
- The random baseline uses a seeded PRNG (seed journaled for reproducibility).
- All baselines use the desk's deterministic risk rule: SL = ``sl_atr`` x ATR,
  TP = ``tp_atr`` x ATR (``RiskConfig``) — the same rule the entry guard
  applies.
- Costs: per-bar spread (the broker-reported spread on each bar), fixed
  slippage at entry and on stop exits, and optional swap per night held.
  Conservative same-bar convention: if a bar touches both SL and TP, the trade
  exits at SL (fail closed).
- The report always carries a disclaimer: this is mechanics evidence for the
  autonomy ladder, not proof of edge.
"""

from __future__ import annotations

import random
from typing import Any

import pandas as pd

from backend.ignite.agent.evaluation import summarize_outcomes
from backend.ignite.analysis.risk import RiskConfig
from backend.ignite.market.bars import fetch_bars
from backend.ignite.services.runtime import Runtime

BARS_PER_DAY_M15 = 96
DEFAULT_MAX_HOLD_BARS = 96  # one trading day on M15


def _atr_series(bars: pd.DataFrame, period: int = 14) -> pd.Series:
    """Simple ATR (true-range rolling mean) aligned to the bars."""
    high, low, close = bars["high"], bars["low"], bars["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=1).mean()


def simulate_trade(
    bars: pd.DataFrame,
    entry_idx: int,
    side: str,
    sl_distance: float,
    tp_distance: float,
    point: float,
    spread_points: float | None = None,
    slippage_points: float = 2.0,
    swap_points_per_night: float = 0.0,
    minutes_per_bar: int = 15,
    max_hold_bars: int = DEFAULT_MAX_HOLD_BARS,
) -> dict[str, Any] | None:
    """Simulate one trade entered at the open of ``bars[entry_idx]``.

    SL/TP are checked from the entry bar onward. Returns
    ``{"r_multiple", "exit_reason", "bars_held", "exit_price"}`` or None when
    the entry is out of range. Costs in price units: spread + slippage at
    entry (long buys at ask), spread + slippage on stop and market exits for
    shorts (they buy back at ask), slippage on stop exits for longs.
    """
    if entry_idx < 0 or entry_idx >= len(bars) or sl_distance <= 0:
        return None
    entry_bar = bars.iloc[entry_idx]

    def spread_of(bar: pd.Series) -> float:
        pts = spread_points if spread_points is not None else float(
            bar.get("spread") or 0.0
        )
        return (pts + slippage_points) * point

    entry = float(entry_bar["open"])
    if side == "LONG":
        entry_eff = entry + spread_of(entry_bar)  # buy at ask
        sl_price = entry - sl_distance
        tp_price = entry + tp_distance
    else:
        entry_eff = entry  # sell at bid
        sl_price = entry + sl_distance
        tp_price = entry - tp_distance

    last_idx = min(entry_idx + max_hold_bars, len(bars) - 1)
    for i in range(entry_idx, last_idx + 1):
        bar = bars.iloc[i]
        sp = spread_of(bar)
        if side == "LONG":
            sl_hit = float(bar["low"]) <= sl_price
            tp_hit = float(bar["high"]) >= tp_price
        else:
            sl_hit = float(bar["high"]) >= sl_price
            tp_hit = float(bar["low"]) <= tp_price

        bars_held = i - entry_idx
        nights = (bars_held * minutes_per_bar) // 1440
        swap_cost = nights * swap_points_per_night * point

        if sl_hit:  # conservative: SL wins even when TP was touched same-bar
            if side == "LONG":
                exit_eff = sl_price - slippage_points * point
            else:
                exit_eff = sl_price + sp
            reason = "SL"
        elif tp_hit:
            if side == "LONG":
                exit_eff = tp_price  # sell at bid
            else:
                exit_eff = tp_price + sp  # buy back at ask
            reason = "TP"
        elif i == last_idx:
            # Timeout or end of data: forced market exit at close.
            if side == "LONG":
                exit_eff = float(bar["close"])
            else:
                exit_eff = float(bar["close"]) + sp
            reason = "TIMEOUT"
        else:
            continue

        move = (exit_eff - entry_eff) if side == "LONG" else (entry_eff - exit_eff)
        move -= swap_cost
        return {
            "r_multiple": round(move / sl_distance, 4),
            "exit_reason": reason,
            "bars_held": bars_held,
            "exit_price": float(bar["close"]),
        }
    return None  # unreachable, kept for safety


def _stats(rs: list[float], risk_usd: float) -> dict[str, Any]:
    rows = [{"executed": True, "r_multiple": r, "realised_pnl": r * risk_usd} for r in rs]
    stats = summarize_outcomes(rows)
    stats["est_usd"] = round(stats["sum_r"] * risk_usd, 2)
    return stats


def kronos_baseline(
    bars: pd.DataFrame,
    forecasts: list[dict[str, Any]],
    risk: RiskConfig,
    point: float,
    **cost_kwargs: Any,
) -> dict[str, Any]:
    """Replay the desk's journaled forecasts with the desk's risk rule.

    Direction: LONG when ``p_up >= 0.5``, else SHORT. SL/TP distances from the
    ATR the forecast itself reported (``risk.sl_atr`` / ``risk.tp_atr``). One
    open trade at a time (same as one symbol position).
    """
    rs: list[float] = []
    times = pd.to_datetime(bars["time"])
    open_until = -1
    for fc in forecasts:
        atr = fc.get("atr")
        if atr is None or float(atr) <= 0:
            continue
        created = pd.to_datetime(fc["created_at"])
        created = created.tz_localize(None) if created.tzinfo is None else created.tz_convert(None)
        # First bar whose open is at/after the forecast was published — the
        # first bar a market entry could realistically happen (no lookahead).
        idx = int(times.searchsorted(created))
        if idx <= open_until or idx >= len(bars):
            continue
        side = "LONG" if float(fc["p_up"] or 0.5) >= 0.5 else "SHORT"
        result = simulate_trade(
            bars, idx, side, risk.sl_atr * float(atr), risk.tp_atr * float(atr),
            point, **cost_kwargs,
        )
        if result is None:
            continue
        open_until = idx + result["bars_held"]
        rs.append(result["r_multiple"])
    return {"trades": len(rs), "r_multiples": rs}


def random_baseline(
    bars: pd.DataFrame,
    n_trades: int,
    risk: RiskConfig,
    point: float,
    seed: int = 42,
    atr_period: int = 14,
    **cost_kwargs: Any,
) -> dict[str, Any]:
    """Random direction, same risk rule, seeded PRNG (seed is journaled)."""
    rs: list[float] = []
    if n_trades <= 0 or len(bars) < atr_period + 2:
        return {"trades": 0, "seed": seed, "r_multiples": rs}
    atr = _atr_series(bars, atr_period)
    rng = random.Random(seed)
    last_idx = -1
    attempts = 0
    while len(rs) < n_trades and attempts < n_trades * 10:
        attempts += 1
        idx = rng.randrange(atr_period, len(bars) - 1)
        if idx <= last_idx:
            continue
        a = float(atr.iloc[idx])
        if a <= 0:
            continue
        side = "LONG" if rng.random() < 0.5 else "SHORT"
        result = simulate_trade(
            bars, idx, side, risk.sl_atr * a, risk.tp_atr * a, point, **cost_kwargs
        )
        if result is None:
            continue
        last_idx = idx + result["bars_held"]
        rs.append(result["r_multiple"])
    return {"trades": len(rs), "seed": seed, "r_multiples": rs}


def baseline_report(
    rt: Runtime,
    symbol: str,
    timeframe: str = "M15",
    lookback_days: int = 30,
    seed: int = 42,
    slippage_points: float = 2.0,
    swap_points_per_night: float = 0.0,
) -> dict[str, Any]:
    """Compare the agent's realised results against the three baselines.

    Primary metric: R multiples after costs. USD figures use the desk's
    ``risk_pct`` against a reference equity (live account equity when
    available, else 10,000) — they are estimates, not claims.
    """
    risk = rt.risk_config()
    spec = rt.spec(symbol)
    minutes_per_bar = {"M5": 5, "M15": 15, "M30": 30, "H1": 60}.get(timeframe, 15)
    count = min(lookback_days * (1440 // minutes_per_bar), 5000)
    bars = fetch_bars(rt.mcp, rt.clock(), symbol, timeframe, count)

    cost_kwargs = {
        "point": spec.point,
        "slippage_points": slippage_points,
        "swap_points_per_night": swap_points_per_night,
        "minutes_per_bar": minutes_per_bar,
    }

    until = str(bars.iloc[-1]["time"])
    since = str(bars.iloc[0]["time"])
    forecasts = rt.store.analyses_between(symbol, timeframe, since, until)
    outcomes = rt.store.agent_position_outcomes(limit=500)

    equity = float((rt.account() or {}).get("equity") or 0.0) or 10_000.0
    risk_usd = equity * risk.risk_pct

    agent_rs = [
        float(r["r_multiple"])
        for r in outcomes
        if r.get("symbol") == symbol and r.get("executed") and r.get("r_multiple") is not None
    ]
    kronos = kronos_baseline(bars, forecasts, risk, **cost_kwargs)
    rnd = random_baseline(bars, len(kronos["r_multiples"]), risk, seed=seed, **cost_kwargs)

    report = {
        "symbol": symbol,
        "timeframe": timeframe,
        "window": {"since": since, "until": until},
        "assumptions": {
            "sl_atr": risk.sl_atr,
            "tp_atr": risk.tp_atr,
            "spread": "per-bar broker spread",
            "slippage_points": slippage_points,
            "swap_points_per_night": swap_points_per_night,
            "same_bar_rule": "SL wins (conservative)",
            "risk_usd_per_r": round(risk_usd, 2),
            "random_seed": seed,
        },
        "agent": _stats(agent_rs, risk_usd) | {"source": "journaled outcomes"},
        "no_trade": {"sum_r": 0.0, "est_usd": 0.0, "note": "the bar to beat"},
        "kronos": _stats(kronos["r_multiples"], risk_usd) | {"forecasts": len(forecasts)},
        "random": _stats(rnd["r_multiples"], risk_usd)
        | {"n_trades": rnd["trades"], "seed": seed},
        "disclaimer": (
            "Mechanics evidence only (PRD Goal 5): journaled forecasts and "
            "conservative cost assumptions. Not proof of edge; do not promote "
            "or tune thresholds on these numbers without out-of-sample review."
        ),
    }
    rt.store.audit("agent", "baseline_report", {"symbol": symbol}, "ok")
    rt.store.append_agent_event(
        "evaluation.baseline_report",
        severity="info",
        symbol=symbol,
        payload={k: v for k, v in report.items() if k != "window"},
    )
    return report
