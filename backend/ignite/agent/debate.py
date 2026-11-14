"""Multi-agent trading debate system (TradingAgents pattern).

Implements a structured debate between specialised agents before any trade
decision is finalised:

1. **Researcher** (bull/bear) — analyses Kronos forecast, market structure,
   news, and memory to argue for/against a directional bias.
2. **Strategist** — proposes entry/SL/TP and position size based on research.
3. **Risk Manager** — validates against daily loss limit, kill switch,
   position caps, drawdown, and spread guards.
4. **Executor** — makes the final go/no-go decision and drafts the order.

All agents are pure functions over a shared context — deterministic given the
same inputs, fully testable without an LLM. The LLM is only used to colour the
narrative; the decision logic is deterministic guards.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import uuid

from backend.ignite.agent.kronos_signal import KronosSignal, analyse_paths
from backend.ignite.agent.analyst import Analyst
from backend.ignite.agent.execution_desk import ExecutionDesk
from backend.ignite.agent.session import SessionGuard
from backend.ignite.agent.intelligence.regime import RegimeClassifier
from backend.ignite.agent.intelligence.risk_intel import RiskIntel
from backend.ignite.agent.intelligence.market_intel import MarketIntel
from backend.ignite.agent.reasoning.planner import Planner
from backend.ignite.agent.reasoning.reflector import Reflector
from backend.ignite.services.runtime import Runtime


@dataclass(frozen=True)
class DebateContext:
    """Shared context passed between debate agents."""

    symbol: str
    timeframe: str
    paths: np.ndarray  # Kronos forecast paths (samples, horizon)
    last_close: float
    atr: float
    equity: float
    daily_pnl: float
    daily_loss_limit: float
    kill_switch: bool
    open_positions: int
    max_positions: int
    spread_points: float
    max_spread_points: float
    news_blackout: bool
    trend: str  # "up" / "down" / "choppy"
    calendar_high_impact: bool


@dataclass(frozen=True)
class ResearcherVerdict:
    """Researcher's analysis and bias."""

    bias: Literal["long", "short", "neutral"]
    conviction: float  # 0.0 to 1.0
    kronos_signal: KronosSignal
    reasons: tuple[str, ...]
    regime: str | None = None
    regime_confidence: float = 0.0


@dataclass(frozen=True)
class StrategistProposal:
    """Strategist's proposed trade."""

    side: Literal["long", "short", "none"]
    lots: float
    entry: float
    sl: float
    tp: float
    risk_usd: float
    risk_pct: float
    expected_rr: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RiskManagerVerdict:
    """Risk manager's go/no-go."""

    approved: bool
    blocked_reason: str | None
    adjusted_lots: float | None
    checks: tuple[str, ...]


@dataclass(frozen=True)
class ExecutorDecision:
    """Executor's final decision."""

    action: Literal["enter", "skip", "wait", "blocked"]
    symbol: str
    side: Literal["long", "short", "none"] | None
    lots: float | None
    entry: float | None
    sl: float | None
    tp: float | None
    narrative: str
    debate_trace: tuple[str, ...]


