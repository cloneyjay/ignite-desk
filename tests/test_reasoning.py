"""Tests for agent reasoning module — planner and reflector."""

from __future__ import annotations

import pytest
import tempfile
import os
import atexit
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

from backend.ignite.agent.reasoning.planner import Planner, Plan, PlanStep
from backend.ignite.agent.reasoning.reflector import Reflector, Reflection
from backend.ignite.agent.tools import ToolRegistry
from backend.ignite.llm.client import LLMClient, LLMResult, ToolCall


class FakeLLMClient(LLMClient):
    """Fake LLM client for testing."""

    def __init__(self):
        self.responses = []

    def add_response(self, text: str, tool_calls=None):
        self.responses.append(LLMResult(
            text=text,
            provider="fake",
            model="fake",
            latency_ms=1,
            tool_calls=tool_calls,
        ))

    def complete(self, messages, tools=None, tool_choice="auto", **kwargs):
        if not self.responses:
            return LLMResult(
                text='',
                provider="fake",
                model="fake",
                latency_ms=1,
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="create_plan",
                        arguments={
                            "steps": [
                                {"tool": "market.intel", "args": {"symbol": "XAUUSD"}, "expected_outcome": "market analysis", "success_criteria": "trend identified"},
                                {"tool": "risk.size", "args": {"symbol": "XAUUSD", "side": "buy"}, "expected_outcome": "position size", "success_criteria": "size within risk limits"}
                            ]
                        }
                    )
                ],
            )
        return self.responses.pop(0)


class FakeToolRegistry(ToolRegistry):
    """Fake tool registry for testing."""

    def __init__(self):
        # Don't call parent __init__ which builds real tools
        self._tools = {}

    def get_available(self, mode: str, kill_switch: bool):
        return []

    def _register(self, tool):
        self._tools[tool.name] = tool


# Global temp directory for test database
TEST_DB_DIR = tempfile.mkdtemp()
TEST_DB_PATH = Path(TEST_DB_DIR) / "test_reasoning.db"

def cleanup_test_db():
    """Cleanup test database on exit."""
    try:
        if os.path.exists(TEST_DB_PATH):
            os.unlink(TEST_DB_PATH)
        os.rmdir(TEST_DB_DIR)
    except:
        pass

atexit.register(cleanup_test_db)


def create_test_runtime():
    """Create a minimal test runtime with fake dependencies."""
    from backend.ignite.services.runtime import Runtime
    from backend.ignite.config import Settings, MCPSettings
    from tests.fakes import FakeMCP, FakeForecast
    from pathlib import Path

    settings = Settings(
        mcp=MCPSettings(url="http://fake", token="test-token"),
        db_path=TEST_DB_PATH,
        bind_host="127.0.0.1",
        bind_port=8000,
        kronos_worker_url="http://fake",
        kronos_model="fake",
        timezone="local",
    )
    rt = Runtime(
        settings,
        mcp_client=FakeMCP(),
        forecast_client=FakeForecast(),
    )
    rt.llm = FakeLLMClient()
    rt.tool_registry = FakeToolRegistry()
    return rt


import pytest

from backend.ignite.agent.reasoning.planner import Planner, Plan, PlanStep
from backend.ignite.agent.reasoning.reflector import Reflector, Reflection
from backend.ignite.agent.tools import ToolRegistry
from backend.ignite.llm.client import LLMClient, LLMResult, ToolCall


class FakeLLMClient(LLMClient):
    """Fake LLM client for testing."""

    def __init__(self):
        self.responses = []

    def add_response(self, text: str, tool_calls=None):
        self.responses.append(LLMResult(
            text=text,
            provider="fake",
            model="fake",
            latency_ms=1,
            tool_calls=tool_calls,
        ))

    def complete(self, messages, tools=None, tool_choice="auto", **kwargs):
        if not self.responses:
            return LLMResult(
                text='',
                provider="fake",
                model="fake",
                latency_ms=1,
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="create_plan",
                        arguments={
                            "steps": [
                                {"tool": "market.intel", "args": {"symbol": "XAUUSD"}, "expected_outcome": "market analysis", "success_criteria": "trend identified"},
                                {"tool": "risk.size", "args": {"symbol": "XAUUSD", "side": "buy"}, "expected_outcome": "position size", "success_criteria": "size within risk limits"}
                            ]
                        }
                    )
                ],
            )
        return self.responses.pop(0)


class FakeToolRegistry(ToolRegistry):
    """Fake tool registry for testing."""

    def __init__(self):
        # Don't call parent __init__ which builds real tools
        self._tools = {}

    def get_available(self, mode: str, kill_switch: bool):
        return []

    def _register(self, tool):
        self._tools[tool.name] = tool


def create_test_runtime():
    """Create a minimal test runtime with fake dependencies."""
    from backend.ignite.services.runtime import Runtime
    from backend.ignite.agent.tools import ToolRegistry
    from backend.ignite.config import Settings, MCPSettings
    from tests.fakes import FakeMCP, FakeForecast
    from pathlib import Path

    settings = Settings(
        mcp=MCPSettings(url="http://fake", token="test-token"),
        db_path=TEST_DB_PATH,
        bind_host="127.0.0.1",
        bind_port=8000,
        kronos_worker_url="http://fake",
        kronos_model="fake",
        timezone="local",
    )
    rt = Runtime(
        settings,
        mcp_client=FakeMCP(),
        forecast_client=FakeForecast(),
    )
    rt.llm = FakeLLMClient()
    rt.tool_registry = FakeToolRegistry()
    return rt


def test_planner_creates_multi_step_plan():
    rt = create_test_runtime()
    rt.llm.add_response(
        text='',
        tool_calls=[
            ToolCall(
                id="call_1",
                name="create_plan",
                arguments={
                    "steps": [
                        {"tool": "market.intel", "args": {"symbol": "XAUUSD"}, "expected_outcome": "market analysis", "success_criteria": "trend identified"},
                        {"tool": "risk.size", "args": {"symbol": "XAUUSD", "side": "buy"}, "expected_outcome": "position size", "success_criteria": "size within risk limits"}
                    ]
                }
            )
        ]
    )
    planner = Planner(rt)
    plan = planner.create_plan("Analyze XAUUSD and execute if bullish")
    assert len(plan.steps) >= 2
    assert all(hasattr(s, 'tool') and hasattr(s, 'expected_outcome') for s in plan.steps)


def test_planner_validates_steps():
    rt = create_test_runtime()
    planner = Planner(rt)
    with pytest.raises(ValueError, match="empty"):
        planner.create_plan("")


def test_reflector_records_insight():
    rt = create_test_runtime()
    reflector = Reflector(rt)
    reflection = reflector.reflect("decision_123", "trade_executed", {"pnl": 150, "lesson": "should have scaled earlier"})
    assert reflection["decision_id"] == "decision_123"
    assert "general_lesson" in reflection["insights"]
    assert reflection["insights"]["general_lesson"] == "should have scaled earlier"