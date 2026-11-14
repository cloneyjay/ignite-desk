# Execution & Supervision — Slice 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the execution and supervision layer: guard chain hardening, ticket binding & protection assertion, spec-driven trailing stops with ATR-based logic, scaling in/out, and broker reconciliation (orphan detection, PnL/R reconciliation, unknown order handling).

**Architecture:** The PositionManager (already exists) runs as a scheduled job every 60s. This slice hardens its guard chain, implements spec-driven trailing (ATR-based with volatility regime awareness), adds scale-in/out with proper partial close via broker, and builds a reconciliation service that runs on every cycle to detect orphans, reconcile PnL/R from broker deal history, and handle unknown orders.

**Tech Stack:** Python 3.11, FastAPI, APScheduler, existing PositionManager, Ledger, Gateway, Broker MCP.

**Spec:** `docs/superpowers/specs/2026-11-13-agentic-trading-platform-design.md` (sections 6, 7, 8.2, 8.3, 12, 15.3)

## Global Constraints

- Single process: API + scheduler share one `Runtime` (Slice 1 Task 6).
- All broker writes go through `AgentExecutionGateway` (Slice 1 Task 4).
- Every tool call persists to `agent_events` with `decision_id` (Slice 1 Task 1).
- Config from `ConfigService` only; ceilings enforced (Slice 1 Task 2).
- PnL & guards from `Ledger`; fail-closed (Slice 1 Task 3).
- Kill switch blocks entries & risk-increasing modifications only (spec §6.2).
- `agent_positions` table has new columns: `status`, `decision_id`, `entry_deal`, `position_ticket`, `initial_risk_usd`, `initial_sl`, `mfe`, `mae`, `last_synced_at`, `broker_snapshot_json` (Slice 1 Task 1).
- Rollout modes: `shadow` → `demo` → `live`, promotion explicit (spec §13).

## Review Focus

1. **Trailing SL never tightens** → only moves in favorable direction, respects `stops_level`, updates `agent_positions.trail_sl` and `last_managed_at`.
2. **Scale-out uses broker partial close** → `execution.scale` tool handles partial volume; gateway validates partial size against `volume_min`/`volume_step`.
3. **Reconciliation is fail-closed** → broker PnL unavailable → mark position `orphaned`, alert, do not assume zero.
4. **Orphan detection** → position in store but not broker → adopt if broker has it, close locally if not, reconcile PnL from deal history.
5. **Unknown order handling** → gateway returns `UNRESOLVED` when ticket missing; reconciliation retries once, then marks `orphaned`.

---

### Task 1: Harden guard chain in gateway

**Files:**
- Modify: `backend/ignite/services/gateway.py`
- Test: `tests/test_guard_chain.py`

**Interfaces:**
- Consumes: `Runtime`, `Ledger`, `ConfigService`, `AgentExecutionGateway`
- Produces: Hardened `validate()` that checks all guards before send; `SHADOW_MODE` rejection

- [ ] **Step 1: Write failing tests**

```python
def test_guard_chain_order(rt):
    """Guards evaluated in correct order: kill_switch -> mode -> watchlist -> spec -> spread -> news -> daily_loss -> exposure -> margin -> lots -> stops."""
    rt.config_service.update({"operating_mode": "autonomous", "execution_mode": "live"})
    rt.realised_override = -700.0  # Triggers daily loss
    req = OrderRequest("XAUUSD", "buy", 0.01, 3920.0, 3950.0, "d1")
    result = rt.gateway.validate(req)
    # Daily loss should be checked AFTER spread/news but BEFORE exposure/margin
    assert result.code == "DAILY_LOSS"

def test_shadow_mode_rejection(rt):
    rt.config_service.update({"operating_mode": "autonomous", "execution_mode": "shadow"})
    req = OrderRequest("XAUUSD", "buy", 0.01, 3920.0, 3950.0, "d1")
    result = rt.gateway.validate(req)
    assert result.code == "SHADOW_MODE"

def test_kill_switch_blocks_risk_increase_only(rt):
    rt.store.set_kill_switch(True)
    # Close should still work
    assert rt.gateway.close("12345", "MANUAL").ok is True
    # Place should fail
    req = OrderRequest("XAUUSD", "buy", 0.01, 3920.0, 3950.0, "d1")
    assert rt.gateway.validate(req).code == "KILL_SWITCH"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_guard_chain.py -q`
