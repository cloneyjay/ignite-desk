"""Agent engine — core decision loop."""

from __future__ import annotations

import uuid
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from backend.ignite.agent.config import AgentConfig
from backend.ignite.agent.orchestrator import Orchestrator
from backend.ignite.agent.synthesis import (
    FundamentalContext,
    TechnicalContext,
    AttributionContext,
    build_fundamental_context,
    build_technical_context,
    build_attribution_context,
    synthesise,
)
from backend.ignite.services.runtime import Runtime
from backend.ignite.services.execution import ExecutionError, execute_draft_autonomous


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


class AgentEngine:
    """Core agent decision engine."""

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

        symbols = self._get_symbols()
        decisions = []

        for symbol in symbols:
            try:
                decision = self.analyse_symbol(symbol, self.config.timeframe)
                decisions.append(decision)
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
        """Run analysis and synthesis for a single symbol."""
        # Check if we should use the new orchestrator (autonomous mode)
        if self.rt.config().operating_mode == "autonomous":
            return self._analyse_symbol_orchestrator(symbol, timeframe)

        # Legacy path for prepare/observe modes
        return self._analyse_symbol_legacy(symbol, timeframe)

    def _analyse_symbol_orchestrator(self, symbol: str, timeframe: str) -> "SymbolDecision":
        """Analyse using the new orchestrator with LLM tool calling."""
        orchestrator = Orchestrator(self.rt)
        decision = orchestrator.run_cycle(symbol, timeframe)

        # Persist decision
        self.rt.store.insert_agent_decision(
            {
                "id": uuid.uuid4().hex,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "symbol": symbol,
                "timeframe": timeframe,
                "analysis_id": decision.links.analysis_id,
                "signal_side": decision.action if decision.action in ("LONG", "SHORT") else "NONE",
                "p_up": 0.0,  # Not directly available from orchestrator
                "edge_atr": 0.0,
                "decision": decision.action,
                "confidence": decision.conviction,
                "reasoning": decision.thesis,
                "executed": False,
                "execution_error": None,
                "draft_id": decision.links.draft_id,
                "attribution_json": "{}",
                "fundamental_json": "{}",
                "technical_json": "{}",
                "risk_json": json.dumps(self.rt.risk_config().__dict__),
            }
        )

        # Execute if LONG/SHORT
        executed = False
        execution_error = None
        if decision.action in ("LONG", "SHORT"):
            from backend.ignite.services.gateway import OrderRequest
            req = OrderRequest(
                symbol=symbol,
                side="buy" if decision.action == "LONG" else "sell",
                lots=decision.risk.lots,
                sl=decision.risk.sl,
                tp=decision.risk.tp,
                decision_id=decision.links.decision_id,
            )
            result = self.rt.gateway.place(req)
            executed = result.ok
            if not result.ok:
                execution_error = f"{result.code}: {result.detail}"

        return SymbolDecision(
            symbol=symbol,
            timeframe=timeframe,
            action="ENTER" if decision.action in ("LONG", "SHORT") else "SKIP",
            signal_side=decision.action if decision.action in ("LONG", "SHORT") else "NONE",
            p_up=0.0,
            edge_atr=0.0,
            confidence=decision.conviction,
            reasoning=decision.thesis,
            draft_id=decision.links.draft_id,
            executed=executed,
            error=execution_error,
        )

    def _analyse_symbol_legacy(self, symbol: str, timeframe: str) -> "SymbolDecision":
        """Run analysis and synthesis for a single symbol (legacy path)."""
        # Run analysis graph
        from backend.ignite.analysis.graph import run_analysis
        from backend.ignite.analysis.risk import RiskConfig

        clock = self.rt.clock()
        equity = float(self.rt.account().get("equity") or 0.0)
        if equity <= 0:
            return SymbolDecision(
                symbol=symbol,
                timeframe=timeframe,
                action="ERROR",
                signal_side="NONE",
                p_up=0.0,
                edge_atr=0.0,
                confidence=0.0,
                reasoning="Account equity unavailable",
                draft_id=None,
                executed=False,
                error="No equity",
            )

        risk_config = RiskConfig(max_drift_atr=self.rt.settings.max_drift_atr)

        try:
            result = run_analysis(
                self.rt.mcp,
                clock,
                self.rt.forecast,
                symbol,
                timeframe,
                equity,
                risk_config=risk_config,
            )
            self.rt.store.save_analysis(result, self.rt.settings.draft_ttl_s)
        except Exception as exc:  # noqa: BLE001
            return SymbolDecision(
                symbol=symbol,
                timeframe=timeframe,
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

        # Build contexts
        fundamental = build_fundamental_context(self.rt, symbol)
        technical = build_technical_context(self.rt, symbol, timeframe)
        attribution = build_attribution_context(self.rt, result.analysis_id)

        # Synthesize decision
        decision = synthesise(
            forecast=result,
            fundamental=fundamental,
            technical=technical,
            attribution=attribution,
            risk=self.rt.risk_config(),
        )

        # Build reasoning
        reasons = list(result.signal.reasons)
        if decision.action == "ENTER":
            reasons.append(f"Draft created: {decision.reasoning}")
        elif decision.action == "SKIP":
            reasons.append(decision.reasoning)

        reasoning = ". ".join(reasons)

        # Execute if ENTER and draft is executable
        executed = False
        draft_id = None
        execution_error = None
        if decision.action == "ENTER" and result.draft and not result.draft.blocked:
            draft_id = result.draft_id
            try:
                execute_draft_autonomous(self.rt, draft_id)
                executed = True
            except ExecutionError as exc:
                execution_error = str(exc)
                reasons.append(f"Autonomous execution blocked: {exc}")

        self.rt.store.insert_agent_decision(
            {
                "id": uuid.uuid4().hex,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "symbol": symbol,
                "timeframe": timeframe,
                "analysis_id": result.analysis_id,
                "signal_side": result.signal.side.upper(),
                "p_up": result.signal.p_up,
                "edge_atr": result.signal.edge_atr,
                "decision": decision.action,
                "confidence": decision.confidence,
                "reasoning": ". ".join(reasons),
                "executed": executed,
                "execution_error": execution_error,
                "draft_id": draft_id,
                "attribution_json": json.dumps(attribution.__dict__),
                "fundamental_json": json.dumps(fundamental.__dict__),
                "technical_json": json.dumps(technical.__dict__),
                "risk_json": json.dumps(self.rt.risk_config().__dict__),
            }
        )

        return SymbolDecision(
            symbol=symbol,
            timeframe=timeframe,
            action=decision.action,
            signal_side=result.signal.side.upper(),
            p_up=result.signal.p_up,
            edge_atr=result.signal.edge_atr,
            confidence=decision.confidence,
            reasoning=reasoning,
            draft_id=draft_id,
            executed=executed,
            error=execution_error,
        )

    def _get_symbols(self) -> list[str]:
        if self.config.symbols:
            return list(self.config.symbols)
        return [s["symbol"] for s in self.rt.store.list_symbols()]

    def _is_enabled(self) -> bool:
        stored = self.rt.store.agent_config()
        if stored is not None:
            return bool(stored.get("enabled"))
        return self.config.enabled

    def _check_guards(self) -> "GuardResult":
        """Check global guards before running cycle."""
        from dataclasses import dataclass

        @dataclass
        class GuardResult:
            ok: bool
            reason: str | None = None

        if self.rt.kill_switch():
            return GuardResult(ok=False, reason="Kill switch enabled")

        config = self.rt.config()
        pnl = self.rt.ledger.daily()
        if not pnl.available:
            return GuardResult(ok=False, reason="daily_pnl_unavailable")
        if pnl.blocked:
            return GuardResult(
                ok=False, reason=f"Daily loss limit hit: {pnl.total_usd:.2f}"
            )

        # Check max concurrent positions
        positions = self.rt.store.agent_positions()
        if len(positions) >= config.max_concurrent_positions:
            return GuardResult(ok=False, reason="Max concurrent positions reached")

        return GuardResult(ok=True)