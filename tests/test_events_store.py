"""Agent event log and config versioning."""

from __future__ import annotations

from backend.ignite.store.db import Store


def test_append_and_read_event(tmp_path):
    store = Store(tmp_path / "t.db")
    event = store.append_agent_event(
        "order.rejected",
        severity="warning",
        symbol="XAUUSD",
        decision_id="d1",
        payload={"code": "SPREAD"},
    )
    assert event["kind"] == "order.rejected"
    assert event["payload"] == {"code": "SPREAD"}
    assert event["seq"] == 1
    rows = store.agent_events(decision_id="d1")
    assert len(rows) == 1
    assert rows[0]["symbol"] == "XAUUSD"


def test_event_seq_increments(tmp_path):
    store = Store(tmp_path / "t.db")
    store.append_agent_event("a")
    second = store.append_agent_event("b")
    assert second["seq"] == 2


def test_config_version_increments(tmp_path):
    store = Store(tmp_path / "t.db")
    assert store.read_agent_config() is None
    assert store.write_agent_config(True, '{"enabled": true}') == 1
    assert store.write_agent_config(False, '{"enabled": false}') == 2
    row = store.read_agent_config()
    assert row["version"] == 2
    assert row["enabled"] == 0