Expected: FAIL — some guards missing or wrong order

- [ ] **Step 3: Implement guard chain in `backend/ignite/services/gateway.py`**

Ensure `validate()` checks guards in spec order: kill_switch → mode → execution_mode (SHADOW_MODE) → watchlist → spec → spread → news → daily_loss → exposure → margin → lots → stops. Kill switch check in `close()`/`modify()` allows closes but blocks entries/risk-increasing changes.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_guard_chain.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/ignite/services/gateway.py tests/test_guard_chain.py
git commit -m "feat(gateway): hardened guard chain with correct order"
```

---

### Task 2: Spec-driven trailing stops with ATR

**Files:**
- Modify: `backend/ignite/agent/position_manager.py`
- Test: `tests/test_trailing.py`

**Interfaces:**
- Consumes: `Runtime`, `AgentConfig` (trail_sl_atr, scale_in_atr, scale_out_levels)
- Produces: `PositionManager.trail_sl()` with ATR from latest analysis, volatility regime awareness; `check_scale_in()`, `check_scale_out()`; updates `trail_sl`, `max_favourable_atr`, `max_adverse_atr`, `last_managed_at` in store

- [ ] **Step 1: Write failing tests**

```python
def test_trailing_sl_only_moves_favorable(rt):
    pos = create_agent_position(side="BUY", entry=3930.0, sl=3920.0, tp=3950.0)
    # Price moves up 2 ATR
    rt.mcp.quote_override = (3935.0, 3935.5)
    rt.store.upsert_agent_position(pos)
    actions = PositionManager(rt, rt.config()).manage_position(AgentPosition(**pos))
    trail = next((a for a in actions if a.type == "TRAIL_SL"), None)
    assert trail is not None
    assert trail.new_sl > 3920.0  # Only moved up

def test_trailing_sl_respects_stops_level(rt):
    # spec.stops_level = 50 points
    pos = create_agent_position(side="BUY", entry=3930.0, sl=3925.0, tp=3950.0)
    rt.mcp.quote_override = (3930.20, 3930.30)  # Only 20 points above entry
    actions = PositionManager(rt, rt.config()).manage_position(AgentPosition(**pos))
    trail = next((a for a in actions if a.type == "TRAIL_SL"), None)
    assert trail is None  # Not enough distance

def test_scale_in_at_1_5R(rt):
    pos = create_agent_position(side="BUY", entry=3930.0, volume=0.02)
    rt.mcp.quote_override = (3936.0, 3936.10)  # 1.5R move with ATR=2.0
    actions = PositionManager(rt, rt.config()).manage_position(AgentPosition(**pos))
    scale_in = next((a for a in actions if a.type == "SCALE_IN"), None)
    assert scale_in is not None
    assert scale_in.volume == 0.01  # 50% of original

