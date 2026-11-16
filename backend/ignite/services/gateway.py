"""The only broker write path.

The agent authors the trade. This gateway validates the broker and desk
contract, sends the order, binds the fill to the returned ticket, and proves
the position is protected. It rejects; it never rewrites the agent's size.

Two write paths, nothing else (PRD Invariant #3):

- Entries: draft/guard chain -> ``place`` (``execute_draft_autonomous`` or the
  confirm->token->``execute_draft`` handshake).
- Position management (SL/TP modify, close — always risk-reducing):
  ``modify`` / ``close`` directly. These must NOT go through the entry draft
  path: news blackout, margin and drift guards are entry checks, and the kill
  switch must always allow closes (PRD Invariant #1/#5).

Agent and engine code must never call ``broker`` MCP write tools directly —
every write goes through this gateway so the guards and audit apply.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from backend.ignite.services import broker
from backend.ignite.services.broker import BrokerError


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    side: str
    lots: float
    sl: float
    tp: float
    decision_id: str
    comment: str = "ignite agent"
    order_type: str = "market"


@dataclass(frozen=True)
class OrderResult:
    ok: bool
    code: str
    detail: str
    position_ticket: str | None = None
    fill_price: float | None = None
    unprotected: bool = False


class AgentExecutionGateway:
    def __init__(self, rt: Any) -> None:
        self._rt = rt

    # ---------------------------------------------------------------- validation

    def validate(self, req: OrderRequest) -> OrderResult:
        rt = self._rt
        config = rt.config()

        if rt.kill_switch():
            return self._reject(req, "KILL_SWITCH", "kill switch is engaged")
        if config.operating_mode != "autonomous":
            return self._reject(
                req, "MODE", f"operating mode is {config.operating_mode}"
            )
        if config.execution_mode == "shadow":
            return self._reject(req, "SHADOW_MODE", "execution mode is shadow; order not sent")

        watched = {row["symbol"] for row in rt.store.list_symbols()}
        if req.symbol not in watched:
            return self._reject(req, "NOT_WATCHED", f"{req.symbol} is not on the watchlist")

        try:
            spec = rt.spec(req.symbol)
        except Exception as exc:  # noqa: BLE001
            return self._reject(req, "SPEC", f"no symbol spec: {exc}")

        try:
            terminal = rt._call("terminal_get_info").get("terminal") or {}
            connection = (terminal.get("connection") or {}).get("state")
            if connection != "synchronized":
                return self._reject(
                    req, "MARKET_CLOSED", f"terminal state is {connection!r}"
                )
            if terminal.get("trade_allowed") is False:
                return self._reject(req, "MARKET_CLOSED", "trading is disabled")
        except BrokerError as exc:
            return self._reject(req, "MARKET_CLOSED", str(exc))

        try:
            bid, ask = rt.quote(req.symbol)
            spread_points = abs(ask - bid) / spec.point if spec.point else 0.0
        except BrokerError as exc:
            return self._reject(req, "MARKET_CLOSED", str(exc))
        if spread_points > config.to_risk_config().max_spread_points:
            return self._reject(
                req, "SPREAD", f"spread {spread_points:.0f} points above ceiling"
            )

        try:
            blackout = rt.news.blackout_at(rt.now_utc())
        except Exception as exc:  # noqa: BLE001 - unknown news state blocks entries
            return self._reject(req, "NEWS_BLACKOUT", f"news state unavailable: {exc}")
        if blackout is not None:
            return self._reject(
                req, "NEWS_BLACKOUT", f"blackout until {blackout.get('end')}"
            )

        pnl = rt.ledger.daily()
        if not pnl.available:
            return self._reject(req, "DAILY_LOSS", "daily PnL source unavailable")
        if pnl.blocked:
            return self._reject(
                req, "DAILY_LOSS", f"daily loss {pnl.total_usd:.2f} beyond limit"
            )

        try:
            positions = rt.positions()
        except BrokerError as exc:
            return self._reject(req, "BROKER", str(exc))

        if len(positions) >= config.max_concurrent_positions:
            return self._reject(req, "MAX_POSITIONS", "max concurrent positions reached")
        same_symbol = [p for p in positions if p["symbol"] == req.symbol]
        if len(same_symbol) >= config.max_positions_per_symbol:
            return self._reject(
                req, "MAX_PER_SYMBOL", f"{req.symbol} already has {len(same_symbol)}"
            )

        reference = ask if req.side.lower() == "buy" else bid
        stop_distance = abs(float(reference) - float(req.sl))
        requested_risk = stop_distance * req.lots * spec.contract_size
        open_risk = rt.ledger.open_risk_usd(positions)
        equity = float((rt.account() or {}).get("equity") or 0.0)
        if equity > 0 and (open_risk + requested_risk) > equity * config.portfolio_risk_cap_pct:
            return self._reject(
                req,
                "PORTFOLIO_RISK",
                f"open risk {open_risk:.2f} + {requested_risk:.2f} above cap",
            )

        if not self._valid_lots(req.lots, spec):
            return self._reject(
                req,
                "LOTS",
                f"{req.lots} is not a multiple of {spec.volume_step} within "
                f"[{spec.volume_min}, {spec.volume_max}]",
            )

        if not self._valid_stops(req, spec, reference):
            return self._reject(
                req,
                "STOPS",
                f"SL/TP invalid for {req.side} at {reference} "
                f"(minimum {spec.stops_level} points)",
            )

        try:
            margin = rt.mcp.call_tool(
                "trade_order_calc_margin",
                {"symbol": req.symbol, "type": req.side, "volume": req.lots},
            ).get("margin")
            free = float((rt.account() or {}).get("margin_free") or 0.0)
            if margin is None:
                return self._reject(req, "MARGIN", "margin requirement unavailable")
            if float(margin) > free:
                return self._reject(req, "MARGIN", f"need {margin}, free {free}")
        except BrokerError as exc:
            return self._reject(req, "MARGIN", f"margin check failed: {exc}")
        except Exception as exc:  # noqa: BLE001 - unknown margin blocks entries
            return self._reject(req, "MARGIN", f"margin check failed: {exc}")

        return OrderResult(True, "OK", "validated")

    # ------------------------------------------------------------------- writes

    def place(self, req: OrderRequest) -> OrderResult:
        rt = self._rt
        with rt.execution_lock:
            result = self.validate(req)
            if not result.ok:
                return result

            if not rt.store.begin_order(
                req.decision_id,
                req.symbol,
                req.side,
                req.lots,
                req.sl,
                req.tp,
                req.comment,
            ):
                return self._reject(req, "DUPLICATE", "decision already submitted")

            try:
                sent = broker.send_market_order(
                    rt.mcp,
                    req.symbol,
                    req.side,
                    req.lots,
                    req.sl,
                    req.tp,
                    req.comment,
                )
            except BrokerError as exc:
                rt.store.update_order(req.decision_id, state="rejected", error=str(exc))
                return self._reject(req, "BROKER", str(exc))

            order_id, position_id = broker.extract_order_ticket(sent)
            ticket = position_id or order_id
            if not ticket:
                rt.store.update_order(
                    req.decision_id, state="unknown", broker_json=str(sent)
                )
                return self._reject(req, "UNRESOLVED", "broker returned no ticket")

            rt.store.update_order(
                req.decision_id,
                state="sent",
                ticket=order_id,
                position_id=ticket,
            )

            position = self._await_position_by_ticket(req.symbol, ticket, timeout_s=5.0)
            if position is None:
                rt.store.update_order(req.decision_id, state="unresolved")
                return OrderResult(
                    False, "UNRESOLVED", "no position matched the returned ticket"
                )

            if self._is_protected(position, req, rt):
                rt.store.update_order(
                    req.decision_id, state="filled", filled_price=position.get("price_open")
                )
                self._event(
                    "order.filled",
                    req,
                    {"ticket": ticket, "price": position.get("price_open")},
                )
                return OrderResult(
                    True,
                    "OK",
                    "filled and protected",
                    position_ticket=ticket,
                    fill_price=position.get("price_open"),
                )

            # One repair attempt, then flatten rather than leave naked risk.
            try:
                broker.modify_position_sl_tp(
                    rt.mcp, req.symbol, ticket, req.sl, req.tp
                )
            except BrokerError as exc:
                self._event("order.protection_retry_failed", req, {"error": str(exc)})
            refreshed = self._await_position_by_ticket(req.symbol, ticket, timeout_s=2.0)
            if refreshed is not None and self._is_protected(refreshed, req, rt):
                rt.store.update_order(req.decision_id, state="filled")
                return OrderResult(
                    True, "OK", "filled and protected", position_ticket=ticket
                )

            try:
                broker.close_position(rt.mcp, req.symbol, ticket)
            except BrokerError as exc:
                self._event("order.flatten_failed", req, {"error": str(exc)})
            rt.store.update_order(
                req.decision_id, state="protection_failed", error="SL/TP missing"
            )
            self._event("order.protection_failed", req, {"ticket": ticket})
            return OrderResult(
                False,
                "PROTECTION_FAILED",
                "fill arrived without SL/TP; position closed",
                position_ticket=ticket,
                unprotected=True,
            )

    def close(self, ticket: str, reason: str = "MANUAL") -> OrderResult:
        rt = self._rt
        try:
            position = next(
                (p for p in rt.positions() if str(p["ticket"]) == str(ticket)), None
            )
        except BrokerError as exc:
            return OrderResult(False, "BROKER", str(exc))
        if position is None:
            return OrderResult(False, "UNRESOLVED", f"no open position {ticket}")

        # Kill switch allows closes (reducing risk)
        # No kill switch check needed here - always allow close

        with rt.execution_lock:
            try:
                broker.close_position(rt.mcp, position["symbol"], str(ticket))
            except BrokerError as exc:
                return OrderResult(False, "BROKER", str(exc))
        rt.store.append_agent_event(
            "position.close_requested",
            symbol=position["symbol"],
            payload={"ticket": str(ticket), "reason": reason},
        )
        return OrderResult(True, "OK", "close sent", position_ticket=str(ticket))

    def modify(
        self, ticket: str, sl: float | None, tp: float | None
    ) -> OrderResult:
        rt = self._rt
        try:
            position = next(
                (p for p in rt.positions() if str(p["ticket"]) == str(ticket)), None
            )
        except BrokerError as exc:
            return OrderResult(False, "BROKER", str(exc))
        if position is None:
            return OrderResult(False, "UNRESOLVED", f"no open position {ticket}")

        # Kill switch: allow modifications that reduce risk, block those that increase it
        if rt.kill_switch():
            current_sl = position.get("sl")
            current_tp = position.get("tp")
            side = position.get("side", "").upper()
            
            # Check if modification increases risk
            if sl is not None and current_sl is not None:
                if side == "BUY" and sl < current_sl:
                    return OrderResult(False, "KILL_SWITCH", "modification widens SL (increases risk)")
                if side == "SELL" and sl > current_sl:
                    return OrderResult(False, "KILL_SWITCH", "modification widens SL (increases risk)")
            if tp is not None and current_tp is not None:
                if side == "BUY" and tp < current_tp:
                    return OrderResult(False, "KILL_SWITCH", "modification widens TP (increases risk)")
                if side == "SELL" and tp > current_tp:
                    return OrderResult(False, "KILL_SWITCH", "modification widens TP (increases risk)")

        with rt.execution_lock:
            try:
                broker.modify_position_sl_tp(
                    rt.mcp, position["symbol"], str(ticket), sl, tp
                )
            except BrokerError as exc:
                return OrderResult(False, "BROKER", str(exc))
        return OrderResult(True, "OK", "modify sent", position_ticket=str(ticket))

    def scale(
        self, ticket: str, side: str, volume: float, sl: float | None, tp: float | None
    ) -> OrderResult:
        """Scale position in/out. For reduce: close and reopen remainder (MT5 limitation)."""
        rt = self._rt
        # Kill-switch check: block scale-in, allow scale-out only
        if rt.kill_switch() and side == "add":
            return OrderResult(False, "KILL_SWITCH", "scale-in blocked by kill switch")
        try:
            position = next(
                (p for p in rt.positions() if str(p["ticket"]) == str(ticket)), None
            )
        except BrokerError as exc:
            return OrderResult(False, "BROKER", str(exc))
        if position is None:
            return OrderResult(False, "UNRESOLVED", f"no open position {ticket}")

        agent_pos = rt.store.agent_position(ticket)
        if not agent_pos:
            return OrderResult(False, "UNRESOLVED", f"no agent position {ticket}")

        if side == "reduce":
            # Validate volume
            current_volume = float(position.get("lots") or position.get("volume") or 0.0)
            if volume <= 0 or volume > current_volume:
                return OrderResult(False, "VOLUME", f"reduce volume {volume} exceeds current {current_volume}")
            if volume < rt.spec(position["symbol"]).volume_step - 1e-12:
                return OrderResult(False, "LOTS", f"volume {volume} below step")

            # MT5 doesn't support partial close directly - close full and reopen remainder
            remainder = round(current_volume - volume, 2)
            if remainder < rt.spec(position["symbol"]).volume_min - 1e-12:
                return OrderResult(False, "VOLUME", f"remainder {remainder} below minimum")

            symbol = position["symbol"]
            current_sl = sl if sl is not None else position.get("sl")
            current_tp = tp if tp is not None else position.get("tp")
            entry_price = position.get("price_open")
            position_side = position["side"]

            # Close full position on broker
            with rt.execution_lock:
                try:
                    broker.close_position(rt.mcp, symbol, str(ticket))
                except BrokerError as exc:
                    return OrderResult(False, "BROKER", str(exc))

            # Mark old position as closed in agent store
            rt.store.close_agent_position(ticket, "SCALE_OUT", 0.0, 0.0)

            # Reopen remainder if > 0
            if remainder > 0:
                try:
                    sent = broker.send_market_order(
                        rt.mcp, symbol, position_side, remainder, current_sl, current_tp, "ignite agent scale"
                    )
                except BrokerError as exc:
                    return OrderResult(False, "BROKER", str(exc))
                
                order_id, new_ticket = broker.extract_order_ticket(sent)
                new_ticket = new_ticket or order_id
                if not new_ticket:
                    return OrderResult(False, "UNRESOLVED", "remainder reopen failed")

                # Create new agent position for remainder
                rt.store.upsert_agent_position({
                    "ticket": new_ticket,
                    "symbol": symbol,
                    "side": position_side.upper(),
                    "entry_price": entry_price,
                    "volume": remainder,
                    "sl": current_sl,
                    "tp": current_tp,
                    "opened_at": datetime.now(timezone.utc).isoformat(),
                    "managed_by_agent": 1,
                    "trail_sl": current_sl,
                    "scale_in_count": agent_pos.get("scale_in_count", 0),
                    "scale_out_count": agent_pos.get("scale_out_count", 0) + 1,
                    "max_favourable_atr": agent_pos.get("max_favourable_atr", 0.0),
                    "max_adverse_atr": agent_pos.get("max_adverse_atr", 0.0),
                    "last_managed_at": datetime.now(timezone.utc).isoformat(),
                    "status": "partial",
                })

            rt.store.append_agent_event(
                "position.scaled",
                symbol=symbol,
                payload={"ticket": ticket, "side": "reduce", "volume": volume, "remainder": remainder},
            )
            return OrderResult(True, "OK", f"reduced by {volume}", position_ticket=new_ticket if remainder > 0 else ticket)

        elif side == "add":
            # Scale in - add to position (new order)
            if volume <= 0:
                return OrderResult(False, "VOLUME", "add volume must be positive")
            
            symbol = position["symbol"]
            position_side = position["side"]
            current_sl = sl if sl is not None else position.get("sl")
            current_tp = tp if tp is not None else position.get("tp")

            with rt.execution_lock:
                try:
                    sent = broker.send_market_order(
                        rt.mcp, symbol, position_side, volume, current_sl, current_tp, "ignite agent scale in"
                    )
                except BrokerError as exc:
                    return OrderResult(False, "BROKER", str(exc))

            order_id, new_ticket = broker.extract_order_ticket(sent)
            new_ticket = new_ticket or order_id
            if not new_ticket:
                return OrderResult(False, "UNRESOLVED", "scale in order failed")

            rt.store.upsert_agent_position({
                "ticket": new_ticket,
                "symbol": symbol,
                "side": position["side"].upper(),
                "entry_price": position.get("price_open"),
                "volume": volume,
                "sl": current_sl,
                "tp": current_tp,
                "opened_at": datetime.now(timezone.utc).isoformat(),
                "managed_by_agent": 1,
                "trail_sl": current_sl,
                "scale_in_count": agent_pos.get("scale_in_count", 0) + 1,
                "scale_out_count": agent_pos.get("scale_out_count", 0),
                "max_favourable_atr": agent_pos.get("max_favourable_atr", 0.0),
                "max_adverse_atr": agent_pos.get("max_adverse_atr", 0.0),
                "last_managed_at": datetime.now(timezone.utc).isoformat(),
                "status": "open",
            })

            rt.store.append_agent_event(
                "position.scaled",
                symbol=symbol,
                payload={"ticket": ticket, "side": "add", "volume": volume, "new_ticket": new_ticket},
            )
            return OrderResult(True, "OK", f"added {volume}", position_ticket=new_ticket)

        else:
            return OrderResult(False, "INVALID", f"unknown scale side: {side}")

    def _reject(self, req: OrderRequest, code: str, detail: str) -> OrderResult:
        self._event("order.rejected", req, {"code": code, "detail": detail})
        return OrderResult(False, code, detail)

    def _event(self, kind: str, req: OrderRequest, payload: dict[str, Any]) -> None:
        try:
            self._rt.store.append_agent_event(
                kind,
                severity="warning" if not kind.endswith("filled") else "info",
                symbol=req.symbol,
                decision_id=req.decision_id,
                payload=payload,
            )
        except Exception:  # noqa: BLE001 - audit must not break execution
            pass

    def _await_position_by_ticket(
        self, symbol: str, ticket: str, timeout_s: float
    ) -> dict[str, Any] | None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                for position in self._rt.positions(symbol):
                    if str(position["ticket"]) == str(ticket):
                        return position
            except BrokerError:
                pass
            time.sleep(0.1)
        return None

    @staticmethod
    def _valid_lots(lots: float, spec: Any) -> bool:
        if lots <= 0 or lots < spec.volume_min - 1e-12 or lots > spec.volume_max + 1e-12:
            return False
        step = spec.volume_step or 0.01
        steps = lots / step
        return abs(steps - round(steps)) < 1e-6

    @staticmethod
    def _valid_stops(req: OrderRequest, spec: Any, reference: float) -> bool:
        minimum = (spec.stops_level or 0) * spec.point
        buy = req.side.lower() == "buy"
        if buy:
            if not (req.sl < reference < req.tp):
                return False
        else:
            if not (req.tp < reference < req.sl):
                return False
        if minimum and abs(reference - req.sl) < minimum:
            return False
        if minimum and abs(req.tp - reference) < minimum:
            return False
        return True

    @staticmethod
    def _is_protected(position: dict[str, Any], req: OrderRequest, rt: Any) -> bool:
        point = float(rt.spec(req.symbol).point)
        tolerance = max(point, 1e-9)
        sl = position.get("sl")
        tp = position.get("tp")
        if sl is None or tp is None:
            return False
        return abs(float(sl) - req.sl) <= tolerance and abs(float(tp) - req.tp) <= tolerance
