"""Agent engine — scheduled cycle driver for the LLM trader.

The LLM (via ``Orchestrator``/``LLMHarness``) is the only decision maker, in every
operating mode. The mode only decides what happens to the decision:

* ``observe`` / ``prepare`` — the decision is journaled, nothing is executed
  (shadow evaluation of the LLM on live data).
* ``autonomous`` — a LONG/SHORT decision with a matching draft is executed through
  ``execute_draft_autonomous`` and its full guard chain.

The engine also owns the cycle-level circuit breakers (daily loss, position cap,
consecutive-loss streak) which the LLM cannot influence.
"""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from backend.ignite.agent.config import AgentConfig
from backend.ignite.agent.decision import Decision
from backend.ignite.agent.evaluation import harness_fingerprint
from backend.ignite.agent.orchestrator import SYSTEM_PROMPT, Orchestrator
from backend.ignite.services.execution import ExecutionError, execute_draft_autonomous
from backend.ignite.services.runtime import Runtime

LOSS_STREAK_LOOKBACK_DAYS = 7


@dataclass
class SymbolDecision:
    symbol: str
    timeframe: str
    action: Literal["ENTER", "MANAGE", "SKIP", "ERROR"]
    signal_side: Literal["LONG", "SHORT", "NONE"]
    p_up: float
    edge_atr: float
    confidence: float
    reasoning: str
    draft_id: str | None
    executed: bool
    error: str | None


@dataclass
class CycleResult:
    cycle_id: str
    started_at: str
    completed_at: str
    symbol_decisions: list["SymbolDecision"]


@dataclass
class GuardResult:
    ok: bool
    reason: str | None = None


_SIDE_FOR_ACTION = {"LONG": "buy", "SHORT": "sell"}


def _risk_mismatch(draft: dict[str, Any], risk: Any) -> str | None:
    """Compare draft lots/SL/TP against the decision's stated risk.

    Fail closed: a missing draft number or a difference beyond float noise
    is a mismatch — the draft that gets executed must be the decision's risk.
    """
    for field, value in (("lots", risk.lots), ("sl", risk.sl), ("tp", risk.tp)):
        draft_value = draft.get(field)
        if draft_value is None:
            return f"decision_draft_mismatch: draft {field} missing"
        if float(draft_value) != float(value) and not math.isclose(
            float(draft_value), float(value), rel_tol=1e-9, abs_tol=1e-9
        ):
            return (
                f"decision_draft_mismatch: decision risk {field}={value} "
                f"but draft {field}={draft_value}"
            )
    return None


