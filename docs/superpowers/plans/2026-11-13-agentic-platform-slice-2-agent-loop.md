# Agent Loop — Slice 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the autonomous agent loop with LLM tool calling, bounded steps, structured decision schema, and a typed tool registry. The agent observes market state, reasons with tools, and produces a validated decision — all under execution budgets.

**Architecture:** The agent loop runs as a scheduled job (already created in Slice 1 Task 6). Each cycle: fetch context → LLM tool loop (max 8 steps, 90s, 16 tool calls) → structured decision → gateway validation → order or NO_TRADE. Tools are registered per-cycle based on mode/kill-switch. Decisions are recorded as `agent_events` and `agent_decisions`.

**Tech Stack:** Python 3.11, FastAPI, Pydantic for schemas, `apscheduler` for scheduling, existing `LLMClient` extended with tool calling.

**Spec:** `docs/superpowers/specs/2026-11-13-agentic-trading-platform-design.md` (sections 5.3–5.5, 7)

## Global Constraints

- Single process: API + scheduler share one `Runtime` (Slice 1 Task 6).
- All broker writes go through `AgentExecutionGateway` (Slice 1 Task 4).
- Every tool call persists to `agent_events` with `decision_id` (Slice 1 Task 1).
- Config from `ConfigService` only; ceilings enforced (Slice 1 Task 2).
- PnL & guards from `Ledger`; fail-closed (Slice 1 Task 3).
- Kill switch blocks entries & risk-increasing modifications only (spec §6.2).
- Defaults: `operating_mode="prepare"`, `execution_mode="shadow"`, risk 2%/trade, 6% daily, max 10 concurrent, 2/symbol, 15% portfolio cap.
- Rollout modes: `shadow` → `demo` → `live`, promotion explicit.

## Review Focus

1. **Malformed tool args from LLM** → agent must return a typed error to the model, not silently retry with different data (spec §5.3).
2. **Budget exhaustion mid-loop** → decision must be `NO_TRADE` with reason `budget_exhausted`, never default to a trade (spec §5.3).
3. **Execution tools registered only in autonomous + kill-switch-off** → mode change takes effect immediately per cycle (spec §5.5).
4. **Decision schema validation failure** → recorded as `INVALID`, no order sent, narration stored (spec §5.4).
5. **Provider without native tool calling** → JSON fallback envelope works identically (spec §5.3).

---

### Task 1: Tool schemas and registry

**Files:**
- Create: `backend/ignite/agent/tools.py`
- Modify: `backend/ignite/agent/registry.py` (if exists, else create)
- Test: `tests/test_agent_tools.py`

**Interfaces:**
- Produces: `ToolSpec(name, permission, description, input_schema, output_schema, timeout_s, handler)`; `ToolRegistry.get_available(mode, kill_switch) -> list[ToolSpec]`

- [ ] **Step 1: Write failing tests**

```python
def test_tool_registry_filters_by_permission():
    registry = ToolRegistry()
    read_tools = registry.get_available(mode="prepare", kill_switch=False)
    exec_tools = registry.get_available(mode="autonomous", kill_switch=False)
    # In prepare mode, no execute tools
    assert all(t.permission != "execute" for t in read_tools)
    # In autonomous + kill_switch=False, execute tools present
    assert any(t.permission == "execute" for t in exec_tools)
    # Kill switch on removes execute tools
    exec_killed = registry.get_available(mode="autonomous", kill_switch=True)
    assert all(t.permission != "execute" for t in exec_killed)

def test_tool_spec_has_required_fields():
    spec = ToolSpec(name="account.snapshot", permission="read", description="...",
                    input_schema={}, output_schema={}, timeout_s=10, handler=lambda rt, args: {})
    assert spec.name == "account.snapshot"
    assert spec.permission == "read"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_tools.py -q`
Expected: FAIL — module not found

- [ ] **Step 3: Implement `ToolSpec` dataclass and `ToolRegistry` in `backend/ignite/agent/tools.py`**

Define all 21 tools from spec §5.5 table with JSON schemas (use `pydantic.TypeAdapter` for validation). Permissions: `read`/`prepare`/`execute`. Handler signature: `Callable[[Runtime, dict], Awaitable[dict]]` (sync handlers wrapped). `ToolRegistry.__init__` builds all tools; `get_available(mode, kill_switch)` filters by permission + kill switch.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_tools.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/ignite/agent/tools.py tests/test_agent_tools.py
git commit -m "feat(agent): tool registry with permission scopes"
```

---

### Task 2: LLM tool calling path

**Files:**
- Modify: `backend/ignite/llm/client.py`
- Test: `tests/test_llm_tools.py`

**Interfaces:**
- Consumes: `LLMClient.complete(messages, tools=None, tool_choice="auto", ...)` from Task 1
- Produces: `LLMResult` with optional `tool_calls: list[ToolCall]`; `LLMClient` raises `ToolCallError` on malformed args

- [ ] **Step 1: Write failing tests**

```python
def test_native_tool_calls_returned():
    client = FakeLLMClient()
    resp = client.complete(messages=[{"role": "user", "content": "test"}],
                           tools=[{"type": "function", "function": {"name": "account.snapshot"}}])
    assert resp.tool_calls is not None
    assert len(resp.tool_calls) >= 1
    assert resp.tool_calls[0].name == "account.snapshot"

