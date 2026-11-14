from __future__ import annotations

from datetime import datetime, timezone, timedelta

from backend.ignite.market.time import Clock
from backend.ignite.services.broker import modify_position_sl_tp, positions, send_market_order


class BrokerFake:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments or {}))
        return self.payload


def test_positions_reads_mt5_protection_fields():
    fake = BrokerFake(
        {
            "positions": [
                {
                    "position_id": "42",
                    "symbol": "XAUUSD",
                    "action": "sell",
                    "volume": 0.01,
                    "price_open": 3912.35,
                    "price_last": 3910.0,
                    "stop_loss": 3925.19,
                    "take_profit": 3886.08,
                }
            ]
        }
    )

    result = positions(
        fake,
        Clock(offset=timedelta(0), utc_at_read=datetime.now(timezone.utc)),
    )

    assert result[0]["sl"] == 3925.19
    assert result[0]["tp"] == 3886.08


def test_send_accepts_mt5_done_retcode_without_legacy_ok():
    fake = BrokerFake({"retcode": 10009, "retcode_details": "Done"})

    result = send_market_order(fake, "XAUUSD", "sell", 0.01, 3925.19, 3886.08, "ignite test")

    assert result["retcode"] == 10009


def test_modify_uses_current_mcp_ticket_schema():
    fake = BrokerFake({"retcode": 10009, "retcode_details": "Done"})

    modify_position_sl_tp(fake, "XAUUSD", "42", 3925.19, 3886.08)

    assert fake.calls == [
        (
            "trade_modify_sl_tp",
            {
                "symbol": "XAUUSD",
                "position_ticket": "42",
                "sl": 3925.19,
                "tp": 3886.08,
            },
        )
    ]