class AgentEngine:
    """Drives scheduled LLM trading cycles."""

    def __init__(self, rt: Runtime, config: "AgentConfig") -> None:
        self.rt = rt
        self.config = config

    def run_cycle(self) -> "CycleResult":
        """Run one analysis cycle across all watchlist symbols."""
        started_at = datetime.now(timezone.utc).isoformat()
        cycle_id = uuid.uuid4().hex

        if not self._is_enabled():
            return CycleResult(
                cycle_id=cycle_id,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).isoformat(),
                symbol_decisions=[],
            )

        guards = self._check_guards()
        if not guards.ok:
            blocked_at = datetime.now(timezone.utc).isoformat()
            self.rt.store.set_setting("agent_last_guard", guards.reason or "Trading guard blocked the cycle")
            self.rt.store.set_setting("agent_last_cycle", blocked_at)
            self.rt.events.publish(
                "agent.cycle.blocked",
                {"cycle_id": cycle_id, "reason": guards.reason},
            )
            return CycleResult(
                cycle_id=cycle_id,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).isoformat(),
                symbol_decisions=[],
            )

        decisions: list[SymbolDecision] = []
        for symbol in self._get_symbols():
            try:
                decisions.append(self.analyse_symbol(symbol, self.config.timeframe))
            except Exception as exc:  # noqa: BLE001
                decisions.append(
                    SymbolDecision(
                        symbol=symbol,
                        timeframe=self.config.timeframe,
                        action="ERROR",
                        signal_side="NONE",
                        p_up=0.0,
                        edge_atr=0.0,
                        confidence=0.0,
                        reasoning=f"Analysis failed: {exc}",
                        draft_id=None,
                        executed=False,
                        error=str(exc),
                    )
                )

        completed_at = datetime.now(timezone.utc).isoformat()
        self.rt.store.set_setting("agent_last_cycle", completed_at)
        self.rt.events.publish(
            "agent.cycle.completed",
            {
                "cycle_id": cycle_id,
                "started_at": started_at,
                "completed_at": completed_at,
                "decisions": len(decisions),
            },
        )
        return CycleResult(
            cycle_id=cycle_id,
            started_at=started_at,
            completed_at=completed_at,
            symbol_decisions=decisions,
        )

    def analyse_symbol(self, symbol: str, timeframe: str) -> "SymbolDecision":
        """Ask the LLM for a decision on one symbol, journal it, execute if allowed."""
        mode = self.rt.config().operating_mode
        orchestrator = Orchestrator(self.rt)
        decision = orchestrator.run_cycle(symbol, timeframe)
        meta = orchestrator.last_run

        # Goal 5: pin the decision harness (provider, model, prompt, tools).
        # A change resets evaluation to shadow — the measured stats no longer
        # describe the current trader.
        fingerprint = harness_fingerprint(
            meta.get("provider"),
            meta.get("model"),
            SYSTEM_PROMPT,
            self.rt.tool_registry.names(),
        )
        previous_fingerprint = self.rt.store.setting("agent_eval_fingerprint")
        if previous_fingerprint is None:
            self.rt.store.set_setting("agent_eval_fingerprint", fingerprint)
        elif previous_fingerprint != fingerprint:
            self.rt.auto_demote(
                "harness change: model/prompt/tools", to_shadow=True
            )
            self.rt.store.set_setting("agent_eval_fingerprint", fingerprint)

        is_entry = decision.action in ("LONG", "SHORT")
        p_up, edge_atr = self._signal_numbers(decision.links.analysis_id)

        executed = False
        execution_error: str | None = None
        if is_entry:
            if mode != "autonomous":
                execution_error = f"shadow: {mode} mode does not execute"
            else:
                execution_error = self._validate_entry(decision)
                if execution_error is None:
                    try:
                        execute_draft_autonomous(self.rt, str(decision.links.draft_id))
                        executed = True
                    except ExecutionError as exc:
                        execution_error = f"{exc.code}: {exc.detail}"

        self.rt.store.insert_agent_decision(
            {
                "id": decision.links.decision_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "symbol": symbol,
                "timeframe": timeframe,
                "analysis_id": decision.links.analysis_id,
                "signal_side": decision.action if is_entry else "NONE",
                "p_up": p_up,
                "edge_atr": edge_atr,
                "decision": decision.action,
                "confidence": decision.conviction,
                "reasoning": decision.thesis,
                "executed": executed,
                "execution_error": execution_error,
                "draft_id": decision.links.draft_id,
                "attribution_json": json.dumps(
                    {
                        "provider": meta.get("provider"),
                        "model": meta.get("model"),
                        "operating_mode": mode,
                        "execution_mode": self.rt.config().execution_mode,
                        "tools_used": meta.get("tools_used", []),
                        "invalidate_if": decision.invalidate_if,
                        "evidence": decision.evidence,
                        "expected_rr": decision.expected_rr,
                    }
                ),
                "fundamental_json": "{}",
                "technical_json": "{}",
                "risk_json": json.dumps(self.rt.risk_config().__dict__),
            }
        )

        return SymbolDecision(
            symbol=symbol,
            timeframe=timeframe,
            action="ENTER" if is_entry else "SKIP",
            signal_side=decision.action if is_entry else "NONE",  # type: ignore[arg-type]
            p_up=p_up,
            edge_atr=edge_atr,
            confidence=decision.conviction,
            reasoning=decision.thesis,
            draft_id=decision.links.draft_id,
            executed=executed,
            error=execution_error,
        )

    # ------------------------------------------------------------ entry checks

    def _validate_entry(self, decision: Decision) -> str | None:
        """The LLM's stated decision must match the draft it wants executed.

        Side, symbol, lots, SL and TP are all checked: the numbers that reach
        the broker must be the numbers the decision states (PRD Invariant #3/#6).
        Returns an error string (fail closed) or None when consistent.
        """
        draft_id = decision.links.draft_id
        if draft_id is None or draft_id == "":
            return "no draft: autonomous execution requires a draft"
        draft = self.rt.store.get_draft(draft_id)
        if draft is None:
            return f"draft_not_found: {draft_id}"
        expected = _SIDE_FOR_ACTION[decision.action]
        if str(draft.get("side", "")).lower() != expected:
            return (
                f"decision_draft_mismatch: decision {decision.action} "
                f"but draft side is {draft.get('side')}"
            )
        if draft.get("symbol") not in (None, decision.symbol):
            return "decision_draft_mismatch: symbol differs"
        risk_error = _risk_mismatch(draft, decision.risk)
        if risk_error is not None:
            return risk_error
        return None

    def _signal_numbers(self, analysis_id: str | None) -> tuple[float, float]:
        """Kronos numbers the LLM saw, for the journal. 0.0 when unavailable."""
        if not analysis_id:
            return 0.0, 0.0
        try:
            row = self.rt.store.get_analysis(analysis_id) or {}
        except Exception:  # noqa: BLE001 - journal only
            return 0.0, 0.0
        return float(row.get("p_up") or 0.0), float(row.get("edge_atr") or 0.0)

    # ------------------------------------------------------------------ config

    def _get_symbols(self) -> list[str]:
        if self.config.symbols:
            return list(self.config.symbols)
        return [s["symbol"] for s in self.rt.store.list_symbols()]

    def _is_enabled(self) -> bool:
        stored = self.rt.store.agent_config()
        if stored is not None:
            return bool(stored.get("enabled"))
        return self.config.enabled

    # ---------------------------------------------------------------- breakers

    def _check_guards(self) -> GuardResult:
        """Cycle-level circuit breakers. The LLM has no tool to change these."""
        if self.rt.kill_switch():
            return GuardResult(ok=False, reason="Kill switch enabled")

        config = self.rt.config()
        pnl = self.rt.ledger.daily()
        if not pnl.available:
            return GuardResult(ok=False, reason="daily_pnl_unavailable")
        if pnl.blocked:
            reason = f"Daily loss limit hit: {pnl.total_usd:.2f}"
            # Goal 5: a drawdown that trips the breaker steps autonomy down.
            self.rt.auto_demote(reason)
            return GuardResult(ok=False, reason=reason)

        positions = self.rt.store.agent_positions()
        if len(positions) >= config.max_concurrent_positions:
            return GuardResult(ok=False, reason="Max concurrent positions reached")

        streak = self._loss_streak_guard(config.max_consecutive_losses)
        if not streak.ok:
            # Goal 5: a loss streak steps autonomy down one ladder level.
            self.rt.auto_demote(streak.reason)
            return streak

        return GuardResult(ok=True)

    def _loss_streak_guard(self, limit: int) -> GuardResult:
        """Stop trading after ``limit`` consecutive losing round-trips.

        Fails closed when history is unavailable. ``limit <= 0`` disables it.
        """
        if limit <= 0:
            return GuardResult(ok=True)
        from backend.ignite.services.broker import closed_trades

        try:
            now = datetime.now(timezone.utc)
            trades = closed_trades(
                self.rt.mcp,
                self.rt.clock(),
                now - timedelta(days=LOSS_STREAK_LOOKBACK_DAYS),
                now,
            )
        except Exception as exc:  # noqa: BLE001 - a guard must fail closed
            return GuardResult(ok=False, reason=f"loss_streak_unavailable: {exc}")
        return loss_streak_result(trades, limit)


def loss_streak_result(trades: list[dict[str, Any]], limit: int) -> GuardResult:
    """Pure helper: newest-first consecutive losses vs. ``limit``."""
    ordered = sorted(
        trades, key=lambda t: str(t.get("close_time") or ""), reverse=True
    )
    streak = 0
    for trade in ordered:
        if float(trade.get("net") or 0.0) < 0:
            streak += 1
        else:
            break
    if streak >= limit:
        return GuardResult(
            ok=False, reason=f"Loss streak: {streak} consecutive losing trades"
        )
    return GuardResult(ok=True)
