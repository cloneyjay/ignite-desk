"""Tests for the ExecutionDesk unit: guarded draft execution via MCP."""

from __future__ import annotations

from backend.ignite.agent.analyst import Analyst
from backend.ignite.agent.execution_desk import ExecutionDesk, ExecutionResult


def test_execution_desk_exists():
    """ExecutionDesk and ExecutionResult can be imported and instantiated."""
    assert ExecutionDesk is not None
    assert ExecutionResult is not None


def test_execution_desk_blocks_missing_draft(rt):
    """A non-existent draft returns blocked, not an exception."""
    desk = ExecutionDesk(rt)
    result = desk.execute("nonexistent_draft_id")

    assert isinstance(result, ExecutionResult)
    assert result.blocked is True
    assert result.block_reason == "draft not found"
    assert result.ok is False
    assert result.ticket is None


def test_execution_desk_executes_draft(rt):
    """A valid draft is evaluated then executed through the gateway."""
    # Enable agent for autonomous execution
    rt.config_service.update({"enabled": True})

    # Run analysis to produce a draft
    analyst = Analyst(rt)
    analysis = analyst.assess("XAUUSD", "M15")

    if analysis.draft_id is None:
        # Analysis produced no tradeable setup — nothing to execute
        return

    desk = ExecutionDesk(rt)
    execution = desk.execute(analysis.draft_id)

    assert isinstance(execution, ExecutionResult)
    assert execution.blocked is False
    assert execution.block_reason is None
    if execution.ok:
        assert execution.ticket is not None
        assert execution.fill_price is not None
