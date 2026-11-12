"""Order execution: guards, confirmation, send, reconcile.

Nothing here is reachable without a single-use confirmation token issued to the
UI dialog. The LLM has no path to this module.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.ignite.services.broker import (
    BrokerError,
    check_market_order,
    extract_order_ticket,
    send_market_order,
)
from backend.ignite.services.runtime import Runtime
from backend.ignite.store.db import utc_now


class ExecutionError(RuntimeError):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail or {}


def _order_side(side: str) -> str:
    """Draft sides are long/short; MT5 order types are buy/sell."""
    if side == "long":
        return "buy"
    if side == "short":
        return "sell"
    raise ExecutionError(409, "bad_side", f"cannot execute side {side!r}")


def evaluate_draft(rt: Runtime, draft: dict[str, Any]) -> dict[str, Any]:
    """Live readiness of a draft. Pure inspection: never sends an order."""
    analysis = rt.store.get_analysis(draft["analysis_id"])
    if analysis is None:
        raise ExecutionError(409, "analysis_missing", "the source analysis is gone")

    checks: list[dict[str, Any]] = []

    def add(code: str, ok: bool, message: str) -> None:
        checks.append({"code": code, "ok": ok, "message": message})

    now = datetime.now(timezone.utc)
    expires_at = datetime.fromisoformat(draft["expires_at"])
    expires_in = max(0, int((expires_at - now).total_seconds()))

    side = draft["side"]
    atr = float(analysis["atr"] or 0.0)
    spec = rt.spec(draft.get("symbol") or analysis["symbol"])
    bid, ask = rt.quote(analysis["symbol"])
    live_reference = ask if side == "long" else bid
    drift_atr = (
        abs(live_reference - float(draft["reference_price"])) / atr if atr > 0 else 0.0
    )
    live_spread = (ask - bid) / spec.point if spec.point > 0 else 0.0
    config = rt.risk_config()

    state = str(draft["state"])
    add(
        "not_blocked",
        not int(draft["blocked"]),
        str(draft["block_reason"] or "draft is not blocked"),
    )
    add("expired", expires_in > 0, f"draft expires in {expires_in}s")
    add("draft_state", state == "draft", f"draft state is {state}")
    add("kill_switch", not rt.kill_switch(), "kill switch is off")
    add(
        "price_drift",
        drift_atr <= config.max_drift_atr,
        f"drift {drift_atr:.2f} ATR (max {config.max_drift_atr:.2f})",
    )
    add(
        "spread",
        live_spread <= config.max_spread_points,
        f"spread {live_spread:.0f} points (max {config.max_spread_points:.0f})",
    )

    open_positions: list[dict[str, Any]] = []
    try:
        open_positions = rt.positions(analysis["symbol"])
    except BrokerError as exc:
        add("positions", False, f"could not read open positions: {exc}")
    else:
        add(
            "no_open_position",
            not open_positions,
            (
                "no open position on the symbol"
                if not open_positions
                else f"{len(open_positions)} position(s) already open on "
                f"{analysis['symbol']} ({open_positions[0]['ticket']})"
            ),
        )

    margin = draft.get("margin")
    worst_case = draft.get("worst_case_usd")
    free_margin = None
    try:
        account = rt.account()
        free_margin = float(account.get("margin_free") or 0.0)
        from backend.ignite.market.symbols import calc_margin, calc_profit

        margin = calc_margin(
            rt.mcp,
            analysis["symbol"],
            _order_side(side),
            float(draft["lots"]),
            live_reference,
        )
        worst_case = calc_profit(
            rt.mcp,
            analysis["symbol"],
            _order_side(side),
            float(draft["lots"]),
            live_reference,
            float(draft["sl"]),
        )
        add(
            "margin",
            margin <= free_margin,
            f"margin {margin:.2f} USD, free {free_margin:.2f} USD",
        )
    except Exception as exc:  # noqa: BLE001 - no margin answer means no trade
        add("margin", False, f"margin check failed: {exc}")

    blackout = None
    try:
        blackout = rt.news.blackout_at(now)
    except Exception as exc:  # noqa: BLE001
        add("news_guard", False, f"economic calendar unavailable: {exc}")
    else:
        add(
            "news_blackout",
            blackout is None,
            (
                "outside blackout windows"
                if blackout is None
                else f"inside blackout for {blackout['name']} ({blackout['currency']})"
            ),
        )

    return {
        "draft_id": draft["id"],
        "analysis_id": draft["analysis_id"],
        "executable": all(check["ok"] for check in checks),
        "checks": checks,
        "expires_in_s": expires_in,
        "live": {
            "bid": bid,
            "ask": ask,
            "reference": live_reference,
            "spread_points": round(live_spread, 1),
            "drift_atr": round(drift_atr, 3),
        },
        "margin": margin,
        "worst_case_usd": worst_case,
        "blackout": blackout,
        "open_positions": open_positions,
    }


def execute_draft(
    rt: Runtime,
    draft_id: str,
    *,
    confirm: bool,
    token: str | None,
) -> dict[str, Any]:
    if not confirm:
        raise ExecutionError(
            400, "confirm_required", "execution must be confirmed in the dialog"
        )
    draft = rt.store.get_draft(draft_id)
    if draft is None:
        raise ExecutionError(404, "draft_not_found", f"no draft {draft_id}")

    # Cheap state checks first, so the user sees *why* rather than "bad token".
    remaining = int(
        (
            datetime.fromisoformat(draft["expires_at"]) - datetime.now(timezone.utc)
        ).total_seconds()
    )
    if int(draft["blocked"]):
        raise ExecutionError(
            409, "not_blocked", str(draft["block_reason"] or "draft is blocked")
        )
    if remaining <= 0:
        if draft["state"] == "draft":
            rt.store.transition_draft(draft_id, "draft", "expired")
        raise ExecutionError(
            409, "expired", "this draft has expired; re-analyse and confirm again"
        )
    if draft["state"] != "draft":
        raise ExecutionError(
            409, "draft_state", f"this draft is already {draft['state']}"
        )

    if not rt.consume_token(token, draft_id):
        raise ExecutionError(
            403,
            "token_invalid",
            "confirmation token is missing, expired or already used",
        )

    analysis = rt.store.get_analysis(draft["analysis_id"])
    if analysis is None:
        raise ExecutionError(409, "analysis_missing", "the source analysis is gone")

    symbol = analysis["symbol"]
    side = draft["side"]
    order_side = _order_side(side)

    with rt.execution_lock:
        state = evaluate_draft(rt, draft)
        if not state["executable"]:
            failing = next(c for c in state["checks"] if not c["ok"])
            rt.store.audit(
                "api",
                "execute_rejected",
                {"draft_id": draft_id, "check": failing},
                "rejected",
            )
            raise ExecutionError(
                409,
                failing["code"],
                failing["message"],
                {"checks": state["checks"]},
            )

        before = {position["ticket"] for position in state["open_positions"]}
        reference = float(state["live"]["reference"])
        lots = float(draft["lots"])
        sl = float(draft["sl"])
        tp = float(draft["tp"])

        try:
            check = check_market_order(rt.mcp, symbol, order_side, lots, sl, tp)
        except BrokerError as exc:
            rt.store.audit(
                "api", "execute_check_failed", {"draft_id": draft_id}, str(exc)
            )
            raise ExecutionError(409, "broker_check_failed", str(exc)) from exc

        if not rt.store.transition_draft(draft_id, "draft", "executing"):
            raise ExecutionError(
                409, "draft_already_used", "this draft is no longer executable"
            )

        comment = f"ignite {draft_id[:8]}"
        sent: dict[str, Any] | None = None
        try:
            sent = send_market_order(rt.mcp, symbol, order_side, lots, sl, tp, comment)
        except Exception as exc:  # noqa: BLE001 - record exactly what the broker said
            rt.store.transition_draft(draft_id, "executing", "failed")
            rt.store.insert_order(
                {
                    "id": uuid.uuid4().hex,
                    "draft_id": draft_id,
                    "created_at": utc_now(),
                    "symbol": symbol,
                    "side": side,
                    "lots": lots,
                    "requested_price": reference,
                    "filled_price": None,
                    "sl": sl,
                    "tp": tp,
                    "ticket": None,
                    "position_id": None,
                    "state": "failed",
                    "comment": comment,
                    "error": str(exc),
                    "broker_json": json.dumps({"error": str(exc)}),
                }
            )
            rt.store.audit(
                "api", "execute_failed", {"draft_id": draft_id}, str(exc)
            )
            rt.events.publish(
                "execution.failed",
                {"draft_id": draft_id, "symbol": symbol, "error": str(exc)},
            )
            raise ExecutionError(
                502, "order_rejected", str(exc), {"broker": sent}
            ) from exc

        order_id, position_id = extract_order_ticket(sent)
        position = _await_position(rt, symbol, before, timeout_s=10.0)
        filled_price = position["price_open"] if position else None
        final_state = "filled" if position else "unconfirmed"
        position_id = (position["ticket"] if position else position_id)

        rt.store.insert_order(
            {
                "id": uuid.uuid4().hex,
                "draft_id": draft_id,
                "created_at": utc_now(),
                "symbol": symbol,
                "side": side,
                "lots": lots,
                "requested_price": reference,
                "filled_price": filled_price,
                "sl": sl,
                "tp": tp,
                "ticket": order_id,
                "position_id": position_id,
                "state": final_state,
                "comment": comment,
                "error": None if position else "no position appeared within 10s",
                "broker_json": json.dumps(sent, default=str),
            }
        )
        rt.store.transition_draft(draft_id, "executing", final_state)
        rt.store.audit(
            "api",
            "execute",
            {"draft_id": draft_id, "lots": lots, "side": side, "price": reference},
            final_state,
        )

    stored = rt.store.get_draft(draft_id)
    order = rt.store.orders_for_draft(draft_id)
    rt.events.publish(
        "execution.done",
        {
            "draft_id": draft_id,
            "symbol": symbol,
            "side": side,
            "lots": lots,
            "filled_price": filled_price,
            "state": final_state,
            "position": position,
        },
    )
    return {
        "ok": True,
        "state": final_state,
        "confirmed": position is not None,
        "draft": stored,
        "order": order[-1] if order else None,
        "position": position,
        "checks": state["checks"],
        "live": state["live"],
        "margin": state["margin"],
        "worst_case_usd": state["worst_case_usd"],
        "broker_check": check,
        "broker_response": sent,
    }


def _await_position(
    rt: Runtime, symbol: str, before: set[str], timeout_s: float
) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            current = rt.positions(symbol)
        except BrokerError:
            time.sleep(0.5)
            continue
        new = [p for p in current if p["ticket"] not in before]
        if new:
            return new[0]
        time.sleep(0.5)
    return None
