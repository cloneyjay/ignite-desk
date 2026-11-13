"""Single config owner: persistence, validation, ceilings, hot reload."""

from __future__ import annotations

import pytest

from backend.ignite.agent.config import AgentConfig, ConfigError
from backend.ignite.services.config_service import ConfigService
from backend.ignite.store.db import Store


def test_seeds_from_env_once(tmp_path):
    store = Store(tmp_path / "t.db")
    svc = ConfigService(store, AgentConfig())
    assert svc.get().operating_mode == "prepare"
    # A second service must read the persisted row, not re-seed.
    svc2 = ConfigService(store, AgentConfig(operating_mode="observe"))
    assert svc2.get().operating_mode == "prepare"


def test_update_is_immutable_and_persisted(tmp_path):
    svc = ConfigService(Store(tmp_path / "t.db"), AgentConfig())
    before = svc.get()
    after = svc.update({"risk_pct": 0.025})
    assert before.risk_pct == 0.02
    assert after.risk_pct == 0.025
    assert svc.get().risk_pct == 0.025


def test_ceiling_rejects(tmp_path):
    svc = ConfigService(Store(tmp_path / "t.db"), AgentConfig())
    with pytest.raises(ConfigError, match="risk_pct"):
        svc.update({"risk_pct": 0.5})


def test_unknown_field_rejected(tmp_path):
    svc = ConfigService(Store(tmp_path / "t.db"), AgentConfig())
    with pytest.raises(ConfigError):
        svc.update({"not_a_field": 1})


def test_risk_config_carries_aggressive_envelope(tmp_path):
    svc = ConfigService(Store(tmp_path / "t.db"), AgentConfig())
    risk = svc.get().to_risk_config(max_drift_atr=0.3)
    assert risk.risk_pct == 0.02
    assert risk.max_risk_pct == 0.02
    assert risk.risk_pct <= risk.max_risk_pct


def test_version_bumps_and_toggle_persists(tmp_path):
    svc = ConfigService(Store(tmp_path / "t.db"), AgentConfig())
    v1 = svc.version()
    svc.set_enabled(True)
    assert svc.version() == v1 + 1
    assert svc.get().enabled is True


def test_second_service_sees_write(tmp_path):
    store = Store(tmp_path / "t.db")
    a = ConfigService(store, AgentConfig())
    b = ConfigService(store, AgentConfig())
    a.update({"daily_loss_limit_pct": 0.08})
    assert b.get().daily_loss_limit_pct == 0.08
