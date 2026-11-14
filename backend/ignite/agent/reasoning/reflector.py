"""Agent reflector: post-decision reflection and insight extraction."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from backend.ignite.services.runtime import Runtime
from backend.ignite.store.db import utc_now


@dataclass(frozen=True)
class Reflection:
    """A post-decision reflection with extracted insights."""
    reflection_id: str
    decision_id: str
    outcome: str
    insights: dict[str, Any]
    created_at: str = field(default_factory=utc_now)


class Reflector:
    """Records post-decision reflections and extracts learning insights."""

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt

    def reflect(
        self,
        decision_id: str,
        outcome: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Record a reflection on a decision outcome."""
        reflection_id = uuid.uuid4().hex
        created = utc_now()

        # Extract structured insights from context
        insights = self._extract_insights(context)

        reflection = {
            "reflection_id": reflection_id,
            "decision_id": decision_id,
            "outcome": outcome,
            "insights": insights,
            "created_at": created,
        }

        # Persist to agent_events
        self.rt.store.append_agent_event(
            "reflection.recorded",
            severity="info",
            decision_id=decision_id,
            payload=reflection,
        )

        return reflection

    def _extract_insights(self, context: dict[str, Any]) -> dict[str, Any]:
        """Extract structured insights from reflection context."""
        insights = {}

        # Extract PnL lesson
        if "pnl" in context:
            pnl = float(context["pnl"])
            if pnl > 0:
                insights["pnl_lesson"] = f"Profitable trade (+{pnl:.2f}). Pattern worked."
            elif pnl < 0:
                insights["pnl_lesson"] = f"Loss ({pnl:.2f}). Review entry/exit logic."
            else:
                insights["pnl_lesson"] = "Break-even. No clear signal."

        # Extract sizing lesson
        if "size" in context and "optimal_size" in context:
            actual = float(context["size"])
            optimal = float(context["optimal_size"])
            if actual > optimal * 1.2:
                insights["sizing_lesson"] = f"Over-sized ({actual:.4f} vs optimal {optimal:.4f}). Reduce position."
            elif actual < optimal * 0.8:
                insights["sizing_lesson"] = f"Under-sized ({actual:.4f} vs optimal {optimal:.4f}). Could have been larger."

        # Extract timing lesson
        if "timing" in context:
            insights["timing_lesson"] = context["timing"]

        # Extract regime lesson
        if "regime" in context:
            insights["regime_lesson"] = f"Regime was {context['regime']}. Adjust strategy accordingly."

        # Extract general lesson
        if "lesson" in context:
            insights["general_lesson"] = context["lesson"]

        return insights