"""Autonomy engine: manages autonomy levels and tool gating."""

from __future__ import annotations

from typing import Any

from backend.ignite.agent.tools import ToolRegistry
from backend.ignite.services.runtime import Runtime


class AutonomyEngine:
    """Manages autonomy levels and tool registration gating."""

    # Autonomy levels:
    # 0 = Observe only (no tools)
    # 1 = Prepare only (read/prepare tools)
    # 2 = Execute guarded (execute tools with full validation)
    # 3 = Adaptive (can modify risk params within bounds)
    # 4 = Fully autonomous (policy engine only)

    LEVEL_NAMES = {
        0: "observe",
        1: "prepare",
        2: "execute_guarded",
        3: "adaptive",
        4: "autonomous",
    }

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt
        self.tool_registry = rt.tool_registry

    def get_level(self) -> int:
        return self.rt.config().autonomy_level

    def get_level_name(self) -> str:
        return self.LEVEL_NAMES.get(self.get_level(), "unknown")

    def get_available_tools(self) -> list[str]:
        """Get list of available tool names for current autonomy level."""
        config = self.rt.config()
        tools = self.tool_registry.get_available(config.operating_mode, self.rt.kill_switch(), config.autonomy_level)
        if self.get_level() < 2:
            # Filter out execute tools
            return [t.name for t in tools if t.permission != "execute"]
        return [t.name for t in tools]

    def can_execute(self) -> bool:
        """Check if execution is allowed at current autonomy level."""
        return self.get_level() >= 2 and not self.rt.kill_switch()

    def set_level(self, level: int) -> bool:
        """Set autonomy level (0-4). Returns True if successful."""
        if not 0 <= level <= 4:
            return False
        if level > 2 and self.rt.config().operating_mode != "autonomous":
            return False
        if level > 0 and self.rt.config().operating_mode not in ("autonomous", "prepare"):
            return False
        self.rt.config_service.update({"autonomy_level": level})
        return True

    def get_permissions(self) -> dict[str, bool]:
        """Get permission matrix for current level."""
        level = self.get_level()
        return {
            "read": level >= 0,
            "prepare": level >= 1,
            "execute": level >= 2 and not self.rt.kill_switch(),
            "modify_risk": level >= 3,
            "modify_policy": level >= 4,
        }

    def get_status(self) -> dict[str, Any]:
        """Get full autonomy status."""
        return {
            "level": self.get_level(),
            "level_name": self.get_level_name(),
            "permissions": self.get_permissions(),
            "available_tools": self.get_available_tools(),
            "kill_switch": self.rt.kill_switch(),
            "operating_mode": self.rt.config().operating_mode,
            "execution_mode": self.rt.config().execution_mode,
        }