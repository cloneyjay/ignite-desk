"""Strategy development and backtesting layer.

Enables the agent to:
- Write MQL5 Expert Advisor code from natural language
- Compile MQL5 via MetaEditor MCP tool
- Run MT5 Strategy Tester backtests
- Store, version, and compare strategies
- Retrieve backtest results (equity curve, drawdown, win rate, etc.)

All strategy code and results are stored locally in SQLite. MCP calls to MT5
are used for compilation and backtesting when the terminal is available.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.ignite.services.runtime import Runtime


STRATEGIES_DIR = Path(__file__).resolve().parents[2] / "data" / "strategies"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class StrategyResult:
    """Outcome of a strategy operation."""

    ok: bool
    strategy_id: str | None
    message: str
    data: dict[str, Any]


class StrategyManager:
    """Manages strategy lifecycle: create, compile, backtest, store."""

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt
        STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ create

    def create_strategy(
        self,
        name: str,
        symbol: str,
        timeframe: str,
        mql5_code: str,
        description: str | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> StrategyResult:
        """Create a new strategy definition and save MQL5 code to disk."""
        strategy_id = uuid.uuid4().hex
        now = utc_now()

        # Save MQL5 source to disk
        safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
        file_path = STRATEGIES_DIR / f"{safe_name}_{strategy_id[:8]}.mq5"
        file_path.write_text(mql5_code, encoding="utf-8")

        self.rt.store.insert_strategy(
            {
                "id": strategy_id,
                "name": name,
                "description": description,
                "symbol": symbol,
                "timeframe": timeframe,
                "mql5_code": mql5_code,
                "status": "draft",
                "version": 1,
                "parameters": parameters or {},
                "created_at": now,
                "updated_at": now,
            }
        )

        self.rt.store.insert_strategy_version(
            {
                "id": uuid.uuid4().hex,
                "strategy_id": strategy_id,
                "version": 1,
                "mql5_code": mql5_code,
                "change_note": "Initial version",
                "compiled": False,
                "created_at": now,
            }
        )

        self.rt.store.audit(
            "agent",
            "strategy_created",
            {"strategy_id": strategy_id, "name": name, "symbol": symbol},
            "ok",
        )

        return StrategyResult(
            ok=True,
            strategy_id=strategy_id,
            message=f"Strategy '{name}' created (v1). File: {file_path.name}",
            data={
                "strategy_id": strategy_id,
                "file_path": str(file_path),
                "mql5_code": mql5_code,
            },
        )

    # ------------------------------------------------------------------ compile

    def compile_strategy(self, strategy_id: str) -> StrategyResult:
        """Compile an MQL5 strategy via the MetaEditor MCP tool."""
        strategy = self.rt.store.get_strategy(strategy_id)
        if not strategy:
            return StrategyResult(
                ok=False,
                strategy_id=strategy_id,
                message=f"Strategy {strategy_id} not found",
                data={},
            )

        # Call MT5 MetaEditor MCP tool to compile
        try:
            result = self.rt.call(
                "metaeditor.compile",
                {
                    "file_path": strategy["mql5_code"],  # pass code or path
                    "symbol": strategy["symbol"],
                },
            )
        except Exception as exc:  # noqa: BLE001
            # MT5 not available — mark as uncompiled but keep the strategy
            self.rt.store.update_strategy(
                strategy_id,
                {"status": "draft", "status": "draft"},
            )
            return StrategyResult(
                ok=False,
                strategy_id=strategy_id,
                message=f"MT5 MetaEditor not available: {exc}. Strategy saved locally but not compiled.",
                data={"compiled": False},
            )

        compiled = bool(result.get("compiled", False))
        compile_errors = result.get("errors")
        compile_warnings = result.get("warnings")

        new_status = "compiled" if compiled else "draft"
        self.rt.store.update_strategy(strategy_id, {"status": new_status})
        self.rt.store.insert_strategy_version(
            {
                "id": uuid.uuid4().hex,
                "strategy_id": strategy_id,
                "version": strategy["version"] + 1,
                "mql5_code": strategy["mql5_code"],
                "change_note": "Recompiled",
                "compiled": compiled,
                "compile_errors": compile_errors,
                "compiled_at": utc_now(),
                "created_at": utc_now(),
            }
        )

        self.rt.store.audit(
            "agent",
            "strategy_compiled",
            {"strategy_id": strategy_id, "compiled": compiled},
            "ok" if compiled else "warning",
        )

        return StrategyResult(
            ok=compiled,
            strategy_id=strategy_id,
            message=(
                f"Strategy '{strategy['name']}' compiled successfully."
                if compiled
                else f"Compilation failed: {compile_errors or 'unknown error'}"
            ),
            data={
                "compiled": compiled,
                "errors": compile_errors,
                "warnings": compile_warnings,
            },
        )

    # ------------------------------------------------------------------ backtest

    def run_backtest(
        self,
        strategy_id: str,
        start_date: str,
        end_date: str,
        parameters: dict[str, Any] | None = None,
    ) -> StrategyResult:
        """Run an MT5 Strategy Tester backtest for a strategy."""
        strategy = self.rt.store.get_strategy(strategy_id)
        if not strategy:
            return StrategyResult(
                ok=False,
                strategy_id=strategy_id,
                message=f"Strategy {strategy_id} not found",
                data={},
            )

        if strategy["status"] not in ("compiled", "backtested", "shadow", "demo", "live"):
            return StrategyResult(
                ok=False,
                strategy_id=strategy_id,
                message="Strategy must be compiled before backtesting",
                data={"status": strategy["status"]},
            )

        try:
            result = self.rt.call(
                "terminal.backtest",
                {
                    "strategy_id": strategy_id,
                    "symbol": strategy["symbol"],
                    "timeframe": strategy["timeframe"],
                    "start_date": start_date,
                    "end_date": end_date,
                    "parameters": parameters or {},
                    "mql5_code": strategy["mql5_code"],
                },
            )
        except Exception as exc:  # noqa: BLE001
            return StrategyResult(
                ok=False,
                strategy_id=strategy_id,
                message=f"MT5 backtest not available: {exc}",
                data={"backtested": False},
            )

        backtest_id = uuid.uuid4().hex
        now = utc_now()

        backtest = {
            "id": backtest_id,
            "strategy_id": strategy_id,
            "version": strategy["version"],
            "start_date": start_date,
            "end_date": end_date,
            "symbol": strategy["symbol"],
            "timeframe": strategy["timeframe"],
            "initial_balance": result.get("initial_balance", 10000.0),
            "final_balance": result.get("final_balance"),
            "gross_profit": result.get("gross_profit"),
            "gross_loss": result.get("gross_loss"),
            "net_profit": result.get("net_profit"),
            "profit_factor": result.get("profit_factor"),
            "total_trades": result.get("total_trades"),
            "winning_trades": result.get("winning_trades"),
            "losing_trades": result.get("losing_trades"),
            "win_rate": result.get("win_rate"),
            "max_drawdown": result.get("max_drawdown"),
            "max_drawdown_pct": result.get("max_drawdown_pct"),
            "sharpe_ratio": result.get("sharpe_ratio"),
            "recovery_factor": result.get("recovery_factor"),
            "expectancy": result.get("expectancy"),
            "equity_curve": result.get("equity_curve", []),
            "trades": result.get("trades", []),
            "parameters": parameters or {},
            "tester_report": result.get("tester_report", {}),
            "created_at": now,
        }

        self.rt.store.insert_strategy_backtest(backtest)

        # Update strategy with backtest summary
        self.rt.store.update_strategy(
            strategy_id,
            {
                "status": "backtested",
                "p_up": result.get("win_rate", 0.0) / 100.0
                if result.get("win_rate")
                else None,
                "total_trades": result.get("total_trades"),
                "winning_trades": result.get("winning_trades"),
                "losing_trades": result.get("losing_trades"),
                "win_rate": result.get("win_rate"),
                "profit_factor": result.get("profit_factor"),
                "max_drawdown": result.get("max_drawdown"),
                "sharpe_ratio": result.get("sharpe_ratio"),
                "initial_balance": result.get("initial_balance"),
                "final_balance": result.get("final_balance"),
                "backtest_id": backtest_id,
            },
        )

        self.rt.store.audit(
            "agent",
            "strategy_backtested",
            {
                "strategy_id": strategy_id,
                "backtest_id": backtest_id,
                "net_profit": result.get("net_profit"),
                "win_rate": result.get("win_rate"),
            },
            "ok",
        )

        return StrategyResult(
            ok=True,
            strategy_id=strategy_id,
            message=(
                f"Backtest complete: {result.get('total_trades', 0)} trades, "
                f"win rate {result.get('win_rate', 0):.1f}%, "
                f"profit factor {result.get('profit_factor', 0):.2f}, "
                f"max DD {result.get('max_drawdown', 0):.2f}"
            ),
            data={
                "backtest_id": backtest_id,
                "result": backtest,
            },
        )

    # ------------------------------------------------------------------ list / get

    def list_strategies(self, status: str | None = None) -> list[dict[str, Any]]:
        return self.rt.store.list_strategies(status=status)

    def get_strategy(self, strategy_id: str) -> dict[str, Any] | None:
        return self.rt.store.get_strategy(strategy_id)

    def get_backtest(self, backtest_id: str) -> dict[str, Any] | None:
        return self.rt.store.get_strategy_backtest(backtest_id)

    def list_backtests(self, strategy_id: str) -> list[dict[str, Any]]:
        return self.rt.store.list_strategy_backtests(strategy_id)
