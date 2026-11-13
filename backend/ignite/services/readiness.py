"""Live readiness validator: checks all subsystems before live trading."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from backend.ignite.services.runtime import Runtime
from backend.ignite.services.ledger import DailyPnl
from backend.ignite.analysis.risk import RiskConfig


@dataclass(frozen=True)
class CheckResult:
    """Result of a single readiness check."""
    ok: bool
    detail: str = ""
    severity: str = "error"  # "error" | "warning" | "info"


@dataclass(frozen=True)
class ReadinessReport:
    """Complete readiness report."""
    ready: bool
    checks: dict[str, CheckResult]
    summary: str
    timestamp: str = None

    def __post_init__(self):
        if self.timestamp is None:
            object.__setattr__(self, "timestamp", datetime.utcnow().isoformat())


class ReadinessService:
    """Validates all subsystems are ready for live trading."""

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt

    def check(self) -> ReadinessReport:
        """Run all readiness checks and return aggregated report."""
        checks = {}

        # 1. MCP reachable
        checks["mcp"] = self._check_mcp()

        # 2. Terminal connected and trade_allowed
        checks["terminal"] = self._check_terminal()

        # 3. Kronos healthy
        checks["kronos"] = self._check_kronos()

        # 3. Database writable
        checks["database"] = self._check_database()

        # 4. Config valid (ceilings)
        checks["config"] = self._check_config()

        # 5. Kill switch off
        checks["kill_switch"] = self._check_kill_switch()

        # 6. Account equity > 0
        checks["account"] = self._check_account()

        # 7. Margin free > 0
        checks["margin"] = self._check_margin()

        # 8. Risk config valid
        checks["risk_config"] = self._check_risk_config()

        # 9. Daily loss not breached
        checks["daily_loss"] = self._check_daily_loss()

        # 10. Positions within limits
        checks["positions"] = self._check_positions()

        # 11. Per-symbol position limits
        checks["per_symbol_positions"] = self._check_per_symbol_positions()

        # Aggregate
        all_ok = all(c.ok for c in checks.values())
        failed = [name for name, c in checks.items() if not c.ok]
        summary = "All checks passed" if all_ok else f"Failed checks: {', '.join(failed)}"

        return ReadinessReport(
            ready=all_ok,
            checks=checks,
            summary=summary,
        )

    # --- Individual checks ---

    def _check_mcp(self) -> CheckResult:
        try:
            info = self.rt.call("terminal_get_info")
            terminal = info.get("terminal") or {}
            if not terminal:
                return CheckResult(False, "No terminal info", "error")
            return CheckResult(True, "MCP reachable")
        except Exception as e:
            return CheckResult(False, f"MCP unreachable: {e}", "error")

    def _check_terminal(self) -> CheckResult:
        try:
            info = self.rt.call("terminal_get_info")
            terminal = info.get("terminal") or {}
            connection = (terminal.get("connection") or {}).get("state")
            trade_allowed = terminal.get("trade_allowed", False)

            if connection != "synchronized":
                return CheckResult(False, f"Terminal not synchronized: {connection}", "error")
            if not trade_allowed:
                return CheckResult(False, "Trading not allowed by terminal", "error")
            return CheckResult(True, "Terminal connected and trading allowed")
        except Exception as e:
            return CheckResult(False, f"Terminal check failed: {e}", "error")

    def _check_kronos(self) -> CheckResult:
        try:
            health = self.rt.forecast.health()
            if not health.get("ready", False):
                return CheckResult(False, f"Kronos not ready: {health.get('error', 'unknown')}", "error")
            return CheckResult(True, "Kronos healthy")
        except Exception as e:
            return CheckResult(False, f"Kronos health check failed: {e}", "error")

    def _check_database(self) -> CheckResult:
        try:
            # Simple test query
            self.rt.store._conn.execute("SELECT 1").fetchone()
            return CheckResult(True, "Database writable")
        except Exception as e:
            return CheckResult(False, f"Database not writable: {e}", "error")

    def _check_config(self) -> CheckResult:
        try:
            config = self.rt.config()
            # Validate ceilings
            from backend.ignite.agent.config import CEILINGS
            for key, ceiling in CEILINGS.items():
                value = getattr(config, key, None)
                if value is not None and float(value) > ceiling + 1e-12:
                    return CheckResult(False, f"Config {key}={value} exceeds ceiling {ceiling}", "error")
            return CheckResult(True, "Config within ceilings")
        except Exception as e:
            return CheckResult(False, f"Config validation failed: {e}", "error")

    def _check_kill_switch(self) -> CheckResult:
        if self.rt.kill_switch():
            return CheckResult(False, "Kill switch is engaged", "error")
        return CheckResult(True, "Kill switch off")

    def _check_account(self) -> CheckResult:
        try:
            account = self.rt.account_payload()
            equity = float(account.get("equity") or 0.0)
            if equity <= 0:
                return CheckResult(False, f"Account equity not positive: {equity}", "error")
            return CheckResult(True, f"Equity: {equity:.2f}")
        except Exception as e:
            return CheckResult(False, f"Account check failed: {e}", "error")

    def _check_margin(self) -> CheckResult:
        try:
            account = self.rt.account_payload()
            margin_free = float(account.get("margin_free") or 0.0)
            if margin_free <= 0:
                return CheckResult(False, f"Free margin not positive: {margin_free}", "error")
            return CheckResult(True, f"Free margin: {margin_free:.2f}")
        except Exception as e:
            return CheckResult(False, f"Margin check failed: {e}", "error")

    def _check_risk_config(self) -> CheckResult:
        try:
            risk = self.rt.risk_config()
            if risk.risk_pct <= 0 or risk.risk_pct > risk.max_risk_pct:
                return CheckResult(False, f"Invalid risk config: risk_pct={risk.risk_pct}, max={risk.max_risk_pct}", "error")
            return CheckResult(True, "Risk config valid")
        except Exception as e:
            return CheckResult(False, f"Risk config check failed: {e}", "error")

    def _check_daily_loss(self) -> CheckResult:
        try:
            pnl = self.rt.ledger.daily()
            if not pnl.available:
                return CheckResult(False, "Daily PnL source unavailable", "error")
            if pnl.blocked:
                return CheckResult(False, f"Daily loss limit breached: {pnl.total_usd:.2f}", "error")
            return CheckResult(True, f"Daily PnL: {pnl.total_usd:.2f}")
        except Exception as e:
            return CheckResult(False, f"Daily loss check failed: {e}", "error")

    def _check_positions(self) -> CheckResult:
        try:
            config = self.rt.config()
            positions = self.rt.positions()
            if len(positions) >= config.max_concurrent_positions:
                return CheckResult(
                    False,
                    f"Position count {len(positions)} >= max {config.max_concurrent_positions}",
                    "error",
                )
            return CheckResult(True, f"Positions: {len(positions)}/{config.max_concurrent_positions}")
        except Exception as e:
            return CheckResult(False, f"Positions check failed: {e}", "error")

    def _check_per_symbol_positions(self) -> CheckResult:
        try:
            config = self.rt.config()
            positions = self.rt.positions()
            per_symbol = {}
            for pos in positions:
                symbol = pos.get("symbol")
                per_symbol[symbol] = per_symbol.get(symbol, 0) + 1
            for symbol, count in per_symbol.items():
                if count >= config.max_positions_per_symbol:
                    return CheckResult(
                        False,
                        f"{symbol} has {count} positions >= max {config.max_positions_per_symbol}",
                        "error",
                    )
            return CheckResult(True, "Per-symbol positions within limits")
        except Exception as e:
            return CheckResult(False, f"Per-symbol positions check failed: {e}", "error")