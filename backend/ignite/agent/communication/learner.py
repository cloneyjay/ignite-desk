"""Learner: extracts patterns, runs A/B tests, policy gradient, regime adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.ignite.services.runtime import Runtime
from backend.ignite.agent.memory import EpisodicMemory
from backend.ignite.agent.memory.semantic import SemanticMemory


@dataclass(frozen=True)
class Pattern:
    """Extracted trading pattern."""
    pattern_id: str
    name: str
    description: str
    win_rate: float
    avg_r: float
    sample_size: int
    conditions: dict[str, Any]
    regime: str | None = None


@dataclass(frozen=True)
class ABTestReport:
    """A/B test results."""
    variant_a: str
    variant_b: str
    metric: str
    winner: str
    p_value: float
    confidence: float
    sample_size_a: int
    sample_size_b: int


@dataclass(frozen=True)
class PolicyUpdate:
    """Proposed policy update."""
    parameter: str
    old_value: Any
    new_value: Any
    expected_improvement: float
    confidence: float


class Learner:
    """Learning dashboard: pattern extraction, A/B testing, policy gradient, regime adaptation."""

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt
        self.episodic = EpisodicMemory(rt)
        self.semantic = SemanticMemory(rt)

    def extract_patterns(self) -> list[dict[str, Any]]:
        """Extract trading patterns from episodic memory."""
        trades = self.episodic.get_trades()
        if not trades:
            return []

        # Group by regime and outcome
        patterns = []
        wins = [t for t in trades if t.get("outcome") == "profit"]
        losses = [t for t in trades if t.get("outcome") == "loss"]

        if wins:
            patterns.append({
                "name": "Winning Pattern",
                "description": f"{len(wins)} winning trades with avg R: {sum(t.get('r_multiple', 0) for t in wins)/len(wins):.2f}",
                "win_rate": len(wins) / len(trades),
                "avg_r": sum(t.get('r_multiple', 0) for t in wins) / len(wins),
                "sample_size": len(wins),
                "conditions": self._extract_conditions(wins),
            })

        if losses:
            patterns.append({
                "name": "Losing Pattern",
                "description": f"{len(losses)} losing trades with avg R: {sum(t.get('r_multiple', 0) for t in losses)/len(losses):.2f}",
                "win_rate": 0,
                "avg_r": sum(t.get('r_multiple', 0) for t in losses) / len(losses),
                "sample_size": len(losses),
                "conditions": self._extract_conditions(losses),
            })

        return patterns

    def _extract_conditions(self, trades: list[dict]) -> dict[str, Any]:
        """Extract common conditions from trades."""
        conditions = {}
        if not trades:
            return conditions
        
        # Extract common regime
        regimes = [t.get("regime") for t in trades if t.get("regime")]
        if regimes:
            from collections import Counter
            most_common = Counter(regimes).most_common(1)[0][0]
            conditions["regime"] = most_common

        return conditions

    def run_ab_test(self, variant_a: dict, variant_b: dict, metric: str, days: int = 30) -> dict:
        """Run A/B test between two variants."""
        # Placeholder for actual A/B test infrastructure
        return {
            "variant_a": variant_a,
            "variant_b": variant_b,
            "metric": metric,
            "duration_days": days,
            "status": "running",
        }

    def update_policy(self, updates: dict[str, Any]) -> dict[str, Any]:
        """Propose policy updates based on learning."""
        # Placeholder for policy gradient updates
        return {
            "status": "proposed",
            "updates": updates,
            "requires_approval": True,
        }

    def adapt_to_regime(self, regime: str) -> dict[str, Any]:
        """Adapt policy parameters to current regime."""
        adaptations = {
            "trend_up": {"risk_multiplier": 1.0, "trail_multiplier": 1.0},
            "trend_down": {"risk_multiplier": 1.0, "trail_multiplier": 1.0},
            "range": {"risk_multiplier": 0.5, "trail_multiplier": 0.5},
            "volatile": {"risk_multiplier": 0.3, "trail_multiplier": 0.5},
            "breakout": {"risk_multiplier": 0.8, "trail_multiplier": 0.8},
        }
        return adaptations.get(regime, {"risk_multiplier": 0.5, "trail_multiplier": 0.5})


from collections import Counter