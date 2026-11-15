"""Position lifecycle manager for agent-managed positions."""

from __future__ import annotations

import json
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
    managed_by_agent: int = 1
    last_managed_at: str | None = None


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
        if not self._is_enabled() or self.rt.kill_switch():
            return []
        self._sync_positions()
        actions = []
        positions = self.rt.store.agent_positions()
        for pos_data in positions:
            pos = AgentPosition(**pos_data)
            for action in self.manage_position(pos):
                actions.append(action)
                self._apply_action(action, pos)
        return actions

    def _is_enabled(self) -> bool:
        config = self.rt.store.agent_config()
        return bool(config and config.get("enabled"))

    def _sync_positions(self) -> None:
        live = self.rt.positions()
        live_tickets = {str(position["ticket"]) for position in live}
        for position in live:
            if not str(position.get("comment") or "").startswith("ignite "):
                continue
            existing = self.rt.store.agent_position(str(position["ticket"])) or {}
            self.rt.store.upsert_agent_position(
                {
                    "ticket": str(position["ticket"]),
                    "symbol": position["symbol"],
                    "side": position["side"],
                    "entry_price": position["price_open"],
                    "volume": position["lots"],
                    "sl": position.get("sl"),
                    "tp": position.get("tp"),
                    "opened_at": position["open_time"] or datetime.now(timezone.utc).isoformat(),
                    "managed_by_agent": 1,
                    "trail_sl": existing.get("trail_sl"),
                    "scale_in_count": existing.get("scale_in_count", 0),
                    "scale_out_count": existing.get("scale_out_count", 0),
                    "max_favourable_atr": existing.get("max_favourable_atr"),
                    "max_adverse_atr": existing.get("max_adverse_atr"),
                    "last_managed_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        for position in self.rt.store.agent_positions():
            if position["ticket"] not in live_tickets:
                self.rt.store.close_agent_position(
                    position["ticket"], "BROKER_CLOSED", 0.0, 0.0
                )

    def _apply_action(self, action: "PositionAction", pos: "AgentPosition") -> None:
        from backend.ignite.services.broker import close_position, modify_position_sl_tp

        try:
            with self.rt.execution_lock:
                if action.type == "TRAIL_SL":
                    modify_position_sl_tp(
                        self.rt.mcp, pos.symbol, action.ticket, action.new_sl, pos.tp
                    )
                elif action.type == "CLOSE":
                    close_position(self.rt.mcp, pos.symbol, action.ticket)
                    self.rt.store.close_agent_position(
                        action.ticket, action.reason or "AGENT_EXIT", 0.0, 0.0
                    )
                elif action.type == "SCALE_OUT":
                    raise RuntimeError("MT5 MCP close tool does not support partial volume")
            self.rt.store.audit(
                "agent",
                f"position_{action.type.lower()}",
                {"ticket": action.ticket, "reason": action.reason},
                "ok",
            )
        except Exception as exc:  # noqa: BLE001 - preserve broker failure in audit
            self.rt.store.audit(
                "agent",
                f"position_{action.type.lower()}_failed",
                {"ticket": action.ticket, "reason": action.reason},
                str(exc),
            )

    def manage_position(self, pos: AgentPosition) -> list["PositionAction"]:
        actions = []

        # 1. Check exit conditions
        exit_reason = self.check_exit_conditions(pos)
        if exit_reason:
            actions.append(PositionAction(type="CLOSE", ticket=pos.ticket, reason=exit_reason))
            return actions

        # 2. Track MFE/MAE (maximum favorable/adverse excursion in ATR)
        self._update_excursion(pos)

        # 3. Trail SL
        new_sl = self.trail_sl(pos)
        if new_sl is not None:
            actions.append(PositionAction(type="TRAIL_SL", ticket=pos.ticket, new_sl=new_sl))

        return actions

    def _update_excursion(self, pos: AgentPosition) -> None:
        """Update maximum favorable/adverse excursion in ATR terms."""
        atr = self._get_atr(pos.symbol)
        if atr is None or atr == 0:
            return
        
        current_price = self._get_current_price(pos.symbol)
        if current_price is None:
            return
        
        if pos.side.upper() == "BUY":
            move = current_price - pos.entry_price
        else:
            move = pos.entry_price - current_price
        
        move_atr = move / atr
        
        # Update max favourable/adverse
        max_fav = max(0.0, move_atr)
        max_adv = max(0.0, -move_atr)
        
        # Get current values from store
        stored = self.rt.store.agent_position(pos.ticket)
        if stored:
            current_fav = float(stored.get("max_favourable_atr") or 0.0)
            current_adv = float(stored.get("max_adverse_atr") or 0.0)
            
            new_fav = max(current_fav, max_fav)
            new_adv = max(current_adv, max_adv)
            
            if new_fav > current_fav or new_adv > current_adv:
                self.rt.store.upsert_agent_position({
                    "ticket": pos.ticket,
                    "symbol": pos.symbol,
                    "side": pos.side,
                    "entry_price": pos.entry_price,
                    "volume": pos.volume,
                    "sl": pos.sl,
                    "tp": pos.tp,
                    "opened_at": pos.opened_at,
                    "managed_by_agent": pos.managed_by_agent,
                    "trail_sl": pos.trail_sl,
                    "scale_in_count": pos.scale_in_count,
                    "scale_out_count": pos.scale_out_count,
                    "max_favourable_atr": new_fav,
                    "max_adverse_atr": new_adv,
                    "last_managed_at": datetime.now(timezone.utc).isoformat(),
                })

    def trail_sl(self, pos: AgentPosition, atr: float | None = None) -> float | None:
        """Calculate new trailing SL."""
        if atr is None:
            atr = self._get_atr(pos.symbol)

        current_price = self._get_current_price(pos.symbol)
        if current_price is None:
            return None
        if pos.side.upper() == "BUY":
            if current_price <= pos.entry_price:
                return None
            new_sl = min(
                current_price - self.config.trail_sl_atr * atr,
                current_price - 0.01,
            )
            if pos.sl is None or new_sl > pos.sl:
                return round(new_sl, 2)
        else:
            if current_price >= pos.entry_price:
                return None
            new_sl = max(
                current_price + self.config.trail_sl_atr * atr,
                current_price + 0.01,
            )
            if pos.sl is None or new_sl < pos.sl:
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
        pnl = self.rt.ledger.daily()
        if not pnl.available:
            return "DAILY_PNL_UNAVAILABLE"
        if pnl.blocked:
            return "DAILY_LOSS_LIMIT"

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
                features = json.loads(row.get("features_json") or "{}")
                atr = features.get("atr")
                return float(atr) if atr is not None else None
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