"""Goal 5 evaluation tests: decision→outcome linkage, summaries, feedback.

PRD Goal 5: journaled decisions are linked to their outcomes (R multiple,
MAE/MFE), and the LLM receives compact feedback — not raw history.
"""

from __future__ import annotations

import json

from backend.ignite.agent.baselines import baseline_report
from backend.ignite.agent.evaluation import (
    compact_feedback,
    harness_fingerprint,
    summarize_outcomes,
)
from backend.ignite.agent.engine import AgentEngine
from backend.ignite.store.db import Store, utc_now


def _seed_analysis(store: Store, analysis_id: str = "a1") -> None:
    store._conn.execute(
        """INSERT INTO analyses (id, created_at, symbol, timeframe, last_bar_time,
        lookback, horizon, samples, model_id, infer_s, atr, p_up, edge, edge_atr,
        dispersion, signal, signal_version, risk_version, features_json, reasons_json)
        VALUES (?,'2026-01-01T00:00:00+00:00','XAUUSD','M15','t',1,1,1,'m',0.1,
        2.5,0.6,1.0,0.5,0.1,'LONG','v1','v1','{}','[]')""",
        (analysis_id,),
    )
    store._conn.commit()


def _seed_decision(store: Store, decision_id: str, executed: bool = True) -> None:
    store.insert_agent_decision(
        {
            "id": decision_id,
            "created_at": "2026-01-01T01:00:00+00:00",
            "symbol": "XAUUSD",
            "timeframe": "M15",
            "analysis_id": "a1",
            "signal_side": "LONG",
            "p_up": 0.6,
            "edge_atr": 0.5,
            "decision": "LONG",
            "confidence": 0.7,
            "reasoning": "test thesis",
            "executed": executed,
            "execution_error": None,
            "draft_id": None,
            "attribution_json": json.dumps({"model": "test-model"}),
            "fundamental_json": "{}",
            "technical_json": "{}",
            "risk_json": "{}",
        }
    )


def test_position_links_to_decision_via_order_ticket(rt):
    """The full chain: decision → order(position_id=ticket) → agent_positions."""
    store = rt.store
    _seed_analysis(store)
    _seed_decision(store, "dec1")
    store.begin_order("dec1", "XAUUSD", "buy", 0.01, 3920.0, 3950.0)
    store.update_order("dec1", state="filled", position_id="900001")

    assert store.decision_id_for_ticket("900001") == "dec1"
    assert store.decision_id_for_ticket("no-such-ticket") is None

    # First sync writes the linkage; second sync preserves it
    store.upsert_agent_position(
        {
            "ticket": "900001",
            "symbol": "XAUUSD",
            "side": "buy",
            "entry_price": 3930.0,
            "volume": 0.01,
            "opened_at": utc_now(),
            "decision_id": store.decision_id_for_ticket("900001"),
        }
    )
    store.upsert_agent_position(
        {
            "ticket": "900001",
            "symbol": "XAUUSD",
            "side": "buy",
            "entry_price": 3930.0,
            "volume": 0.01,
            "opened_at": utc_now(),
        }
    )
    assert store.agent_position("900001")["decision_id"] == "dec1"

    # Close the trade with an outcome; the join surfaces it
    store.close_agent_position("900001", "TP", 45.0, 1.5)
    rows = store.agent_position_outcomes()
    assert len(rows) == 1
    assert rows[0]["decision_id"] == "dec1"
    assert rows[0]["r_multiple"] == 1.5
    assert rows[0]["realised_pnl"] == 45.0


def test_summarize_outcomes_math():
    rows = [
        {"executed": True, "r_multiple": 1.5, "realised_pnl": 45.0},
        {"executed": True, "r_multiple": -1.0, "realised_pnl": -30.0},
        {"executed": True, "r_multiple": -1.0, "realised_pnl": -30.0},
        {"executed": True, "r_multiple": None, "realised_pnl": None},  # open
        {"executed": False, "r_multiple": None, "realised_pnl": None},  # blocked
    ]
    stats = summarize_outcomes(rows)
    assert stats["closed"] == 3
    assert stats["open"] == 1
    assert stats["unexecuted"] == 1
    assert stats["wins"] == 1
    assert stats["losses"] == 2
    assert stats["win_rate"] == 1 / 3
    assert stats["sum_r"] == -0.5
    assert stats["avg_r"] == -0.5 / 3
    assert stats["total_realised_usd"] == -15.0


