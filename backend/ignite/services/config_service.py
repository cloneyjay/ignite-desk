"""The single owner of agent configuration.

Reads and writes the ``agent_config`` row, validates patches, enforces the
absolute ceilings, and publishes ``config.changed`` so every component in the
process can drop a cached copy. There is no second source of truth.
"""

from __future__ import annotations

import json
import threading
from dataclasses import replace
from typing import Any

from backend.ignite.agent.config import (
    AgentConfig,
    ConfigError,
    check_ceilings,
    validate_patch,
)
from backend.ignite.services.events import EventBus
from backend.ignite.store.db import Store


class ConfigService:
    def __init__(
        self, store: Store, seed: AgentConfig, events: EventBus | None = None
    ) -> None:
        self._store = store
        self._events = events
        self._lock = threading.Lock()
        self._cached: AgentConfig | None = None
        self._cached_version = 0
        self._seed = seed
        if store.read_agent_config() is None:
            self._write(seed)

    # ------------------------------------------------------------------ reads

    def get(self) -> AgentConfig:
        with self._lock:
            row = self._store.read_agent_config()
            if row is None:
                self._write(self._seed)
                return self._seed
            version = int(row.get("version") or 1)
            if self._cached is None or version != self._cached_version:
                try:
                    self._cached = AgentConfig.from_dict(
                        json.loads(row["config_json"])
                    )
                except Exception as exc:  # noqa: BLE001 - corrupted row must not brick the desk
                    raise ConfigError(f"stored config is unreadable: {exc}") from exc
                self._cached_version = version
            return self._cached

    def version(self) -> int:
        self.get()
        return self._cached_version

    # ----------------------------------------------------------------- writes

    def update(self, patch: dict[str, Any]) -> AgentConfig:
        clean = validate_patch(patch)
        check_ceilings(clean)
        current = self.get()
        merged = replace(current, **clean)
        check_ceilings(merged.as_dict())
        # Audit config change
        self._store.audit(
            "config",
            "config.updated",
            {
                "patch": clean,
                "from": current.as_dict(),
                "to": merged.as_dict(),
            },
            "ok",
        )
        self._write(merged)
        return merged

    def set_enabled(self, enabled: bool) -> AgentConfig:
        return self.update({"enabled": enabled})

    def set_operating_mode(self, mode: str) -> AgentConfig:
        return self.update({"operating_mode": mode})

    def set_execution_mode(self, mode: str) -> AgentConfig:
        return self.update({"execution_mode": mode})

    # --------------------------------------------------------------- internal

    def _write(self, config: AgentConfig) -> None:
        version = self._store.write_agent_config(
            config.enabled, json.dumps(config.as_dict())
        )
        self._cached = config
        self._cached_version = version
        if self._events is not None:
            self._events.publish("config.changed", {"version": version})
