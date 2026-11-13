"""Tests for pagination, draft expiry, and health snapshot."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.ignite.api.app import create_app


def test_messages_return_newest_window(tmp_path):
    from backend.ignite.store.db import Store

    store = Store(tmp_path / "t.db")
    store.create_agent_session("s", "chat")
    for i in range(250):
        store.add_agent_message({
            "id": f"m{i:03d}",
            "session_id": "s",
            "created_at": f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}+00:00",
            "role": "user",
            "content": f"m{i}",
            "status": "ok",
        })
    rows = store.agent_messages("s", limit=200)
    assert rows[-1]["content"] == "m249"
    assert rows[0]["content"] == "m50"


def test_expire_drafts_removes_stale(tmp_path):
    from backend.ignite.store.db import Store, utc_now

    store = Store(tmp_path / "t.db")
    store._conn.execute(
        """INSERT INTO analyses (id, created_at, symbol, timeframe, last_bar_time,
        lookback, horizon, samples, model_id, infer_s, atr, p_up, edge, edge_atr,
        dispersion, signal, signal_version, risk_version, features_json, reasons_json)
        VALUES ('a','2026-01-01T00:00:00+00:00','XAUUSD','M15','t',1,1,1,'m',0.1,
        2.5,0.6,1.0,0.5,0.1,'LONG','v1','v1','{}','[]')"""
    )
    store.insert_draft({
        "id": "d1", "analysis_id": "a", "created_at": "2026-01-01T00:00:00+00:00",
        "expires_at": "2026-01-01T00:00:01+00:00", "state": "draft",
        "side": "long", "lots": 0.01, "reference_price": 3930.0,
        "sl": 3920.0, "tp": 3950.0, "risk_usd": 10.0, "risk_pct": 0.01,
        "rr": 2.0, "margin": None, "worst_case_usd": None,
        "blocked": 0, "block_reason": None, "idempotency_key": "k1",
    })
    store._conn.commit()
    assert store.expire_stale_drafts(utc_now()) == 1
    assert store.pending_drafts() == []


def test_health_uses_snapshot(client):
    assert client.get("/api/health").status_code == 200