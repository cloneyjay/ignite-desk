"""Goal 5 (d) baseline tests: simulation math, baselines, report.

PRD Goal 5: compare results against no-trade, always-follow-Kronos, and
random baselines with the same risk rules, after spread/slippage/swap.
Conservative same-bar convention: SL wins when both levels are touched.
"""

from __future__ import annotations

import json

import pandas as pd

from backend.ignite.agent.baselines import baseline_report, kronos_baseline, random_baseline, simulate_trade
from backend.ignite.analysis.risk import RiskConfig
from backend.ignite.store.db import utc_now

POINT = 0.01  # XAUUSD


def _bars(prices: list[float], spread: float = 10.0, span: float = 0.5) -> pd.DataFrame:
    """Build OHLC bars where every bar spans [price - span, price + span]."""
    rows = []
    t = pd.Timestamp("2026-01-05 00:00")
    for p in prices:
        rows.append({
            "time": t,
            "open": p,
            "high": p + span,
            "low": p - span,
            "close": p,
            "volume": 100.0,
            "spread": spread,
        })
        t += pd.Timedelta(minutes=15)
    return pd.DataFrame(rows)


def test_simulate_long_hits_tp():
    # Entry 100, SL 99 (1.0 away), TP 102 (2.0 away); bar 2 rallies to 102.5
    bars = _bars([100.0, 100.1, 100.1])
    bars.loc[2, "high"] = 102.5
    result = simulate_trade(bars, 0, "LONG", 1.0, 2.0, POINT, slippage_points=0.0)
    assert result["exit_reason"] == "TP"
    # entry at ask = 100 + spread/2 = 100.05, TP price = entry_eff + 2 = 102.05, exit at TP - spread/2 = 102.00
    expected_r = (102.00 - 100.05) / 1.0
    assert result["r_multiple"] == round(expected_r, 4)


def test_simulate_long_hits_sl():
    bars = _bars([100.0, 98.5])
    result = simulate_trade(bars, 0, "LONG", 1.0, 2.0, POINT, slippage_points=0.0)
    assert result["exit_reason"] == "SL"
    # entry at ask = 100 + spread/2 = 100.05, SL price = 99.05, exit at SL - spread/2 = 99.00
    expected_r = (99.00 - 100.05) / 1.0
    assert result["r_multiple"] == round(expected_r, 4)


def test_simulate_same_bar_sl_wins_conservative():
    """A bar touching both SL and TP exits at SL (fail closed, PRD Invariant #5)."""
    bars = _bars([100.0, 100.0])
    bars.loc[1, "low"] = 98.9   # touches SL (entry 100, SL 99)
    bars.loc[1, "high"] = 102.5  # also touches TP (102)
    result = simulate_trade(bars, 0, "LONG", 1.0, 2.0, POINT, slippage_points=0.0)
    assert result["exit_reason"] == "SL"


def test_simulate_short_costs_spread_on_exit():
    bars = _bars([100.0, 102.5])
    result = simulate_trade(bars, 0, "SHORT", 1.0, 2.0, POINT, slippage_points=0.0)
    assert result["exit_reason"] == "SL"
    # short entry at bid = 100 - spread/2 = 99.95, SL price = 100.95, exit at SL + spread/2 = 101.00
    expected_r = (99.95 - 101.00) / 1.0
    assert result["r_multiple"] == round(expected_r, 4)


def test_simulate_timeout_exits_at_close():
    bars = _bars([100.0, 100.0, 100.0, 100.0])
    result = simulate_trade(bars, 0, "LONG", 1.0, 2.0, POINT, slippage_points=0.0, max_hold_bars=2)
    assert result["exit_reason"] == "TIMEOUT"
    assert result["bars_held"] == 2


