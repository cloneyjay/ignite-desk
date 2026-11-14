"""Integration test: analyze → draft → execute → fill → chat notes."""

from __future__ import annotations

from backend.ignite.agent.analyst import Analyst
from backend.ignite.agent.execution_desk import ExecutionDesk, ExecutionResult


def test_analyze_then_execute_flow(rt):
    """End-to-end: Analyst produces a draft, ExecutionDesk executes it via MCP."""
    # Enable agent for autonomous execution
    rt.config_service.update({"enabled": True})

    # Step 1: Analyst runs multi-source read → deterministic analysis → draft
    analyst = Analyst(rt)
    analysis = analyst.assess("XAUUSD", "M15")

    assert analysis.signal in {"LONG", "SHORT", "NONE"}
    assert isinstance(analysis.rationale, str) and len(analysis.rationale) > 0

    if analysis.draft_id is None:
        # No tradeable setup — nothing to execute. Still validates the analyst path.
        return

    # Step 2: ExecutionDesk validates guards and executes via MCP gateway
    desk = ExecutionDesk(rt)
    execution = desk.execute(analysis.draft_id)

    assert isinstance(execution, ExecutionResult)
    assert execution.blocked is False
    assert execution.block_reason is None

    if execution.ok:
        assert execution.ticket is not None
        assert execution.fill_price is not None

        # Verify the MCP order was actually sent
        order_calls = rt.mcp.called("trade_send_market_order")
        assert len(order_calls) >= 1, "MCP place_order was not called"

        # Verify the position appears in the broker
        positions = rt.positions("XAUUSD")
        assert any(str(p["ticket"]) == execution.ticket for p in positions)

    # Step 3: Verify pending drafts reflect execution
    draft = rt.store.get_draft(analysis.draft_id)
    assert draft is not None
    assert draft["state"] in {"filled", "executing"}
