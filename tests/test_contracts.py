"""Tests for API contract compliance (overview, risk, account)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.ignite.api.app import create_app


def test_overview_contract(client):
    body = client.get("/api/agent/overview").json()
    # Top-level keys from spec §9
    assert set(body) >= {
        "status",
        "account",
        "risk",
        "positions",
        "drafts",
        "decisions",
        "guardrails",
    }
    # Account shape
    assert {
        "equity",
        "profit",
        "server",
        "currency",
        "margin_free",
        "mode",
    } <= set(body["account"])
    # Risk shape
    assert {
        "open_risk_usd",
        "open_risk_pct",
        "cap_pct",
        "daily_pnl",
        "daily_loss_limit_pct",
    } <= set(body["risk"])
    # Consistency: status.daily_pnl == risk.daily_pnl
    assert body["status"]["daily_pnl"] == body["risk"]["daily_pnl"]


def test_status_uses_ledger_for_daily_pnl(client, rt):
    # Set a realised PnL
    rt.realised_override = -123.45
    body = client.get("/api/agent/status").json()
    # status.daily_pnl should come from ledger (realised + floating)
    # In the fake, floating is 0, so it should match realised
    assert body["daily_pnl"] == -123.45