def test_scale_out_at_levels(rt):
    pos = create_agent_position(side="BUY", entry=3930.0, volume=0.03)
    rt.config.scale_out_levels = (1.0, 2.0, 3.0)
    rt.mcp.quote_override = (3932.0, 3932.10)  # 1R move
    actions = PositionManager(rt, rt.config()).manage_position(AgentPosition(**pos))
    scale_out = next((a for a in actions if a.type == "SCALE_OUT"), None)
    assert scale_out is not None
    assert scale_out.volume == 0.01  # 1/3 of position
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_trailing.py -q`
Expected: FAIL — ATR source, stops_level, scale logic incomplete

- [ ] **Step 3: Implement in `backend/ignite/agent/position_manager.py`**

1. `trail_sl()`: Read ATR from latest analysis `features_json`; calculate new SL = price ± trail_sl_atr * ATR; enforce `stops_level` (min distance); only move SL in favorable direction; update `trail_sl` and `last_managed_at`.
2. `check_scale_in()`: Trigger at 1.5R move; add 50% size; use `execution.scale` tool via gateway.
3. `check_scale_out()`: Trigger at config `scale_out_levels` (1R, 2R, 3R); close 1/3 each level; use `execution.scale` tool.
4. Track `max_favourable_atr`, `max_adverse_atr` per position.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_trailing.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/ignite/agent/position_manager.py tests/test_trailing.py
git commit -m "feat(positions): spec-driven trailing stops and scaling"
```

---

### Task 3: Reconciliation service

**Files:**
- Create: `backend/ignite/services/reconciliation.py`
- Modify: `backend/ignite/agent/position_manager.py` (integrate reconciliation)
- Test: `tests/test_reconciliation.py`

**Interfaces:**
- Consumes: `Runtime`, `Ledger`, `Store`
- Produces: `ReconciliationService.run()` → list of `ReconciliationResult`; updates `agent_positions` status, `realised_pnl`, `r_multiple`, `last_synced_at`, `broker_snapshot_json`

- [ ] **Step 1: Write failing tests**

```python
def test_reconcile_broker_closed_position(rt):
    # Position in store, closed in broker
    rt.store.upsert_agent_position(create_agent_position(ticket="12345"))
    # Broker deal history shows closed trade
    rt.mcp.closed_trades_override = [{"ticket": "12345", "net": 45.50, "entry": 3930.0, "exit": 3940.0, "volume": 0.01, "sl": 3920.0}]
    result = ReconciliationService(rt).run()
    pos = rt.store.agent_position("12345")
    assert pos["status"] == "closed"
    assert pos["realised_pnl"] == 45.50
    assert abs(pos["r_multiple"] - 1.0) < 0.01

def test_reconcile_orphan_position(rt):
    # Position in store but not in broker
    rt.store.upsert_agent_position(create_agent_position(ticket="99999"))
    rt.mcp.positions_override = []  # No positions in broker
    result = ReconciliationService(rt).run()
    pos = rt.store.agent_position("99999")
    assert pos["status"] == "orphaned"

def test_reconcile_unknown_order(rt):
    # Gateway returned UNRESOLVED, order exists in broker but no position yet
    rt.store.upsert_order({"id": "dec1", "state": "sent", "position_id": None, "ticket": "55555"})
    rt.mcp.positions_override = [create_live_position(ticket="55555")]
    result = ReconciliationService(rt).run()
    order = rt.store.order("dec1")
    assert order["state"] == "filled"
    pos = rt.store.agent_position("55555")
    assert pos is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_reconciliation.py -q`
Expected: FAIL — ReconciliationService not implemented

- [ ] **Step 3: Implement `backend/ignite/services/reconciliation.py`**

```python
class ReconciliationService:
    def __init__(self, rt: Runtime):
        self.rt = rt

    def run(self) -> list[ReconciliationResult]:
        # 1. Get live broker positions
        # 2. Get agent positions from store
        # 3. Match by ticket
        # 4. For each agent position:
        #    - If live: update SL/TP, mfe/mae, last_synced_at, broker_snapshot_json
        #    - If not live: check closed_trades for PnL/R; mark closed or orphaned
        # 5. For each live position not in agent_positions with "ignite" comment:
        #    - Adopt: upsert with status="adopted"
        # 6. For each order with state="sent"/"unknown":
        #    - Check broker for fill; update state, bind position
        # 7. Persist all changes; return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_reconciliation.py -q`
Expected: PASS

