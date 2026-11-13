"""Tests for mode promotion/demotion API."""

from __future__ import annotations

import pytest

from backend.ignite.agent.config import ExecutionMode


def test_promote_shadow_to_demo(client, rt):
    rt.config_service.update({"execution_mode": "shadow", "operating_mode": "autonomous"})
    resp = client.post("/api/mode/promote", json={"target": "demo", "confirm": True, "account_number": "12345"})
    assert resp.status_code == 200
    assert resp.json()["mode"] == "demo"
    assert rt.config().execution_mode == "demo"
    audit = rt.store.get_audit_log()[-1]
    assert audit["action"] == "mode_promoted"
    assert audit["payload"]["from"] == "shadow"
    assert audit["payload"]["to"] == "demo"


def test_promote_demo_to_live(client, rt):
    rt.config_service.update({"execution_mode": "demo", "operating_mode": "autonomous"})
    resp = client.post("/api/mode/promote", json={"target": "live", "confirm": True, "account_number": "12345"})
    assert resp.status_code == 200
    assert resp.json()["mode"] == "live"
    assert rt.config().execution_mode == "live"
    audit = rt.store.get_audit_log()[-1]
    assert audit["action"] == "mode_promoted"
    assert audit["payload"]["from"] == "demo"
    assert audit["payload"]["to"] == "live"
    assert audit["payload"]["account"] == "12345"


def test_promote_requires_confirmation(client, rt):
    resp = client.post("/api/mode/promote", json={"target": "live", "confirm": False, "account_number": "12345"})
    assert resp.status_code == 400


def test_promote_live_requires_account_number(client, rt):
    rt.config_service.update({"execution_mode": "demo", "operating_mode": "autonomous"})
    resp = client.post("/api/mode/promote", json={"target": "live", "confirm": True})
    assert resp.status_code == 400


def test_promote_skips_not_allowed(client, rt):
    """Cannot promote from shadow directly to live."""
    rt.config_service.update({"execution_mode": "shadow", "operating_mode": "autonomous"})
    resp = client.post("/api/mode/promote", json={"target": "live", "confirm": True, "account_number": "12345"})
    assert resp.status_code == 400


def test_demote_live_to_shadow(client, rt):
    rt.config_service.update({"execution_mode": "live", "operating_mode": "autonomous"})
    resp = client.post("/api/mode/demote", json={"confirm": True})
    assert resp.status_code == 200
    assert resp.json()["mode"] == "shadow"
    assert rt.config().execution_mode == "shadow"
    audit = rt.store.get_audit_log()[-1]
    assert audit["action"] == "mode_demoted"
    assert audit["payload"]["from"] == "live"
    assert audit["payload"]["to"] == "shadow"


def test_demote_requires_confirmation(client, rt):
    rt.config_service.update({"execution_mode": "live", "operating_mode": "autonomous"})
    resp = client.post("/api/mode/demote", json={"confirm": False})
    assert resp.status_code == 400


def test_promote_not_allowed_in_prepare_mode(client, rt):
    """Cannot promote when operating_mode is prepare."""
    rt.config_service.update({"execution_mode": "shadow", "operating_mode": "prepare"})
    resp = client.post("/api/mode/promote", json={"target": "demo", "confirm": True, "account_number": "12345"})
    assert resp.status_code == 400


def test_promote_invalid_target(client, rt):
    rt.config_service.update({"execution_mode": "shadow", "operating_mode": "autonomous"})
    resp = client.post("/api/mode/promote", json={"target": "invalid", "confirm": True, "account_number": "12345"})
    assert resp.status_code == 400