def test_kronos_baseline_follows_p_up():
    """Direction follows the journaled forecast: p_up >= 0.5 is LONG."""
    bars = _bars([100.0, 100.0, 100.0, 100.0, 100.0])
    bars.loc[2, "high"] = 103.5  # the long's TP (3.0 x ATR = 103) is touched on bar 2
    bars.loc[4, "close"] = 100.2  # the short times out losing
    forecasts = [
        {"created_at": "2026-01-05T00:00:00+00:00", "p_up": 0.7, "atr": 1.0},
        {"created_at": "2026-01-05T01:00:00+00:00", "p_up": 0.2, "atr": 1.0},
    ]
    result = kronos_baseline(
        bars, forecasts, RiskConfig(), POINT,
        spread_points=0.0, slippage_points=0.0,
    )
    assert result["trades"] == 2
    assert result["r_multiples"][0] > 0  # long won (TP touched on bar 2)
    assert result["r_multiples"][1] < 0  # short lost


def test_random_baseline_is_reproducible():
    bars = _bars([100.0 + 0.1 * i for i in range(60)])
    kwargs = dict(spread_points=0.0, slippage_points=0.0)
    a = random_baseline(bars, 5, RiskConfig(), POINT, seed=7, **kwargs)
    b = random_baseline(bars, 5, RiskConfig(), POINT, seed=7, **kwargs)
    c = random_baseline(bars, 5, RiskConfig(), POINT, seed=8, **kwargs)
    assert a["r_multiples"] == b["r_multiples"]
    assert a["seed"] == 7 and c["seed"] == 8


def test_baseline_report_end_to_end(rt):
    """Full report: agent R multiples vs the three baselines, journaled."""
    # Journaled agent outcome: one winning trade
    rt.store._conn.execute(
        """INSERT INTO analyses (id, created_at, symbol, timeframe, last_bar_time,
        lookback, horizon, samples, model_id, infer_s, atr, p_up, edge, edge_atr,
        dispersion, signal, signal_version, risk_version, features_json, reasons_json)
        VALUES ('a1','2026-01-05T00:00:00+00:00','XAUUSD','M15','t',1,1,1,'m',0.1,
        2.5,0.6,1.0,0.5,0.1,'LONG','v1','v1','{}','[]')"""
    )
    rt.store.insert_agent_decision({
        "id": "dec1", "created_at": "2026-01-05T01:00:00+00:00",
        "symbol": "XAUUSD", "timeframe": "M15", "analysis_id": "a1",
        "signal_side": "LONG", "p_up": 0.6, "edge_atr": 0.5, "decision": "LONG",
        "confidence": 0.7, "reasoning": "t", "executed": True,
        "execution_error": None, "draft_id": None,
        "attribution_json": "{}", "fundamental_json": "{}",
        "technical_json": "{}", "risk_json": "{}",
    })
    rt.store.begin_order("dec1", "XAUUSD", "buy", 0.01)
    rt.store.update_order("dec1", state="filled", position_id="900001")
    rt.store.upsert_agent_position({
        "ticket": "900001", "symbol": "XAUUSD", "side": "buy",
        "entry_price": 3930.0, "volume": 0.01, "opened_at": utc_now(),
        "decision_id": "dec1",
    })
    rt.store.close_agent_position("900001", "TP", 45.0, 1.5)

    report = baseline_report(
        rt, "XAUUSD", "M15", lookback_days=2,
        slippage_points=2.0, swap_points_per_night=5.0,
    )

    assert report["agent"]["sum_r"] == 1.5
    assert report["no_trade"]["sum_r"] == 0.0
    assert "win_rate" in report["kronos"]
    assert "seed" in report["random"]
    assert report["assumptions"]["same_bar_rule"] == "SL wins (conservative)"
    assert "Mechanics evidence only" in report["disclaimer"]

    # Journaled for the autonomy ladder's evidence trail (PRD Invariant #9)
    events = rt.store.agent_events(limit=10)
    assert any(e["kind"] == "evaluation.baseline_report" for e in events)
    audits = rt.store.get_audit_log(limit=5)
    assert any(a["action"] == "baseline_report" for a in audits)
