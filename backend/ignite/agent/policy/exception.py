"""Exception handler: human-in-the-loop escalation for policy violations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any
import uuid

from backend.ignite.services.runtime import Runtime
from backend.ignite.services.events import EventBus
from backend.ignite.agent.policy.policy_engine import PolicyValidationResult


class ExceptionSeverity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class PolicyException:
    """A policy violation that requires human intervention."""
    exception_id: str
    severity: ExceptionSeverity
    violation: str
    context: dict[str, Any]
    created_at: str
    resolved_at: str | None = None
    resolution: str | None = None
    resolved_by: str | None = None


class ExceptionHandler:
    """Handles policy violations with human-in-the-loop escalation."""

    def __init__(self, rt: Runtime, events: EventBus | None = None) -> None:
        self.rt = rt
        self.events = events
        self._exceptions: dict[str, Any] = {}

    def handle_violation(
        self,
        validation_result: PolicyValidationResult,
        context: dict[str, Any] | None = None,
    ) -> ExceptionSeverity:
        """Handle a policy violation, escalate if needed."""
        if validation_result.ok:
            return ExceptionSeverity.LOW

        severity = self._assess_severity(validation_result)
        exception = self._create_exception(validation_result, severity, context)

        # Store exception
        self._exceptions[exception.exception_id] = exception

        # Publish event
        if self.events:
            self.events.publish("policy.violation", {
                "exception_id": exception.exception_id,
                "severity": severity.value,
                "violation": validation_result.violations,
                "context": context,
            })

        # For critical violations, we could trigger immediate demotion
        if severity == ExceptionSeverity.CRITICAL:
            self._trigger_emergency_demotion()

        return severity

    def _assess_severity(self, result: PolicyValidationResult) -> ExceptionSeverity:
        """Determine severity based on violation types."""
        if not result.violations:
            return ExceptionSeverity.LOW

        violations = result.violations or []
        
        # Critical: forbidden symbols, kill switch, daily loss breach
        critical_keywords = ["forbidden", "kill switch", "daily loss", "drawdown", "margin"]
        for v in violations:
            if any(kw in v.lower() for kw in critical_keywords):
                return ExceptionSeverity.CRITICAL

        # High: leverage, position size, concentration
        high_keywords = ["leverage", "position size", "concentration", "max_positions"]
        for v in violations:
            if any(kw in v.lower() for kw in high_keywords):
                return ExceptionSeverity.HIGH

        # Medium: correlation, drawdown
        medium_keywords = ["correlation", "drawdown", "max_positions"]
        for v in violations:
            if any(kw in v.lower() for kw in medium_keywords):
                return ExceptionSeverity.MEDIUM

        return ExceptionSeverity.LOW

    def _create_exception(
        self,
        validation_result: PolicyValidationResult,
        severity: ExceptionSeverity,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        exception_id = uuid.uuid4().hex
        return {
            "exception_id": exception_id,
            "severity": severity.value,
            "violation": validation_result.violations,
            "context": context or {},
            "created_at": datetime.now(timezone.utc).isoformat(),
            "resolved_at": None,
            "resolution": None,
            "resolved_by": None,
        }

    def _trigger_emergency_demotion(self) -> None:
        """Emergency demotion to shadow mode on critical violation."""
        self.rt.config_service.update({
            "execution_mode": "shadow",
            "autonomy_level": 0,
        })
        if self.events:
            self.events.publish("agent.emergency_demotion", {
                "reason": "Critical policy violation",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    def resolve_exception(self, exception_id: str, resolution: str, resolved_by: str) -> bool:
        """Mark an exception as resolved."""
        if exception_id not in self._exceptions:
            return False
        
        self._exceptions[exception_id].update({
            "resolved_at": datetime.now(timezone.utc).isoformat(),
            "resolution": resolution,
            "resolved_by": resolved_by,
        })
        
        if self.events:
            self.events.publish("policy.exception_resolved", {
                "exception_id": exception_id,
                "resolution": resolution,
                "resolved_by": resolved_by,
            })
        return True

    def get_exception(self, exception_id: str) -> dict[str, Any] | None:
        return self._exceptions.get(exception_id)

    def get_active_exceptions(self, severity: ExceptionSeverity | None = None) -> list[dict[str, Any]]:
        exceptions = list(self._exceptions.values())
        if severity:
            exceptions = [e for e in exceptions if e["severity"] == severity.value]
        return exceptions

    def get_exception_stats(self) -> dict[str, int]:
        total = len(self._exceptions)
        by_severity = {}
        for e in self._exceptions.values():
            sev = e["severity"]
            by_severity[sev] = by_severity.get(sev, 0) + 1
        return {"total": total, "by_severity": by_severity}