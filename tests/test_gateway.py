"""Execution gateway: idempotency, validation, ticket binding, protection."""

from __future__ import annotations

import threading

from backend.ignite.services.gateway import OrderRequest


def gw(rt):
    return rt.gateway


def test_duplicate_decision_is_rejected(rt):
    gateway = gw(rt)
    req = OrderRequest("XAUUSD", "buy", 0.01, 3920.0, 3950.0, "d1")
    first = gateway.place(req)
    second = gateway.place(req)
    assert first.ok is True
    assert second.ok is False and second.code == "DUPLICATE"
    assert len(rt.mcp.called("trade_send_market_order")) == 1


def test_lot_step_is_rejected_not_rounded(rt):
    result = gw(rt).validate(
        OrderRequest("XAUUSD", "buy", 0.015, 3920.0, 3950.0, "d2")
    )
    assert result.ok is False and result.code == "LOTS"


def test_unprotected_fill_is_closed_and_marked(rt):
    rt.mcp.drop_sl_tp = True
    result = gw(rt).place(
        OrderRequest("XAUUSD", "buy", 0.01, 3920.0, 3950.0, "d3")
    )
    assert result.ok is False
    assert result.code == "PROTECTION_FAILED"
    assert result.unprotected is True
    assert rt.mcp.called("trade_close_single_position")


def test_second_position_on_symbol_is_rejected(rt):
    for ticket in ("1", "2"):
        rt.mcp.positions.append(
            {
                "position_id": ticket,
                "symbol": "XAUUSD",
                "action": "buy",
                "volume": 0.01,
                "price_open": 3930.0,
                "price_last": 3930.0,
                "sl": 3920.0,
                "tp": 3950.0,
                "comment": "ignite agent",
                "create_time": "2026-01-01T00:00:00",
                "update_time": "2026-01-01T00:00:00",
            }
        )
    result = gw(rt).validate(
        OrderRequest("XAUUSD", "buy", 0.01, 3920.0, 3950.0, "d4")
    )
    assert result.code == "MAX_PER_SYMBOL"


def test_daily_loss_blocks_entry(rt):
    rt.realised_override = -700.0
    result = gw(rt).validate(
        OrderRequest("XAUUSD", "buy", 0.01, 3920.0, 3950.0, "d5")
    )
    assert result.code == "DAILY_LOSS"


def test_requires_autonomous_mode(rt):
    rt.config_service.update({"operating_mode": "prepare"})
    result = gw(rt).validate(
        OrderRequest("XAUUSD", "buy", 0.01, 3920.0, 3950.0, "d6")
    )
    assert result.code == "MODE"


def test_concurrent_orders_on_one_symbol_only_one_fills(rt):
    rt.config_service.update(
        {"operating_mode": "autonomous", "max_positions_per_symbol": 1}
    )
    results = []

    def submit(i):
        results.append(
            rt.gateway.place(
                OrderRequest("XAUUSD", "buy", 0.01, 3920.0, 3950.0, f"c{i}")
            )
        )

    threads = [threading.Thread(target=submit, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sum(1 for r in results if r.ok) == 1
    assert sum(1 for r in results if r.code == "MAX_PER_SYMBOL") == 1