def test_malformed_args_raises_toolcallerror():
    client = FakeLLMClient()
    # Simulate provider returning invalid JSON in arguments
    with pytest.raises(ToolCallError, match="invalid arguments"):
        client.complete(...)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_llm_tools.py -q`
Expected: FAIL — `ToolCallError` not defined, `tool_calls` not returned

- [ ] **Step 3: Implement tool calling in `backend/ignite/llm/client.py`**

Add `ToolCall` dataclass (`id`, `name`, `arguments: dict`). Extend `LLMResult` with `tool_calls: list[ToolCall] | None`. In `complete()`, when `tools` provided:
1. If provider supports native `tools` (NIM, some local), send `tools` + `tool_choice`, parse `tool_calls` from response.
2. Else (fallback), inject tool schemas into system prompt, request JSON envelope `{"tool": "name", "arguments": {...}}`, parse and validate.
3. Validate arguments against tool's input schema (from `ToolRegistry`). On failure, raise `ToolCallError(tool, reason, raw_args)` — caught by orchestrator and returned to model.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_llm_tools.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/ignite/llm/client.py tests/test_llm_tools.py
git commit -m "feat(llm): native tool calling + JSON fallback"
```

---

### Task 3: Structured decision schema

**Files:**
- Create: `backend/ignite/agent/decision.py`
- Test: `tests/test_decision_schema.py`

**Interfaces:**
- Produces: `Decision` Pydantic model matching spec §5.4; `DecisionError` for validation failures

- [ ] **Step 1: Write failing tests**

```python
def test_valid_long_decision_passes():
    d = Decision(symbol="XAUUSD", timeframe="M15", action="LONG", conviction=0.82,
                 thesis="...", evidence=["..."], failed_conditions=[],
                 entry={"type": "market", "price": 0.0},
                 risk={"lots": 0.02, "sl": 3920.0, "tp": 3950.0},
                 expected_rr=2.5, invalidate_if=["..."], links={...})
    assert d.action == "LONG"

def test_invalid_action_rejected():
    with pytest.raises(ValidationError):
        Decision(..., action="BUY", ...)  # not in enum

def test_missing_required_field_rejected():
    with pytest.raises(ValidationError):
        Decision(symbol="XAUUSD", timeframe="M15")  # missing action, etc.
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_decision_schema.py -q`
Expected: FAIL — `Decision` not defined

- [ ] **Step 3: Implement `Decision` model in `backend/ignite/agent/decision.py`**

Pydantic model with exact fields from spec §5.4. `action` enum: `LONG`, `SHORT`, `NO_TRADE`, `WAIT`, `MONITOR`, `CLOSE`, `MODIFY`. `entry.type` enum: `market`, `limit`. Nested models for `entry`, `risk`, `links`. `ConfigDict(extra="forbid")`. Export `parse_decision(json_str) -> Decision | DecisionError`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_decision_schema.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/ignite/agent/decision.py tests/test_decision_schema.py
git commit -m "feat(agent): structured decision schema"
```

---

### Task 4: Agent orchestrator (bounded loop)

**Files:**
- Create: `backend/ignite/agent/orchestrator.py`
- Modify: `backend/ignite/agent/engine.py` (integrate orchestrator into `run_cycle`)
- Test: `tests/test_agent_orchestrator.py`

**Interfaces:**
- Consumes: `Runtime`, `ToolRegistry`, `LLMClient`, `Decision` parser, `AgentExecutionGateway`, `Ledger`
- Produces: `Orchestrator.run_cycle(symbol, timeframe) -> Decision`; records `agent_events` per tool call

- [ ] **Step 1: Write failing tests**

```python
def test_orchestrator_respects_max_steps():
    rt = FakeRuntime()
    orch = Orchestrator(rt, max_steps=2)
    # Provide a fake LLM that always wants to call tools
    decision = orch.run_cycle("XAUUSD", "M15")
    assert decision.action == "NO_TRADE"
    assert "budget_exhausted" in (decision.failed_conditions or [])

