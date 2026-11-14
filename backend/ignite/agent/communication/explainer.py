"""Explainer: decision tree with evidence, counterfactuals, links to evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.ignite.agent.decision import Decision, Entry, Risk, Links
from backend.ignite.services.runtime import Runtime


@dataclass(frozen=True)
class DecisionExplanation:
    """Structured explanation of a trading decision."""
    action: str
    conviction: float
    thesis: str
    evidence: list[str]
    counterfactuals: list[str]
    entry: dict[str, Any]
    risk: dict[str, Any]
    expected_rr: float
    invalidate_if: list[str]
    links: dict[str, Any]
    confidence_score: float


class Explainer:
    """Generates structured explanations for trading decisions."""

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt

    def explain(self, decision: Decision) -> dict[str, Any]:
        """Generate a structured explanation for a decision."""
        # Build evidence from decision
        evidence = list(decision.evidence)
        if decision.failed_conditions:
            evidence.append(f"Failed conditions: {', '.join(decision.failed_conditions)}")

        # Generate counterfactuals
        counterfactuals = self._generate_counterfactuals(decision)

        # Build explanation
        explanation = {
            "action": decision.action,
            "conviction": decision.conviction,
            "thesis": decision.thesis,
            "evidence": evidence,
            "counterfactuals": counterfactuals,
            "entry": {
                "type": decision.entry.type,
                "price": decision.entry.price,
            },
            "risk": {
                "lots": decision.risk.lots,
                "sl": decision.risk.sl,
                "tp": decision.risk.tp,
            },
            "expected_rr": decision.expected_rr,
            "invalidate_if": decision.invalidate_if,
            "links": {
                "analysis_id": decision.links.analysis_id,
                "draft_id": decision.links.draft_id,
                "decision_id": decision.links.decision_id,
            },
            "confidence_score": decision.conviction,
        }

        return explanation

    def _generate_counterfactuals(self, decision: Decision) -> list[str]:
        """Generate counterfactual scenarios for the decision."""
        counterfactuals = []

        # Counterfactual: what if price moves against us?
        if decision.action == "LONG":
            counterfactuals.append(
                f"If price drops below {decision.risk.sl:.2f} (stop loss), "
                f"loss would be {abs(decision.risk.lots * (decision.risk.sl - (decision.entry.price if decision.entry.type == 'market' else decision.entry.price))):.2f}"
            )
        elif decision.action == "SHORT":
            counterfactuals.append(
                f"If price rises above {decision.risk.sl:.2f} (stop loss), "
                f"loss would be {abs(decision.risk.lots * ((decision.entry.price if decision.entry.type == 'market' else decision.entry.price) - decision.risk.sl)):.2f}"
            )

        # Counterfactual: what if volatility spikes?
        counterfactuals.append(
            "If volatility doubles, position risk doubles. Consider reducing size."
        )

        # Counterfactual: what if correlation breaks down?
        counterfactuals.append(
            "If correlation with DXY breaks down, intermarket hedge may fail."
        )

        # Counterfactual: regime change
        counterfactuals.append(
            f"If regime shifts from {decision.action} to opposite, "
            f"stop loss will trigger at {decision.risk.sl}."
        )

        return counterfactuals