"""Policy engine: JSON schema validation and constraint enforcement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import json
import jsonschema

from backend.ignite.services.runtime import Runtime
from backend.ignite.services.ledger import DailyPnl


@dataclass(frozen=True)
class PolicyValidationResult:
    """Result of policy validation."""
    ok: bool
    error: str | None = None
    violations: list[str] = None


class PolicyEngine:
    """Validates actions against policy constraints."""

    # JSON schema for policy configuration
    POLICY_SCHEMA = {
        "type": "object",
        "properties": {
            "max_drawdown_pct": {"type": "number", "minimum": 0, "maximum": 1},
            "max_leverage": {"type": "number", "minimum": 1},
            "forbidden_symbols": {"type": "array", "items": {"type": "string"}},
            "allowed_symbols": {"type": "array", "items": {"type": "string"}},
            "max_position_size_pct": {"type": "number", "minimum": 0, "maximum": 1},
            "max_concurrent_positions": {"type": "integer", "minimum": 1},
            "max_positions_per_symbol": {"type": "integer", "minimum": 1},
            "max_portfolio_risk_pct": {"type": "number", "minimum": 0, "maximum": 1},
            "daily_loss_limit_pct": {"type": "number", "minimum": 0, "maximum": 1},
            "max_holding_hours": {"type": "integer", "minimum": 1},
            "trading_hours": {
                "type": "object",
                "properties": {
                    "start": {"type": "string", "pattern": "^([01]?[0-9]|2[0-3]):[0-5][0-9]$"},
                    "end": {"type": "string", "pattern": "^([01]?[0-9]|2[0-3]):[0-5][0-9]$"},
                    "timezone": {"type": "string"},
                },
                "required": ["start", "end"],
            },
            "session_times": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "start": {"type": "string"},
                        "end": {"type": "string"},
                    },
                },
            },
        },
        "additionalProperties": False,
    }

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt
        self._policy: dict[str, Any] = {}
        self._schema_validator = jsonschema.Draft202012Validator(self.POLICY_SCHEMA)

    def load_policy(self, policy_path: str) -> bool:
        """Load policy from JSON file."""
        try:
            with open(policy_path, "r") as f:
                policy = json.load(f)
            self._schema_validator.validate(policy)
            self._policy = policy
            return True
        except (json.JSONDecodeError, jsonschema.ValidationError, FileNotFoundError) as e:
            self._policy = {}
            return False

    def get_policy(self) -> dict[str, Any]:
        return dict(self._policy)

    def validate(self, action: dict[str, Any]) -> PolicyValidationResult:
        """Validate an action against policy constraints."""
        violations = []

        # Check forbidden symbols
        forbidden = self._policy.get("forbidden_symbols", [])
        if action.get("symbol") in forbidden:
            violations.append(f"Symbol {action['symbol']} is forbidden")

        # Check allowed symbols
        allowed = self._policy.get("allowed_symbols")
        if allowed and action.get("symbol") not in allowed:
            violations.append(f"Symbol {action.get('symbol')} not in allowed list")

        # Check leverage
        max_leverage = self._policy.get("max_leverage")
        leverage = action.get("leverage")
        if max_leverage and leverage and leverage > max_leverage:
            violations.append(f"Leverage {leverage} exceeds max {max_leverage}")

        # Check position size
        max_pos_pct = self._policy.get("max_position_size_pct")
        size = action.get("size")
        equity = self._get_equity()
        if max_pos_pct and size and equity > 0:
            position_pct = (size * self._get_contract_value(action.get("symbol", ""))) / equity
            if position_pct > max_pos_pct:
                violations.append(f"Position size {position_pct:.2%} exceeds max {max_pos_pct:.2%}")

        # Check leverage
        max_lev = self._policy.get("max_leverage")
        if max_lev and leverage and leverage > max_lev:
            violations.append(f"Leverage {leverage} exceeds max {max_lev}")

        # Check daily loss limit
        daily_loss = self._policy.get("daily_loss_limit_pct")
        if daily_loss:
            pnl = self.rt.ledger.daily()
            if pnl.available and pnl.blocked:
                violations.append(f"Daily loss limit breached: {pnl.total_usd:.2f}")

        # Check max concurrent positions
        max_pos = self._policy.get("max_concurrent_positions")
        if max_pos:
            positions = self.rt.positions()
            if len(positions) >= max_pos:
                violations.append(f"Max concurrent positions ({max_pos}) reached")

        # Check max positions per symbol
        max_per_symbol = self._policy.get("max_positions_per_symbol")
        if max_per_symbol:
            symbol = action.get("symbol")
            if symbol:
                same_symbol = sum(1 for p in self.rt.positions() if p.get("symbol") == symbol)
                if same_symbol >= max_per_symbol:
                    violations.append(f"Max positions for {symbol} ({max_per_symbol}) reached")

        # Check portfolio risk cap
        max_portfolio_risk = self._policy.get("max_portfolio_risk_pct")
        if max_portfolio_risk:
            risk = self.rt.risk_intel.decompose(self.rt.positions())
            if risk.risk_pct > max_portfolio_risk:
                violations.append(f"Portfolio risk {risk.risk_pct:.2%} exceeds max {max_portfolio_risk:.2%}")

        return PolicyValidationResult(
            ok=len(violations) == 0,
            error="; ".join(violations) if violations else None,
            violations=violations if violations else [],
        )

    def _get_equity(self) -> float:
        return float(self.rt.account_payload().get("equity") or 0.0)

    def _get_contract_value(self, symbol: str) -> float:
        spec = self.rt.spec(symbol)
        return spec.contract_size if spec else 1.0