def test_orchestrator_records_tool_calls():
    rt = FakeRuntime()
    orch = Orchestrator(rt, max_steps=3)
    decision = orch.run_cycle("XAUUSD", "M15")
    events = rt.store.agent_events(decision_id=decision.links.decision_id)
    tool_events = [e for e in events if e["kind"] == "tool.call"]
    assert len(tool_events) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_orchestrator.py -q`
Expected: FAIL — `Orchestrator` not defined

- [ ] **Step 3: Implement `Orchestrator` in `backend/ignite/agent/orchestrator.py`**

```python
class Orchestrator:
    def __init__(self, rt: Runtime, max_steps: int = 8, max_tool_calls: int = 16, deadline_s: float = 90.0):
        ...

    def run_cycle(self, symbol: str, timeframe: str) -> Decision:
        decision_id = uuid.uuid4().hex
        tools = rt.tool_registry.get_available(rt.config().operating_mode, rt.kill_switch())
        messages = self._build_context_pack(rt, symbol, timeframe, decision_id)
        tool_call_count = 0
        start = time.monotonic()

        for step in range(max_steps):
            if time.monotonic() - start > deadline_s or tool_call_count >= max_tool_calls:
                return self._budget_exhausted(decision_id, symbol, timeframe)
            resp = rt.llm.complete(messages, tools=[t.to_openai() for t in tools])
            if resp.tool_calls:
                for tc in resp.tool_calls:
                    tool_call_count += 1
                    result = self._execute_tool(rt, tc, decision_id)
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)})
                continue
            # No tool calls -> model produced final decision
            decision = parse_decision(resp.text)
            if isinstance(decision, DecisionError):
                messages.append({"role": "user", "content": f"Decision invalid: {decision}. Try again."})
                continue
            decision.links.decision_id = decision_id
            rt.store.append_agent_event("decision.final", ..., decision_id=decision_id, payload=decision.model_dump())
            return decision
        return self._budget_exhausted(decision_id, symbol, timeframe)
```

`_execute_tool` dispatches to tool handler, records `agent_events` with `decision_id`, returns result dict. `_build_context_pack` fetches: account snapshot, positions, quote, bars, spec, structure, calendar, news, forecast (if needed), analysis draft.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_orchestrator.py -q`
Expected: PASS

- [ ] **Step 5: Integrate into `AgentEngine.run_cycle`**

Modify `backend/ignite/agent/engine.py`: in `run_cycle`, for each watched symbol/timeframe, call `Orchestrator(rt).run_cycle(symbol, tf)`. Persist decision to `agent_decisions` table. If `action in {"LONG", "SHORT"}`, call `rt.gateway.place(...)` (already validated by gateway).

- [ ] **Step 6: Commit**

```bash
git add backend/ignite/agent/orchestrator.py backend/ignite/agent/engine.py tests/test_agent_orchestrator.py
git commit -m "feat(agent): bounded orchestrator loop with tool calling"
```

---

### Task 5: Agent cycle integration tests

**Files:**
- Create: `tests/test_agent_cycle.py`
- Uses: fixtures from `tests/conftest.py` (Runtime, FakeMCP, FakeForecast)

**Interfaces:**
- End-to-end: scheduled cycle → orchestrator → decision → gateway → order (or rejection)

- [ ] **Step 1: Write failing tests**

```python
def test_full_cycle_produces_decision(client, rt):
    rt.config_service.update({"operating_mode": "autonomous", "execution_mode": "shadow"})
    # Fake LLM that returns a valid LONG decision on first turn
    rt.llm = FakeLLMWithDecision(Decision(action="LONG", ...))
    rt.mcp.positions.append(...)  # seed market data
    # Trigger cycle manually
    from backend.ignite.agent.engine import AgentEngine
    engine = AgentEngine(rt, rt.config())
    engine.run_cycle()
    decisions = rt.store.agent_decisions(limit=10)
    assert len(decisions) == 1
    assert decisions[0]["action"] == "LONG"

def test_cycle_in_shadow_mode_does_not_send_order(client, rt):
    rt.config_service.update({"operating_mode": "autonomous", "execution_mode": "shadow"})
    rt.llm = FakeLLMWithDecision(Decision(action="LONG", ...))
    engine = AgentEngine(rt, rt.config())
    engine.run_cycle()
    # Gateway should validate but not send (shadow mode)
    assert rt.mcp.called("trade_send_market_order") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_cycle.py -q`
Expected: FAIL — orchestrator not integrated, fake LLM not implemented

- [ ] **Step 3: Implement test fakes and verify integration**

Create `FakeLLMWithDecision` in test file. Ensure `AgentEngine.run_cycle` calls orchestrator per symbol. Verify `agent_decisions` table populated, `agent_events` recorded per tool call.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_cycle.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_agent_cycle.py
git commit -m "test(agent): end-to-end cycle integration"
```

---

### Task 6: Slice 2 verification

- [ ] **Step 1: Run full backend suite**

Run: `pytest tests -q`
Expected: all pass (Slice 1 105 + new Slice 2 tests)

- [ ] **Step 2: Run frontend checks**

Run: `npm run typecheck && npm run build` in `frontend/`
Expected: both pass (no frontend changes required for Slice 2)

- [ ] **Step 3: Update spec status**

Change design spec header to include `Implemented: slice 2 (agent loop)`

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-11-13-agentic-trading-platform-design.md
git commit -m "docs: mark slice 2 (agent loop) implemented"
```