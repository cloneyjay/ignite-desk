"""Realised and floating PnL, and the risk it implies.

The ledger is the only place that answers "how much have we lost today" and
"how much risk is open". It reads the broker, caches briefly, and fails closed:
an unavailable PnL source is a blocked account, never a zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DailyPnl:
    realised_usd: float
    floating_usd: float
    total_usd: float
    day_start_equity: float
    loss_limit_usd: float
    remaining_usd: float
    available: bool
    blocked: bool


class Ledger:
    def __init__(self, rt: Any) -> None:
        self._rt = rt

    def daily(self) -> DailyPnl:
        try:
            realised_payload = self._rt.realised_today() or {}
            realised = float(realised_payload.get("realised_usd") or 0.0)
            account = self._rt.account() or {}
            equity = float(account.get("equity") or 0.0)
            floating = float(account.get("profit") or 0.0)
            if equity <= 0:
                raise ValueError("account equity is not positive")
            day_start = equity - floating - realised
            if day_start <= 0:
                day_start = equity
            limit_pct = float(self._rt.config().daily_loss_limit_pct)
            loss_limit = day_start * limit_pct
            total = realised + floating
            return DailyPnl(
                realised_usd=round(realised, 2),
                floating_usd=round(floating, 2),
                total_usd=round(total, 2),
                day_start_equity=round(day_start, 2),
                loss_limit_usd=round(loss_limit, 2),
                remaining_usd=round(max(0.0, loss_limit + total), 2),
                available=True,
                blocked=total <= -loss_limit,
            )
        except Exception as exc:  # noqa: BLE001 - a guard must fail closed
            self._event(
                "guard.daily_loss_unavailable",
                {"error": str(exc)},
            )
            return DailyPnl(
                realised_usd=0.0,
                floating_usd=0.0,
                total_usd=0.0,
                day_start_equity=0.0,
                loss_limit_usd=0.0,
                remaining_usd=0.0,
                available=False,
                blocked=True,
            )

    def open_risk_usd(self, positions: list[dict[str, Any]] | None = None) -> float:
        rows = positions if positions is not None else self._rt.positions()
        total = 0.0
        for row in rows:
            sl = row.get("sl")
            entry = row.get("price_open")
            lots = row.get("lots") or row.get("volume") or 0.0
            contract = row.get("contract_size") or 0.0
            if sl is None or entry is None or not contract:
                continue
            total += abs(float(entry) - float(sl)) * float(lots) * float(contract)
        return round(total, 2)

    def _event(self, kind: str, payload: dict[str, Any]) -> None:
        store = getattr(self._rt, "store", None)
        if store is None:
            return
        try:
            store.append_agent_event(kind, severity="error", payload=payload)
        except Exception:  # noqa: BLE001 - never let audit break the guard
            pass
