"""Broker reconciliation service: matches agent positions to broker state."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from backend.ignite.services.runtime import Runtime


@dataclass
class ReconciliationResult:
    """Result of a single position reconciliation."""
    ticket: str
    symbol: str
    action: str  # "synced", "closed", "orphaned", "adopted", "order_resolved"
    detail: str
    old_status: str | None = None
    new_status: str | None = None


class ReconciliationService:
    """Reconciles agent positions with broker state."""

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt

    def run(self) -> list[ReconciliationResult]:
        results: list[ReconciliationResult] = []
        
        # 1. Get live broker positions
        live_positions = self.rt.positions()
        live_by_ticket = {str(p.get("ticket") or p.get("position_id")): p for p in live_positions}
        
        # 2. Get agent positions from store
        agent_positions = self.rt.store.agent_positions(managed_only=True)
        
        # 3. Match agent positions to live broker positions
        for pos in agent_positions:
            ticket = str(pos["ticket"])
            if ticket in live_by_ticket:
                # Position exists in broker - sync it
                result = self._sync_position(pos, live_by_ticket[ticket])
                results.append(result)
                del live_by_ticket[ticket]
            else:
                # Position not in broker - check if closed
                result = self._check_closed_position(pos)
                results.append(result)
        
        # 4. Adopt live positions not in agent store (with "ignite" comment)
        for ticket, live_pos in live_by_ticket.items():
            comment = str(live_pos.get("comment") or "")
            if comment.startswith("ignite"):
                result = self._adopt_position(live_pos)
                results.append(result)
        
        # 5. Reconcile pending orders (state="sent" or "unknown")
        self._reconcile_pending_orders(results)
        
        return results

    def _sync_position(self, agent_pos: dict[str, Any], live_pos: dict[str, Any]) -> ReconciliationResult:
        """Sync agent position with live broker position."""
        ticket = str(agent_pos["ticket"])
        old_sl = agent_pos.get("sl")
        old_tp = agent_pos.get("tp")
        live_sl = live_pos.get("sl")
        live_tp = live_pos.get("tp")
        
        # Update SL/TP if changed
        updates = {}
        if live_sl is not None and live_sl != old_sl:
            updates["sl"] = live_sl
        if live_tp is not None and live_tp != old_tp:
            updates["tp"] = live_tp
        
        # Always update last_synced_at and broker_snapshot_json
        updates["last_synced_at"] = datetime.now(timezone.utc).isoformat()
        updates["broker_snapshot_json"] = json.dumps(live_pos)
        
        # Merge with agent position data
        merged = {**agent_pos, **updates}
        self.rt.store.upsert_agent_position(merged)
        detail = f"Synced SL/TP: sl={live_sl}, tp={live_tp}"
        
        return ReconciliationResult(
            ticket=ticket,
            symbol=agent_pos["symbol"],
            action="synced",
            detail=detail,
            old_status=agent_pos.get("status"),
            new_status="open",
        )

    def _check_closed_position(self, agent_pos: dict[str, Any]) -> ReconciliationResult:
        """Check if agent position was closed on broker."""
        ticket = str(agent_pos["ticket"])
        symbol = agent_pos["symbol"]
        side = agent_pos["side"].lower()
        
        # Get closed trades from broker for today
        from datetime import datetime, timedelta
        end = datetime.now(timezone.utc)
        start = end.replace(hour=0, minute=0, second=0, microsecond=0)
        
        try:
            from backend.ignite.services.broker import closed_trades
            trades = closed_trades(self.rt.mcp, self.rt.clock(), start, end)
        except Exception:
            trades = []
        
        # Find matching closed trade
        for trade in trades:
            if str(trade.get("ticket") or trade.get("position_id")) == ticket:
                # Found closed trade - calculate PnL and R
                net = float(trade.get("net") or trade.get("profit") or 0.0)
                entry = float(trade.get("entry") or agent_pos["entry_price"])
                exit_price = float(trade.get("exit") or trade.get("price") or entry)
                volume = float(trade.get("volume") or agent_pos["volume"])
                sl = float(trade.get("sl") or agent_pos.get("sl") or 0.0)
                
                # Calculate initial risk
                if sl and entry:
                    risk_per_lot = abs(entry - sl)
                    initial_risk = risk_per_lot * volume * self.rt.spec(symbol).contract_size
                else:
                    initial_risk = 1.0
                
                r_multiple = net / initial_risk if initial_risk > 0 else 0.0
                
                # Close the position
                self.rt.store.close_agent_position(
                    ticket, "BROKER_CLOSED", net, r_multiple
                )
                
                return ReconciliationResult(
                    ticket=ticket,
                    symbol=symbol,
                    action="closed",
                    detail=f"Broker closed: PnL={net:.2f}, R={r_multiple:.2f}",
                    old_status=agent_pos.get("status"),
                    new_status="closed",
                )
        
        # No matching closed trade - mark as orphaned
        self.rt.store.upsert_agent_position({
            **agent_pos,
            "status": "orphaned",
            "last_synced_at": datetime.now(timezone.utc).isoformat(),
        })
        
        return ReconciliationResult(
            ticket=ticket,
            symbol=symbol,
            action="orphaned",
            detail="Position not found in broker and no closed trade found",
            old_status=agent_pos.get("status"),
            new_status="orphaned",
        )

    def _adopt_position(self, live_pos: dict[str, Any]) -> ReconciliationResult:
        """Adopt a broker position that has 'ignite' comment but isn't in agent store."""
        ticket = str(live_pos.get("ticket") or live_pos.get("position_id"))
        symbol = live_pos["symbol"]
        side = live_pos.get("side") or live_pos.get("action")
        volume = live_pos.get("volume") or live_pos.get("lots")
        price_open = live_pos.get("price_open")
        sl = live_pos.get("sl")
        tp = live_pos.get("tp")
        open_time = live_pos.get("open_time") or live_pos.get("create_time")
        
        self.rt.store.upsert_agent_position({
            "ticket": ticket,
            "symbol": symbol,
            "side": side.upper() if side else "BUY",
            "entry_price": price_open,
            "volume": volume,
            "sl": sl,
            "tp": tp,
            "opened_at": open_time,
            "managed_by_agent": 1,
            "trail_sl": sl,
            "scale_in_count": 0,
            "scale_out_count": 0,
            "max_favourable_atr": 0.0,
            "max_adverse_atr": 0.0,
            "last_managed_at": datetime.now(timezone.utc).isoformat(),
            "status": "adopted",
            "broker_snapshot_json": json.dumps(live_pos),
        })
        
        return ReconciliationResult(
            ticket=ticket,
            symbol=symbol,
            action="adopted",
            detail=f"Adopted broker position with ignite comment",
            old_status=None,
            new_status="adopted",
        )

    def _reconcile_pending_orders(self, results: list[ReconciliationResult]) -> None:
        """Check orders with state='sent' or 'unknown' against broker positions."""
        # Get orders that need reconciliation
        # This is a simplified version - in production would query orders table
        # For now, we skip this as it requires order table queries
        pass