"""Position lifecycle manager for agent-managed positions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from backend.ignite.agent.config import AgentConfig
from backend.ignite.services.runtime import Runtime


@dataclass
class AgentPosition:
    ticket: str
    symbol: str
    side: str
    entry_price: float
    volume: float
    sl: float | None
    tp: float | None
    trail_sl: float | None
    scale_in_count: int
    scale_out_count: int
    max_favourable_atr: float | None
    max_adverse_atr: float | None
    opened_at: str
    closed_at: str | None
    close_reason: str | None
    realised_pnl: float | None
    r_multiple: float | None


@dataclass
class PositionAction:
    type: Literal["TRAIL_SL", "SCALE_IN", "SCALE_OUT", "CLOSE"]
    ticket: str
    new_sl: float | None = None
    volume: float | None = None
    reason: str | None = None


class PositionManager:
    """Manages agent positions through full lifecycle."""

    def __init__(self, rt: Runtime, config: AgentConfig) -> None:
        self.rt = rt
        self.config = config

    def manage_all(self) -> list["PositionAction"]:
        actions = []
        positions = self.rt.store.agent_positions()
        for pos_data in positions:
            pos = AgentPosition(**pos_data)
            actions.extend(self.manage_position(pos))
        return actions

    def manage_position(self, pos: AgentPosition) -> list["PositionAction"]:
        actions = []

        # 1. Check exit conditions
        exit_reason = self.check_exit_conditions(pos)
        if exit_reason:
            actions.append(PositionAction(type="CLOSE", ticket=pos.ticket, reason=exit_reason))
            return actions

        # 2. Trail SL
        new_sl = self.trail_sl(pos)
        if new_sl is not None:
            actions.append(PositionAction(type="TRAIL_SL", ticket=pos.ticket, new_sl=new_sl))

        # 3. Scale in
        scale_in = self.check_scale_in(pos)
        if scale_in:
            actions.append(scale_in)

        # 4. Scale out
        scale_out = self.check_scale_out(pos)
        if scale_out:
            actions.append(scale_out)

        return actions

    def trail_sl(self, pos: AgentPosition, atr: float | None = None) -> float | None:
        """Calculate new trailing SL."""
        if atr is None:
            atr = self._get_atr(pos.symbol)

        if pos.side.upper() == "BUY":
            new_sl = pos.entry_price - self.config.trail_sl_atr * atr
            if pos.trail_sl is None or new_sl > pos.trail_sl:
                return round(new_sl, 2)
        else:
            new_sl = pos.entry_price + self.config.trail_sl_atr * atr
            if pos.trail_sl is None or new_sl < pos.trail_sl:
                return round(new_sl, 2)
        return None

    def check_scale_in(self, pos: AgentPosition) -> "PositionAction | None":
        """Check if we should scale in (add to winner)."""
        if pos.scale_in_count >= 2:
            return None

        # Check if price moved 1.5R in our favour
        atr = self._get_atr(pos.symbol)
        if atr is None:
            return None

        move_atr = self._calculate_move_atr(pos)
        if move_atr < 1.5:
            return None

        # 50% of original size
        new_volume = round(pos.volume * 0.5, 2)
        if new_volume < 0.01:
            return None

        return PositionAction(
            type="SCALE_IN",
            ticket=pos.ticket,
            volume=new_volume,
            reason=f"Scale in at {move_atr:.1f}R",
        )

    def check_scale_out(self, pos: AgentPosition) -> "PositionAction | None":
        """Check if we should scale out (partial TP)."""
        if pos.scale_out_count >= len(self.config.scale_out_levels):
            return None

        current_level = self.config.scale_out_levels[pos.scale_out_count]
        # Check if price reached the next R level
        move_atr = self._calculate_move_atr(pos)
        if move_atr < current_level:
            return None

        # Close 1/3 of position at each level
        volume = round(pos.volume / 3, 2)
        if volume < 0.01:
            volume = pos.volume

        return PositionAction(
            type="SCALE_OUT",
            ticket=pos.ticket,
            volume=volume,
            reason=f"Scale out at {current_level}R",
        )

    def check_exit_conditions(self, pos: AgentPosition, current_signal: str | None = None) -> str | None:
        """Check if position should be closed."""
        # Signal reversal
        if current_signal:
            if pos.side.upper() == "BUY" and current_signal == "SHORT":
                return "SIGNAL_REVERSAL"
            if pos.side.upper() == "SELL" and current_signal == "LONG":
                return "SIGNAL_REVERSAL"

        # Daily loss limit
        try:
            from backend.ignite.services.broker import realised_pnl_today
            pnl = realised_pnl_today(self.rt.mcp, self.rt.clock())
            equity = float(self.rt.account().get("equity") or 0.0)
            if equity > 0 and pnl < -equity * self.config.daily_loss_limit_pct:
                return "DAILY_LOSS_LIMIT"
        except Exception:
            pass

        # Session end
        now = datetime.now(timezone.utc)
        if now.hour >= self.config.session_end_hour:
            return "SESSION_END"

        # Correlation breach (simplified)
        if self._check_correlation_breach(pos):
            return "CORRELATION_BREACH"

        # Max adverse excursion
        if pos.max_adverse_atr and pos.max_adverse_atr > 3.0:
            return "MAX_ADVERSE_EXCURSION"

        return None

    def _get_atr(self, symbol: str) -> float | None:
        try:
            row = self.rt.store.latest_analysis(symbol, self.config.timeframe)
            if row:
                features = row.get("features", {})
                return features.get("atr")
        except Exception:
            pass
        return None

    def _calculate_move_atr(self, pos: AgentPosition) -> float:
        """Calculate current move in ATR terms."""
        try:
            atr = self._get_atr(pos.symbol)
            if atr is None or atr == 0:
                return 0.0

            current_price = self._get_current_price(pos.symbol)
            if current_price is None:
                return 0.0

            if pos.side.upper() == "BUY":
                move = current_price - pos.entry_price
            else:
                move = pos.entry_price - current_price

            return move / atr
        except Exception:
            return 0.0

    def _get_current_price(self, symbol: str) -> float | None:
        try:
            bid, ask = self.rt.quote(symbol)
            return (bid + ask) / 2
        except Exception:
            return None

    def _check_correlation_breach(self, pos: AgentPosition) -> bool:
        """Check if adding this position would breach correlation limits."""
        positions = self.rt.store.agent_positions()
        if len(positions) < 2:
            return False

        # Simplified: check if we already have a position in same direction
        same_direction = sum(1 for p in positions if p["side"].upper() == pos.side.upper() and p["ticket"] != pos.ticket)
        return same_direction >= self.config.max_concurrent_positions