- [ ] **Step 5: Integrate into PositionManager.manage_all()**

Call `ReconciliationService(rt).run()` at start of `manage_all()`.

- [ ] **Step 6: Commit**

```bash
git add backend/ignite/services/reconciliation.py backend/ignite/agent/position_manager.py tests/test_reconciliation.py
git commit -m "feat(reconciliation): broker position/PnL reconciliation"
```

---

### Task 4: Gateway partial close (scale-out) support

**Files:**
- Modify: `backend/ignite/services/gateway.py`
- Test: `tests/test_gateway_scale.py`

**Interfaces:**
- Consumes: `OrderRequest` with partial volume for scale-out
- Produces: `OrderResult` for partial close

- [ ] **Step 1: Write failing tests**

```python
def test_scale_out_partial_close(rt):
    rt.config_service.update({"operating_mode": "autonomous", "execution_mode": "live"})
    rt.mcp.positions.append(create_live_position(ticket="12345", volume=0.03))
    result = rt.gateway.scale("12345", "reduce", 0.01, None, None)
    assert result.ok is True
    # Broker should have received partial close
    assert rt.mcp.called("trade_partial_close") or rt.mcp.called("trade_close_single_position")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_gateway_scale.py -q`
Expected: FAIL — `scale()` not implemented or doesn't handle partial volume

- [ ] **Step 3: Implement in `backend/ignite/services/gateway.py`**

Add `scale(ticket, side, volume, sl, tp)` method. For `reduce`, call broker partial close (MT5 `trade_close_partial` or close full then reopen remainder). Validate volume against `volume_min`/`volume_step`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_gateway_scale.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/ignite/services/gateway.py tests/test_gateway_scale.py
git commit -m "feat(gateway): partial close for scale-out"
```

---

### Task 5: Position status lifecycle & events

**Files:**
- Modify: `backend/ignite/agent/position_manager.py`, `backend/ignite/store/db.py`
- Test: `tests/test_position_lifecycle.py`

**Interfaces:**
- Produces: `agent_positions.status` transitions: `pending → open → protected → trailing → partial → closing → closed` (or `orphaned`/`unprotected`)

- [ ] **Step 1: Write failing tests**

```python
def test_position_status_transitions(rt):
    # New position from gateway
    rt.store.upsert_agent_position(create_agent_position(status="pending"))
    # After protection confirmed
    rt.store.upsert_agent_position(create_agent_position(status="protected"))
    # After trailing
    rt.store.upsert_agent_position(create_agent_position(status="trailing"))
    # After scale-out
    rt.store.upsert_agent_position(create_agent_position(status="partial"))
    # After close
    rt.store.close_agent_position("12345", "AGENT_EXIT", 45.0, 1.0)
    pos = rt.store.agent_position("12345")
    assert pos["status"] == "closed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_position_lifecycle.py -q`
Expected: FAIL — status not updated on transitions

- [ ] **Step 3: Implement status updates**

In `PositionManager._apply_action()` and reconciliation: update `status` column on each transition. Emit `agent_events` for `position.opened`, `position.protected`, `position.trailed`, `position.scaled`, `position.closed`, `position.orphaned`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_position_lifecycle.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/ignite/agent/position_manager.py backend/ignite/store/db.py tests/test_position_lifecycle.py
git commit -m "feat(positions): status lifecycle and events"
```

---

### Task 6: Slice 3 verification

- [ ] **Step 1: Run full backend suite**

Run: `pytest tests -q`
Expected: all pass (Slice 1 + 2 + new Slice 3 tests)

- [ ] **Step 2: Run frontend checks**

Run: `npm run typecheck && npm run build` in `frontend/`
Expected: both pass

- [ ] **Step 3: Update spec status**

Change design spec header to include `Implemented: slice 3 (execution & supervision)`

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-11-13-agentic-trading-platform-design.md
git commit -m "docs: mark slice 3 (execution & supervision) implemented"
```