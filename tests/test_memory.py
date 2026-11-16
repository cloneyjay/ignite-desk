"""Tests for agent memory system — scratchpad, episodic, semantic, procedural."""

from __future__ import annotations

import pytest
import tempfile
import os
import atexit
from pathlib import Path

from backend.ignite.agent.memory.scratchpad import Scratchpad
from backend.ignite.agent.memory.episodic import EpisodicMemory
from backend.ignite.agent.memory.semantic import SemanticMemory
from backend.ignite.agent.memory.procedural import ProceduralMemory
from backend.ignite.agent.memory import MemoryStore
from backend.ignite.agent.tools import ToolRegistry
from backend.ignite.services.runtime import Runtime
from backend.ignite.config import Settings, MCPSettings
from tests.fakes import FakeMCP, FakeForecast
from pathlib import Path


# Global temp directory for test database
TEST_DB_DIR = tempfile.mkdtemp()
TEST_DB_PATH = Path(TEST_DB_DIR) / "test_memory.db"

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
    rt.tool_registry = ToolRegistry()
    return rt


def test_scratchpad_read_write():
    rt = create_test_runtime()
    pad = Scratchpad(rt)
    pad.write("analysis", {"symbol": "XAUUSD", "bias": "bullish"})
    assert pad.read("analysis")["bias"] == "bullish"


def test_scratchpad_ttl_expiry():
    rt = create_test_runtime()
    pad = Scratchpad(rt, default_ttl=1)
    pad.write("temp", {"value": 123})
    assert pad.read("temp")["value"] == 123
    import time
    time.sleep(1.5)
    assert pad.read("temp") is None


def test_episodic_query_by_symbol():
    rt = create_test_runtime()
    ep = EpisodicMemory(rt)
    ep.record("trade", {"side": "long", "pnl": 200}, symbol="XAUUSD")
    ep.record("trade", {"side": "short", "pnl": -50}, symbol="EURUSD")
    trades = ep.query(symbol="XAUUSD")
    assert len(trades) == 1
    assert trades[0]["pnl"] == 200


def test_episodic_query_by_timeframe():
    rt = create_test_runtime()
    ep = EpisodicMemory(rt)
    ep.record("analysis", {"signal": "long"}, symbol="XAUUSD", timeframe="M15")
    ep.record("analysis", {"signal": "short"}, symbol="XAUUSD", timeframe="H1")
    analyses = ep.query(symbol="XAUUSD", timeframe="M15")
    assert len(analyses) == 1
    assert analyses[0]["signal"] == "long"


def test_semantic_remember_recall():
    rt = create_test_runtime()
    sm = SemanticMemory(rt)
    sm.remember("xauusd_nfp_pattern", {"pattern": "reverses at 14:00 UTC"}, tags=["XAUUSD", "NFP"])
    results = sm.recall("xauusd")
    assert len(results) == 1
    assert results[0]["value"]["pattern"] == "reverses at 14:00 UTC"


def test_semantic_tag_search():
    rt = create_test_runtime()
    sm = SemanticMemory(rt)
    sm.remember("pattern_1", {"pattern": "bullish engulfing"}, tags=["XAUUSD", "candlestick"])
    sm.remember("pattern_2", {"pattern": "bearish engulfing"}, tags=["XAUUSD", "candlestick"])
    sm.remember("pattern_3", {"pattern": "doji"}, tags=["EURUSD", "candlestick"])
    
    results = sm.recall("", tags=["XAUUSD", "candlestick"])
    # Should match pattern_1 and pattern_2 (both have XAUUSD and candlestick tags)
    # But may also match other entries in the database from other tests
    xauusd_candlestick = [r for r in results if "XAUUSD" in r.get("tags", []) and "candlestick" in r.get("tags", [])]
    assert len(xauusd_candlestick) >= 2


def test_procedural_learn_heuristic():
    rt = create_test_runtime()
    pm = ProceduralMemory(rt)
    pm.learn("spread_widening", "reduce_size_by_50", {"condition": "spread > 20pts"})
    heuristic = pm.recall("spread_widening")
    assert heuristic["action"] == "reduce_size_by_50"


def test_procedural_confidence_scoring():
    rt = create_test_runtime()
    pm = ProceduralMemory(rt)
    pm.learn("high_spread_reduce", "reduce_size", {"condition": "spread > 30pts"}, confidence=0.9)
    pm.learn("high_spread_close", "close_position", {"condition": "spread > 50pts"}, confidence=0.7)
    
    heuristic = pm.recall("high_spread_reduce")
    assert heuristic["action"] == "reduce_size"
    assert heuristic["confidence"] == 0.9


def test_memory_capped_index_eviction():
    rt = create_test_runtime()
    # Clean slate
    rt.store._conn.execute("DELETE FROM agent_memory")
    rt.store._conn.commit()
    store = MemoryStore(rt.store, max_entries=200)
    for i in range(201):
        pid = store.propose_memory(f"key{i}", {"value": i})
        store.commit_memory(pid)
    entries = store.list_memory(limit=500)
    assert len(entries) == 200
    keys = {e["key"] for e in entries}
    # first entry should be evicted (LRU by access_count then created_at)
    assert "key0" not in keys


def test_memory_two_step_save_commit():
    rt = create_test_runtime()
    rt.store._conn.execute("DELETE FROM agent_memory")
    rt.store._conn.commit()
    store = MemoryStore(rt.store)
    pid = store.propose_memory("commit_key", {"a": 1})
    assert store.get_memory("commit_key") is None
    mem_id = store.commit_memory(pid)
    assert mem_id is not None
    content = store.get_memory("commit_key")
    assert content == {"a": 1}


def test_memory_two_step_reject():
    rt = create_test_runtime()
    rt.store._conn.execute("DELETE FROM agent_memory")
    rt.store._conn.commit()
    store = MemoryStore(rt.store)
    pid = store.propose_memory("reject_key", {"a": 2})
    rejected = store.reject_memory(pid)
    assert rejected is True
    assert store.get_memory("reject_key") is None
    # committing after reject should return None
    assert store.commit_memory(pid) is None


def test_memory_get_increments_access_count():
    rt = create_test_runtime()
    rt.store._conn.execute("DELETE FROM agent_memory")
    rt.store._conn.commit()
    store = MemoryStore(rt.store)
    pid = store.propose_memory("access_key", {"x": 1})
    store.commit_memory(pid)
    # initial access count should be 0
    row = rt.store.get_memory_by_key("access_key")
    assert row["access_count"] == 0
    store.get_memory("access_key")
    row = rt.store.get_memory_by_key("access_key")
    assert row["access_count"] == 1
    store.get_memory("access_key")
    row = rt.store.get_memory_by_key("access_key")
    assert row["access_count"] == 2
