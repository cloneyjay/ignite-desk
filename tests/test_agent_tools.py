"""Tests for agent tool registry."""

from __future__ import annotations

import pytest

from backend.ignite.agent.tools import ToolRegistry, ToolSpec


def test_tool_registry_filters_by_permission():
    registry = ToolRegistry()
    read_tools = registry.get_available(mode="prepare", kill_switch=False, autonomy_level=0)
    exec_tools = registry.get_available(mode="autonomous", kill_switch=False, autonomy_level=2)
    # In prepare mode, no execute tools
    assert all(t.permission != "execute" for t in read_tools)
    # In autonomous + kill_switch=False + level 2, execute tools present
    assert any(t.permission == "execute" for t in exec_tools)
    # Kill switch on removes execute tools
    exec_killed = registry.get_available(mode="autonomous", kill_switch=True, autonomy_level=2)
    assert all(t.permission != "execute" for t in exec_killed)


def test_tool_spec_has_required_fields():
    spec = ToolSpec(
        name="account.snapshot",
        permission="read",
        description="...",
        input_schema={},
        output_schema={},
        timeout_s=10,
        handler=lambda rt, args: {},
    )
    assert spec.name == "account.snapshot"
    assert spec.permission == "read"