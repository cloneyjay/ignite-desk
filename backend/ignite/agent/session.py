"""Market session awareness for Aegus.

Answers: "Can I trade right now?" — weekend, session hours, kill switch,
daily loss limit, news blackout, terminal state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from backend.ignite.services.runtime import Runtime


@dataclass(frozen=True)
class SessionState:
    """Whether the desk can open new positions."""

    tradable: bool
    reasons: list[str]
    session_open: bool
    kill_switch: bool
    daily_loss_blocked: bool
    blackout_active: bool
    terminal_connected: bool
    terminal_trade_allowed: bool


class SessionGuard:
    """Evaluates whether the desk is in a tradable state."""

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt

    def evaluate(self) -> SessionState:
        """Run every guard and return a SessionState."""
        reasons: list[str] = []

        config = self.rt.config()

        # --- Terminal state ---
        try:
            account = self.rt.account_payload()
            terminal = account.get("terminal", {}) or {}
            terminal_connected = bool(terminal.get("connected"))
            terminal_trade_allowed = bool(terminal.get("trade_allowed"))
        except Exception:  # noqa: BLE001
            terminal_connected = False
            terminal_trade_allowed = False

        if not terminal_connected:
            reasons.append("MT5 terminal not connected")
        if not terminal_trade_allowed:
            reasons.append("MT5 trading is disabled")

        # --- Kill switch ---
        kill_switch = self.rt.kill_switch()
        if kill_switch:
            reasons.append("Kill switch is engaged")

        # --- Daily loss limit ---
        try:
            pnl = self.rt.ledger.daily()
            daily_loss_blocked = bool(pnl.blocked)
            if daily_loss_blocked:
                reasons.append(f"Daily loss limit hit ({pnl.total_usd:.2f})")
        except Exception:  # noqa: BLE001
            daily_loss_blocked = True
            reasons.append("Daily PnL unavailable")

        # --- Session hours ---
        now = datetime.now(timezone.utc)
        session_open = self._is_session_open(now, config)
        if not session_open:
            reasons.append("Outside trading session hours")

        # --- Weekend / market close ---
        if now.weekday() >= 5:  # Saturday=5, Sunday=6
            reasons.append("Market closed (weekend)")

        # --- News blackout ---
        try:
            blackout = self.rt.news.blackout_at(now)
            blackout_active = blackout is not None
            if blackout_active:
                reasons.append(f"News blackout: {blackout.get('name', 'event')}")
        except Exception:  # noqa: BLE001
            blackout_active = False

        tradable = (
            not reasons
            and terminal_connected
            and terminal_trade_allowed
            and not kill_switch
            and not daily_loss_blocked
            and session_open
            and now.weekday() < 5
            and not blackout_active
        )

        return SessionState(
            tradable=tradable,
            reasons=reasons,
            session_open=session_open,
            kill_switch=kill_switch,
            daily_loss_blocked=daily_loss_blocked,
            blackout_active=blackout_active,
            terminal_connected=terminal_connected,
            terminal_trade_allowed=terminal_trade_allowed,
        )

    @staticmethod
    def _is_session_open(now: datetime, config: Any) -> bool:
        """Check if current UTC time is within configured session hours."""
        open_hour = getattr(config, "session_open_hour", 0)
        end_hour = getattr(config, "session_end_hour", 23)
        hour = now.hour
        if open_hour <= end_hour:
            return open_hour <= hour < end_hour
        # Overnight session (e.g., 22:00–06:00)
        return hour >= open_hour or hour < end_hour

    def can_trade(self) -> bool:
        """Convenience: True if all guards pass."""
        return self.evaluate().tradable
