"""Tests for agent communication module — reasoner, explainer, learner."""

from __future__ import annotations

import pytest
import tempfile
import os
import atexit
from pathlib import Path
from unittest.mock import MagicMock

from backend.ignite.agent.communication.reasoner import Reasoner
from backend.ignite.agent.communication.explainer import Explainer
from backend.ignite.agent.communication.learner import Learner
from backend.ignite.agent.decision import Decision, Entry, Risk, Links
from backend.ignite.services.runtime import Runtime
from backend.ignite.config import Settings, MCPSettings
from backend.ignite.llm.client import LLMClient, LLMResult, ToolCall
from backend.ignite.agent.tools import ToolRegistry
from tests.fakes import FakeMCP, FakeForecast
from pathlib import Path


# Global temp directory for test database
TEST_DB_DIR = tempfile.mkdtemp()
TEST_DB_PATH = Path(TEST_DB_DIR) / "test_communication.db"

def cleanup_test_db():
    """Cleanup test database on exit."""
    try:
        if os.path.exists(TEST_DB_PATH):
            os.unlink(TEST_DB_PATH)
        os.rmdir(TEST_DB_DIR)
    except:
        pass

atexit.register(cleanup_test_db)


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
                text='{"type": "thinking", "content": "Analyzing..."}',
                provider="fake",
                model="fake",
                latency_ms=1,
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="market.intel",
                        arguments={"symbol": "XAUUSD"}
                    )
                ],
            )
        return self.responses.pop(0)


class FakeToolRegistry(ToolRegistry):
    """Fake tool registry for testing."""

    def __init__(self):
        # Don't call parent __init__ which builds real tools
        self._tools = {}

    def get_available(self, mode: str, kill_switch: bool, autonomy_level: int = 0):
        return []

    def _register(self, tool):
        self._tools[tool.name] = tool


def create_test_runtime():
    """Create a minimal test runtime with fake dependencies."""
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
    rt.seed_symbols()
    rt.config_service.update({"enabled": True, "operating_mode": "autonomous", "execution_mode": "live"})
    
    # Replace with fake LLM and tool registry
    rt.llm = FakeLLMClient()
    rt.tool_registry = FakeToolRegistry()
    return rt


def test_reasoning_stream():
    rt = create_test_runtime()
    reasoner = Reasoner(rt)
    events = list(reasoner.stream("Analyzing XAUUSD..."))
    assert len(events) > 0
    assert any(e["type"] == "thinking" for e in events)
    assert any(e["type"] == "tool" for e in events)


def test_decision_explanation():
    rt = create_test_runtime()
    explainer = Explainer(rt)
    from backend.ignite.agent.decision import Decision, Entry, Risk, Links
    decision = Decision(
        symbol="XAUUSD",
        timeframe="M15",
        action="LONG",
        conviction=0.8,
        thesis="Strong bullish setup",
        evidence=["trend up", "forecast supports long"],
        failed_conditions=[],
        entry=Entry(type="market", price=0.0),
        risk=Risk(lots=0.01, sl=3920.0, tp=3950.0),
        expected_rr=2.5,
        invalidate_if=["price below 3900"],
        links=Links(analysis_id="test_analysis", draft_id="test_draft", decision_id="test_decision"),
    )
    explanation = explainer.explain(decision)
    assert "thesis" in explanation
    assert "evidence" in explanation
    assert "counterfactuals" in explanation
    assert "entry" in explanation
    assert "risk" in explanation


def test_learner_extracts_patterns():
    rt = create_test_runtime()
    learner = Learner(rt)
    # Add some mock trade data
    rt.store.episodic_record("trade", {"symbol": "XAUUSD", "side": "buy", "pnl": 100}, symbol="XAUUSD", outcome="profit")
    rt.store.episodic_record("trade", {"symbol": "XAUUSD", "side": "sell", "pnl": -50}, symbol="XAUUSD", outcome="loss")
    
    patterns = learner.extract_patterns()
    assert len(patterns) > 0
    assert any("win_rate" in p for p in patterns)