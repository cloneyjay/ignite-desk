"""Backtest integration: replay decisions with counterfactuals, compute metrics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from backend.ignite.services.runtime import Runtime
from backend.ignite.agent.decision import Decision
from backend.ignite.agent.memory import EpisodicMemory
from backend.ignite.services.ledger import Ledger


@dataclass(frozen=True)
class BacktestReport:
    """Comprehensive backtest report."""
    total_decisions: int
    winning_decisions: int
    losing_decisions: int
    win_rate: float
    total_pnl: float
    sharpe: float
    max_drawdown: float
    avg_r_multiple: float
    profit_factor: float
    expectancy: float
    decisions: list[dict[str, Any]]


class BacktestIntegration:
    """Replays historical decisions with counterfactuals to compute performance metrics."""

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt

    def run(
        self,
        counterfactual_decisions: int = 100,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> BacktestReport:
        """Run backtest over historical decisions."""
        # Get historical decisions from memory
        decisions = self.rt.store.agent_decisions(limit=counterfactual_decisions)
        
        if not decisions:
            return BacktestReport(
                total_decisions=0,
                winning_decisions=0,
                losing_decisions=0,
                win_rate=0.0,
                total_pnl=0.0,
                sharpe=0.0,
                max_drawdown=0.0,
                avg_r_multiple=0.0,
                profit_factor=0.0,
                expectancy=0.0,
                decisions=[],
            )

        # Filter by date range if provided
        if start_date:
            decisions = [d for d in decisions if d["created_at"] >= start_date]
        if end_date:
            decisions = [d for d in decisions if d["created_at"] <= end_date]

        # Compute metrics
        winning = [d for d in decisions if d.get("executed") and d.get("execution_error") is None]
        losing = [d for d in decisions if d.get("executed") and d.get("execution_error") is not None]
        skipped = [d for d in decisions if not d.get("executed")]

        total_pnl = sum(d.get("realised_pnl", 0.0) for d in decisions if d.get("realised_pnl"))
        winning_pnl = sum(d.get("realised_pnl", 0.0) for d in winning)
        losing_pnl = sum(d.get("realised_pnl", 0.0) for d in losing)

        win_rate = len(winning) / len(decisions) if decisions else 0.0
        
        # Calculate R-multiples
        r_multiples = []
        for d in decisions:
            if d.get("executed") and d.get("realised_pnl") is not None and d.get("risk_usd"):
                r = d["realised_pnl"] / d["risk_usd"]
                if not np.isnan(r) and not np.isinf(r):
                    r_multiples.append(r)

        avg_r = np.mean(r_multiples) if r_multiples else 0.0
        winning_r = [r for r in r_multiples if r > 0]
        losing_r = [r for r in r_multiples if r < 0]
        
        profit_factor = abs(sum(winning_r) / sum(losing_r)) if losing_r else float('inf')
        expectancy = np.mean(r_multiples) if r_multiples else 0.0

        # Drawdown calculation
        equity_curve = np.cumsum([d.get("realised_pnl", 0.0) for d in decisions if d.get("realised_pnl")])
        if len(equity_curve) > 0:
            running_max = np.maximum.accumulate(equity_curve)
            drawdowns = running_max - equity_curve
            max_drawdown = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0
        else:
            max_drawdown = 0.0

        # Sharpe ratio (simplified)
        returns = [d.get("realised_pnl", 0.0) for d in decisions if d.get("realised_pnl") is not None]
        if len(returns) > 1:
            sharpe = np.mean(returns) / (np.std(returns) + 1e-9) * np.sqrt(252)
        else:
            sharpe = 0.0

        # Build decision list
        decision_list = []
        for d in decisions:
            decision_list.append({
                "id": d.get("id"),
                "symbol": d.get("symbol"),
                "action": d.get("decision"),
                "executed": d.get("executed", False),
                "pnl": d.get("realised_pnl"),
                "r_multiple": d.get("r_multiple"),
            })

        return BacktestReport(
            total_decisions=len(decisions),
            winning_decisions=len(winning),
            losing_decisions=len(losing),
            win_rate=win_rate,
            total_pnl=total_pnl,
            sharpe=sharpe,
            max_drawdown=max_drawdown,
            avg_r_multiple=avg_r,
            profit_factor=profit_factor,
            expectancy=expectancy,
            decisions=decision_list,
        )