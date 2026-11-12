"""Agent engine — core decision loop."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from backend.ignite.agent.config import AgentConfig
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

        if not self.config.enabled:
            return CycleResult(
                cycle_id=cycle_id,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).isoformat(),
                symbol_decisions=[],
            )

        guards = self._check_guards()
        if not guards.ok:
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
        return CycleResult(
            cycle_id=cycle_id,
            started_at=started_at,
            completed_at=completed_at,
            symbol_decisions=decisions,
        )

    def analyse_symbol(self, symbol: str, timeframe: str) -> "SymbolDecision":
        """Run analysis and synthesis for a single symbol."""
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
        if decision.action == "ENTER" and result.draft and not result.draft.blocked:
            draft_id = result.draft_id
            # Note: Actual execution goes through confirmation flow
            # For agent mode, we'd auto-confirm here
            executed = True

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
            error=None,
        )

    def _get_symbols(self) -> list[str]:
        if self.config.symbols:
            return list(self.config.symbols)
        return [s["symbol"] for s in self.rt.store.list_symbols()]

    def _check_guards(self) -> "GuardResult":
        """Check global guards before running cycle."""
        from dataclasses import dataclass

        @dataclass
        class GuardResult:
            ok: bool
            reason: str | None = None

        if self.rt.kill_switch():
            return GuardResult(ok=False, reason="Kill switch enabled")

        # Check daily loss limit
        try:
            from backend.ignite.services.broker import realised_pnl_today
            pnl = realised_pnl_today(self.rt.mcp, self.rt.clock())
            equity = float(self.rt.account().get("equity") or 0.0)
            if equity > 0 and pnl < -equity * self.config.daily_loss_limit_pct:
                return GuardResult(ok=False, reason=f"Daily loss limit hit: {pnl:.2f}")
        except Exception:
            pass

        # Check max concurrent positions
        positions = self.rt.store.agent_positions()
        if len(positions) >= self.config.max_concurrent_positions:
            return GuardResult(ok=False, reason="Max concurrent positions reached")

        return GuardResult(ok=True)