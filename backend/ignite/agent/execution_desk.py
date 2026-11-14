"""ExecutionDesk: guarded execution of drafts via MT5 MCP.

Validates a draft against live risk guards, then sends it through the broker
gateway. Never sends an order that fails a guard.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.ignite.services.execution import evaluate_draft, execute_draft_autonomous
from backend.ignite.services.runtime import Runtime


@dataclass(frozen=True)
class ExecutionResult:
    """Outcome of executing a draft."""

    ok: bool
    ticket: str | None
    fill_price: float | None
    detail: str
    blocked: bool | None
    block_reason: str | None


class ExecutionDesk:
    """Validates and executes draft orders through the broker gateway."""

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt

    def execute(self, draft_id: str) -> ExecutionResult:
        """Evaluate guards and execute a draft if all checks pass."""
        draft = self.rt.store.get_draft(draft_id)
        if draft is None:
            return ExecutionResult(
                ok=False,
                ticket=None,
                fill_price=None,
                detail="draft not found",
                blocked=True,
                block_reason="draft not found",
            )

        # Pre-check: evaluate draft against live guards
        try:
            state = evaluate_draft(self.rt, draft)
        except Exception as exc:  # noqa: BLE001 - surface evaluation errors
            return ExecutionResult(
                ok=False,
                ticket=None,
                fill_price=None,
                detail=f"evaluation failed: {exc}",
                blocked=True,
                block_reason="evaluation_error",
            )

        if not state.get("executable"):
            failing = next(
                (c for c in state.get("checks", []) if not c.get("ok")), None
            )
            reason = failing["message"] if failing else "draft not executable"
            return ExecutionResult(
                ok=False,
                ticket=None,
                fill_price=None,
                detail=reason,
                blocked=True,
                block_reason=reason,
            )

        # Execute through the guarded autonomous path
        try:
            result = execute_draft_autonomous(self.rt, draft_id)
        except Exception as exc:  # noqa: BLE001 - surface execution errors
            return ExecutionResult(
                ok=False,
                ticket=None,
                fill_price=None,
                detail=str(exc),
                blocked=False,
                block_reason=None,
            )

        position = result.get("position") or {}
        order = result.get("order") or {}
        ticket = (
            position.get("ticket")
            or position.get("position_id")
            or order.get("position_id")
            or order.get("ticket")
        )

        return ExecutionResult(
            ok=bool(result.get("ok", False)),
            ticket=ticket,
            fill_price=result.get("filled_price"),
            detail=str(result.get("state", "unknown")),
            blocked=False,
            block_reason=None,
        )