class DebateEngine:
    """Runs the multi-agent debate for one symbol/timeframe."""

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt
        self.analyst = Analyst(rt)
        self.execution_desk = ExecutionDesk(rt)
        self.session_guard = SessionGuard(rt)
        self.risk_intel = RiskIntel(rt)
        self.regime_classifier = RegimeClassifier(rt)
        self.market_intel = MarketIntel(rt)
        self.planner = Planner(rt)
        self.reflector = Reflector(rt)

    def debate(
        self,
        symbol: str,
        timeframe: str,
        paths: np.ndarray,
        last_close: float,
        atr: float,
        context: DebateContext,
    ) -> ExecutorDecision:
        """Run the full debate pipeline and return an executor decision."""

        trace: list[str] = []
        trace.append(f"=== Debate: {symbol} {timeframe} ===")

        # ---- Planner: decompose the decision into steps ----
        try:
            plan = self.planner.create_plan(
                f"Analyse {symbol} {timeframe} and decide whether to enter a trade"
            )
            trace.append(f"[Planner] Plan {plan.plan_id[:8]}: {len(plan.steps)} steps")
            for i, step in enumerate(plan.steps):
                trace.append(f"  Step {i+1}: {step.tool} → {step.expected_outcome}")
        except Exception:  # noqa: BLE001
            plan = None
            trace.append("[Planner] Planning unavailable — proceeding directly")

        # ---- Researcher: Kronos + market structure + news ----
        kronos_signal = analyse_paths(paths, last_close, atr)
        researcher = self._researcher(kronos_signal, context)
        trace.append(f"[Researcher] {researcher.bias.upper()} — conviction {researcher.conviction:.0%}")
        for r in researcher.reasons:
            trace.append(f"  • {r}")

        if researcher.bias == "neutral":
            trace.append("[Strategist] No directional bias — skipping.")
            trace.append("[Executor] SKIP — no tradeable bias from researcher.")
            return ExecutorDecision(
                action="skip",
                symbol=symbol,
                side="none",
                lots=None,
                entry=None,
                sl=None,
                tp=None,
                narrative="\n".join(trace),
                debate_trace=tuple(trace),
            )

        # ---- Strategist: propose entry/SL/TP ----
        strategist = self._strategist(researcher, context)
        trace.append(
            f"[Strategist] {strategist.side.upper()} {strategist.lots:.2f} lots "
            f"entry {strategist.entry:.2f} SL {strategist.sl:.2f} TP {strategist.tp:.2f} "
            f"(risk {strategist.risk_pct:.2%}, RR {strategist.expected_rr:.2f})"
        )
        for r in strategist.reasons:
            trace.append(f"  • {r}")

        if strategist.side == "none":
            trace.append("[Executor] SKIP — strategist found no executable setup.")
            return ExecutorDecision(
                action="skip",
                symbol=symbol,
                side="none",
                lots=None,
                entry=None,
                sl=None,
                tp=None,
                narrative="\n".join(trace),
                debate_trace=tuple(trace),
            )

        # ---- Risk Manager: validate against guards ----
        risk = self._risk_manager(strategist, context)
        trace.append(
            f"[Risk Manager] {'APPROVED' if risk.approved else 'BLOCKED'}: "
            f"{risk.blocked_reason or 'all guards passed'}"
        )
        for c in risk.checks:
            trace.append(f"  ✓ {c}")

        if not risk.approved:
            trace.append(
                f"[Executor] BLOCKED — {risk.blocked_reason}. No order sent."
            )
            return ExecutorDecision(
                action="blocked",
                symbol=symbol,
                side=strategist.side,
                lots=None,
                entry=None,
                sl=None,
                tp=None,
                narrative="\n".join(trace),
                debate_trace=tuple(trace),
            )

        # ---- Executor: final go/no-go ----
        final_lots = risk.adjusted_lots or strategist.lots
        trace.append(
            f"[Executor] EXECUTE — {strategist.side.upper()} {final_lots:.2f} lots "
            f"entry {strategist.entry:.2f} SL {strategist.sl:.2f} TP {strategist.tp:.2f}"
        )

        narrative = self._build_narrative(
            symbol, timeframe, researcher, strategist, risk, final_lots
        )

        # ---- Reflector: record decision for post-trade learning ----
        try:
            decision_id = uuid.uuid4().hex
            self.reflector.reflect(
                decision_id=decision_id,
                outcome="proposed",
                context={
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "side": strategist.side,
                    "lots": final_lots,
                    "entry": strategist.entry,
                    "sl": strategist.sl,
                    "tp": strategist.tp,
                    "signal_side": researcher.kronos_signal.side,
                    "p_up": researcher.kronos_signal.p_up,
                    "edge_atr": researcher.kronos_signal.edge_atr,
                    "regime": researcher.regime or "unknown",
                    "regime_confidence": researcher.regime_confidence,
                    "risk_pct": strategist.risk_pct,
                    "expected_rr": strategist.expected_rr,
                },
            )
        except Exception:  # noqa: BLE001
            pass

        return ExecutorDecision(
            action="enter",
            symbol=symbol,
            side=strategist.side,
            lots=final_lots,
            entry=strategist.entry,
            sl=strategist.sl,
            tp=strategist.tp,
            narrative="\n".join(trace) + "\n\n" + narrative,
            debate_trace=tuple(trace),
        )

    # ---- Individual agents ----

    def _researcher(
        self, kronos_signal: KronosSignal, context: DebateContext
    ) -> ResearcherVerdict:
        """Researcher analyses Kronos + structure + news and forms a bias."""
        reasons: list[str] = []

        # Kronos signal drives the primary bias
        bias: Literal["long", "short", "neutral"] = kronos_signal.side
        conviction = kronos_signal.confidence

        reasons.append(f"Kronos p_up {kronos_signal.p_up:.0%}")
        reasons.append(f"Kronos edge {kronos_signal.edge_atr:+.2f} ATR")
        reasons.append(f"Kronos regime {kronos_signal.regime}")
        reasons.append(f"Kronos confidence {kronos_signal.confidence:.0%}")

        # Multi-timeframe structure confirmation via MarketIntel
        try:
            mtf = self.market_intel.synthesize(context.symbol, context.timeframe)
            mtf_trend = mtf.get("trend_consensus", "neutral")
            if mtf_trend == "bullish" and kronos_signal.side == "long":
                conviction = min(1.0, conviction + 0.10)
                reasons.append("multi-TF trend aligns with Kronos long bias")
            elif mtf_trend == "bearish" and kronos_signal.side == "short":
                conviction = min(1.0, conviction + 0.10)
                reasons.append("multi-TF trend aligns with Kronos short bias")
            elif mtf_trend == "bullish" and kronos_signal.side == "short":
                conviction = max(0.0, conviction - 0.20)
                reasons.append("multi-TF trend opposes Kronos short bias")
            elif mtf_trend == "bearish" and kronos_signal.side == "long":
                conviction = max(0.0, conviction - 0.20)
                reasons.append("multi-TF trend opposes Kronos long bias")
        except Exception:  # noqa: BLE001
            pass  # Multi-timeframe data unavailable; proceed with Kronos only

        # Regime classification via RegimeClassifier
        try:
            regime = self.regime_classifier.classify(context.symbol, context.timeframe)
            reasons.append(f"regime={regime.regime} (conf {regime.confidence:.0%})")
            if regime.regime == "volatile":
                conviction = max(0.0, conviction - 0.15)
                reasons.append("volatile regime — reducing conviction")
            elif regime.regime in ("trend_up", "trend_down"):
                conviction = min(1.0, conviction + 0.05)
                reasons.append("trending regime — slight conviction boost")
        except Exception:  # noqa: BLE001
            regime = None

        # Trend cross-check (legacy context.trend as fallback)
        if context.trend == "up" and kronos_signal.side == "long":
            conviction = min(1.0, conviction + 0.05)
            reasons.append("context trend aligns with Kronos long bias")
        elif context.trend == "down" and kronos_signal.side == "short":
            conviction = min(1.0, conviction + 0.05)
            reasons.append("context trend aligns with Kronos short bias")

        # News blackout check
        if context.news_blackout:
            conviction = max(0.0, conviction - 0.30)
            reasons.append("high-impact news blackout active — reducing conviction")

        # News calendar surprises
        if context.calendar_high_impact:
            conviction = max(0.0, conviction - 0.15)
            reasons.append("high-impact calendar event nearby — caution")

        # Clamp conviction
        conviction = max(0.0, min(1.0, conviction))

        # Neutral if conviction too low
        if conviction < 0.40:
            bias = "neutral"

        return ResearcherVerdict(
            bias=bias,
            conviction=conviction,
            kronos_signal=kronos_signal,
            regime=regime.regime if regime else None,
            regime_confidence=regime.confidence if regime else 0.0,
            reasons=tuple(dict.fromkeys(reasons)),
        )

    def _strategist(
        self, researcher: ResearcherVerdict, context: DebateContext
    ) -> StrategistProposal:
        """Strategist proposes entry/SL/TP and position size."""
        side = researcher.bias
        k = researcher.kronos_signal

        if side == "long":
            entry = context.last_close
            sl = context.last_close - context.atr * 1.5
            tp = context.last_close + context.atr * 2.5
        elif side == "short":
            entry = context.last_close
            sl = context.last_close + context.atr * 1.5
            tp = context.last_close - context.atr * 2.5
        else:
            return StrategistProposal(
                side="none",
                lots=0.0,
                entry=0.0,
                sl=0.0,
                tp=0.0,
                risk_usd=0.0,
                risk_pct=0.0,
                expected_rr=0.0,
                reasons=("no directional bias",),
            )

        # Risk-based position sizing: risk_pct of equity at stop
        risk_pct = 0.02  # 2% of equity per trade (configurable)
        stop_distance = abs(entry - sl)
        contract_size = 100.0  # XAUUSD contract size
        lots = min(
            (context.equity * risk_pct) / (stop_distance * contract_size),
            10.0,  # cap lots
        )
        lots = round(lots, 2)

        risk_usd = stop_distance * lots * contract_size
        risk_pct_actual = risk_usd / context.equity if context.equity > 0 else 0.0

        rr = abs(tp - entry) / stop_distance if stop_distance > 0 else 0.0

        reasons: list[str] = []
        reasons.append(f"entry at {entry:.2f} (last close)")
        reasons.append(f"SL at {sl:.2f} ({abs(entry-sl)/context.atr:.1f} ATR)")
        reasons.append(f"TP at {tp:.2f} ({abs(tp-entry)/context.atr:.1f} ATR)")
        reasons.append(f"lots {lots:.2f} (risk {risk_pct_actual:.2%} of equity)")
        reasons.append(f"expected R:R {rr:.2f}")

        return StrategistProposal(
            side=side,
            lots=lots,
            entry=entry,
            sl=sl,
            tp=tp,
            risk_usd=risk_usd,
            risk_pct=risk_pct_actual,
            expected_rr=rr,
            reasons=tuple(dict.fromkeys(reasons)),
        )

    def _risk_manager(
        self, strategist: StrategistProposal, context: DebateContext
    ) -> RiskManagerVerdict:
        """Risk manager validates against all guards using RiskIntel."""

        # ---- Kill switch ----
        if context.kill_switch:
            return RiskManagerVerdict(
                approved=False,
                blocked_reason="kill switch is engaged",
                adjusted_lots=None,
                checks=("kill switch engaged",),
            )

        # ---- Daily loss limit ----
        if context.daily_pnl <= -context.daily_loss_limit:
            return RiskManagerVerdict(
                approved=False,
                blocked_reason="daily loss limit reached",
                adjusted_lots=None,
                checks=(
                    f"daily PnL {context.daily_pnl:.2f} <= limit "
                    f"{-context.daily_loss_limit:.2f}",
                ),
            )

        # ---- Regime classification ----
        try:
            regime = self.regime_classifier.classify(context.symbol, context.timeframe)
        except Exception:  # noqa: BLE001
            regime = None

        # ---- Risk decomposition for open positions ----
        try:
            positions = self.rt.positions(context.symbol)
            risk_decomp = self.risk_intel.decompose(positions)
        except Exception:  # noqa: BLE001
            positions = []
            risk_decomp = None

        checks: list[str] = []
        if regime:
            checks.append(f"regime={regime.regime} (confidence {regime.confidence:.0%})")
        if risk_decomp:
            checks.append(
                f"portfolio risk {risk_decomp.risk_pct:.2%} "
                f"(correlation {risk_decomp.correlation_risk:.2f}, "
                f"concentration {risk_decomp.concentration_risk:.2f})"
            )

        # ---- Max concurrent positions ----
        if context.open_positions >= context.max_positions:
            return RiskManagerVerdict(
                approved=False,
                blocked_reason="max concurrent positions reached",
                adjusted_lots=None,
                checks=(
                    f"open positions {context.open_positions} >= max "
                    f"{context.max_positions}",
                ),
            )

        # ---- Spread guard ----
        if context.spread_points > context.max_spread_points:
            return RiskManagerVerdict(
                approved=False,
                blocked_reason="spread too wide",
                adjusted_lots=None,
                checks=(
                    f"spread {context.spread_points:.0f} pts > max "
                    f"{context.max_spread_points:.0f}",
                ),
            )

        # ---- News blackout — block entries entirely ----
        if context.news_blackout:
            return RiskManagerVerdict(
                approved=False,
                blocked_reason="news blackout active",
                adjusted_lots=None,
                checks=("high-impact news blackout",),
            )

        # ---- Dynamic position sizing via RiskIntel ----
        try:
            sizing = self.risk_intel.size(
                context.symbol, strategist.side, signal_strength=researcher.conviction
            )
        except Exception:  # noqa: BLE001
            sizing = None

        # Check if sized lots exceed strategist's proposed lots
        lots = min(strategist.lots, sizing.size) if sizing else strategist.lots

        if lots <= 0:
            return RiskManagerVerdict(
                approved=False,
                blocked_reason="dynamic sizing resulted in zero lots",
                adjusted_lots=None,
                checks=(
                    f"regime={regime.regime if regime else 'unknown'}, "
                    f"corr_pen={sizing.correlation_penalty:.2f if sizing else 0.0}, "
                    f"vol_scale={sizing.volatility_scaling:.2f if sizing else 0.0}",
                ),
            )

        risk_usd = abs(strategist.entry - strategist.sl) * lots * 100.0
        risk_pct_actual = risk_usd / context.equity if context.equity > 0 else 0.0

        rr = (
            abs(strategist.tp - strategist.entry) / abs(strategist.entry - strategist.sl)
            if abs(strategist.entry - strategist.sl) > 0
            else 0.0
        )

        checks.append(
            f"dynamic size {lots:.2f} lots (risk {risk_pct_actual:.2%}, "
            f"regime mult {sizing.regime_multiplier:.2f})"
            if sizing
            else f"risk {risk_pct_actual:.2%}"
        )

        return RiskManagerVerdict(
            approved=True,
            blocked_reason=None,
            adjusted_lots=lots,
            checks=tuple(checks),
        )

    def _build_narrative(
        self,
        symbol: str,
        timeframe: str,
        researcher: ResearcherVerdict,
        strategist: StrategistProposal,
        risk: RiskManagerVerdict,
        final_lots: float,
    ) -> str:
        """Build the final narrative for the user."""
        k = researcher.kronos_signal
        lines: list[str] = []
        lines.append(f"=== Trading Decision: {symbol} {timeframe} ===")
        lines.append("")
        lines.append("[Researcher]")
        lines.append(f"  Bias: {researcher.bias.upper()} (conviction {researcher.conviction:.0%})")
        lines.append(f"  Kronos: p_up {k.p_up:.0%}, edge {k.edge_atr:+.2f} ATR")
        lines.append(f"  Regime: {k.regime}")
        lines.append("")
        lines.append("[Strategist]")
        lines.append(f"  Side: {strategist.side.upper()}")
        lines.append(f"  Lots: {strategist.lots:.2f}")
        lines.append(f"  Entry: {strategist.entry:.2f}")
        lines.append(f"  SL: {strategist.sl:.2f}")
        lines.append(f"  TP: {strategist.tp:.2f}")
        lines.append(f"  Risk: {strategist.risk_pct:.2%} of equity")
        lines.append(f"  Expected R:R: {strategist.expected_rr:.2f}")
        lines.append("")
        lines.append("[Risk Manager]")
        lines.append(f"  Decision: {'APPROVED' if risk.approved else 'BLOCKED'}")
        if risk.adjusted_lots is not None and risk.adjusted_lots != strategist.lots:
            lines.append(f"  Adjusted lots: {strategist.lots:.2f} → {risk.adjusted_lots:.2f}")
        lines.append("")
        lines.append("Decision: EXECUTE")
        lines.append(
            f"Send {strategist.side.upper()} {final_lots:.2f} lots on {symbol} "
            f"at {strategist.entry:.2f}, SL {strategist.sl:.2f}, TP {strategist.tp:.2f}."
        )
        return "\n".join(lines)