def test_summarize_outcomes_empty():
    stats = summarize_outcomes([])
    assert stats["closed"] == 0
    assert stats["avg_r"] is None
    assert stats["win_rate"] is None


def test_harness_fingerprint_changes_on_model_or_prompt_change():
    base = harness_fingerprint("nvidia", "m1", "prompt", ["a", "b"])
    assert base == harness_fingerprint("nvidia", "m1", "prompt", ["b", "a"])
    assert base != harness_fingerprint("nvidia", "m2", "prompt", ["a", "b"])
    assert base != harness_fingerprint("nvidia", "m1", "other prompt", ["a", "b"])
    assert base != harness_fingerprint("nvidia", "m1", "prompt", ["a", "b", "c"])


def test_engine_resets_evaluation_to_shadow_on_model_change(rt):
    """PRD Goal 5: a model change resets evaluation to shadow."""
    from backend.ignite.llm.client import LLMResult

    class FakeLLM:
        def __init__(self):
            self.model = "model-a"

        def complete(self, messages, tools=None, tool_choice="auto", **kwargs):
            return LLMResult(
                text=json.dumps({
                    "symbol": "XAUUSD", "timeframe": "M15", "action": "NO_TRADE",
                    "conviction": 0.0, "thesis": "t", "evidence": [],
                    "failed_conditions": [],
                    "entry": {"type": "market", "price": 0.0},
                    "risk": {"lots": 0.0, "sl": 0.0, "tp": 0.0},
                    "expected_rr": 0.0, "invalidate_if": [],
                    "links": {"analysis_id": None, "draft_id": None,
                              "decision_id": "d"},
                }),
                provider="fake",
                model=self.model,
                latency_ms=1,
            )

    rt.config_service.update({"enabled": True, "operating_mode": "autonomous", "execution_mode": "live"})
    llm = FakeLLM()
    rt.llm = llm  # type: ignore[method-assign]
    rt.realised_override = 0.0

    engine = AgentEngine(rt, rt.config())
    engine.run_cycle()
    assert rt.config().execution_mode == "live"  # first sight only pins

    llm.model = "model-b"
    engine.run_cycle()
    assert rt.config().execution_mode == "shadow"
    assert rt.store.setting("agent_eval_fingerprint") != ""


def test_compact_feedback_mentions_stats_and_trades(rt):
    store = rt.store
    _seed_analysis(store)
    _seed_decision(store, "dec1")
    store.begin_order("dec1", "XAUUSD", "buy", 0.01)
    store.update_order("dec1", state="filled", position_id="900001")
    store.upsert_agent_position(
        {
            "ticket": "900001",
            "symbol": "XAUUSD",
            "side": "buy",
            "entry_price": 3930.0,
            "volume": 0.01,
            "opened_at": utc_now(),
            "decision_id": "dec1",
        }
    )
    store.close_agent_position("900001", "TP", 45.0, 1.5)

    text = compact_feedback(rt)
    assert "win rate" in text
    assert "sum R" in text
    assert "1.50" in text  # the winning trade's R multiple
    assert "test thesis" in text


def test_compact_feedback_empty_desk(rt):
    assert "no entry decisions" in compact_feedback(rt)


def test_compact_feedback_includes_cached_baseline(rt):
    """The daily evaluation job's cached summary reaches the LLM's context pack."""
    rt.store.set_setting(
        "agent_baseline_summary",
        json.dumps({
            "XAUUSD": {
                "created_at": "2026-11-16T22:30:00+00:00",
                "agent_sum_r": 0.4,
                "kronos_sum_r": 1.2,
                "random_sum_r": -0.8,
            }
        }),
    )
    text = compact_feedback(rt)
    assert "Baseline (XAUUSD" in text
    assert "you +0.40R" in text
    assert "follow-Kronos +1.20R" in text
    assert "random -0.80R" in text


def test_baseline_report_caches_summary_for_feedback(rt):
    report = baseline_report(rt, "XAUUSD", lookback_days=2)
    cached = json.loads(rt.store.setting("agent_baseline_summary") or "{}")
    assert "XAUUSD" in cached
    assert cached["XAUUSD"]["agent_sum_r"] == report["agent"]["sum_r"]
