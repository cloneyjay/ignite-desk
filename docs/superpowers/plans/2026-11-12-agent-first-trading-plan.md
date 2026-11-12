# Agent-First Autonomous Trading Platform — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a dedicated agent worker process that runs autonomously at 03:00 UTC + every 30 min, analyses all watchlist symbols, executes trades through full lifecycle (entry → trail SL → scale in/out → close), and provides a global UI toggle + chat interface — all while preserving existing human-in-the-loop flows.

**Architecture:** Dedicated background worker process (`python -m backend.ignite.agent.worker`) with APScheduler (cron 03:00 + interval 30min), following the existing Kronos worker pattern. Agent owns decision engine (`engine.py`), position manager (`position_manager.py`), and synthesis (`synthesis.py`). Uses existing Runtime, MCP client, and SQLite. UI adds global toggle, collapsible sidebar, and chat interface.

**Tech Stack:** Python 3.14, APScheduler 3.10, FastAPI, SQLite (WAL), TanStack Query, React 18, Tailwind 3.

**Spec:** `docs/superpowers/specs/2026-11-12-agent-first-trading-design.md`

---

## Global Constraints

- Python 3.14, FastAPI, SQLite WAL, APScheduler 3.10, React 18 + TanStack Query 5 + Tailwind 3
- All config from `.env` via `backend/ignite/config.py` (existing pattern)
- Database: SQLite WAL, migrations run on startup (existing `Store._migrate()`)
- Agent worker separate process, communicates via shared SQLite (not HTTP)
- NVIDIA NIM (nemotron-3-ultra-550b-a55b) primary, Ollama (bonsai-2:2b) fallback, template final
- Risk engine: reuse existing `risk.v1` (0.5% risk, 1.5×ATR SL, 3×ATR TP, 2R min, 30pt spread cap)
- Daily loss limit: 3% equity (realised + open risk), auto-disables execution
- Session open 03:00 UTC + every 30 min; session end 21:00 UTC flat
- Global agent toggle in UI (DB flag `agent_config.enabled`), immediate effect
- Agent full lifecycle: entry → trail SL (1.5×ATR) → scale in at 1.5R (50% size) → scale out at 1R/2R/3R → close on reversal/daily-loss/session-end
- Collapsible AnalysisDrawer: 540px ↔ 60px, hover preview on retracted, persist in localStorage
- Chat interface: routes natural language → skills (analysis_narrative, daily_brief, news_bias, draft_review, postmortem)
- "analyse XAUUSD M15" in chat → starts analysis job → waits → generates narrative
- All decisions audited in `agent_decisions` + `agent_positions` + `agent_runs`
- Tests: pytest, 55 existing pass; new tests for each module
- UI verification: `npm run verify:ui` (5 screens, 0 console errors)

---

## Review Focus

| Input / Condition | Expected Behavior | Test Location |
|-------------------|-------------------|---------------|
| Agent disabled via toggle mid-cycle | Current cycle completes, no new cycles start | `test_agent_toggle.py::test_disable_mid_cycle` |
| Daily loss limit hit (3%) | Agent stops new entries, manages existing to flat | `test_position_manager.py::test_daily_loss_limit` |
| Correlation > 0.7 between positions | Agent blocks new correlated entry | `test_position_manager.py::test_correlation_limit` |
| Kill switch ON | All agent execution blocked, cycles still run but no executes | `test_agent_toggle.py::test_kill_switch_blocks` |
| Session end (21:00 UTC) | All agent positions closed flat | `test_position_manager.py::test_session_end_flat` |

---

## File Map

| File | Responsibility |
|------|----------------|
| `backend/ignite/agent/config.py` | AgentConfig dataclass, env loading |
| `backend/ignite/agent/worker.py` | Entrypoint, APScheduler, signal handling |
| `backend/ignite/agent/engine.py` | AgentEngine, run_cycle, analyse_symbol |
| `backend/ignite/agent/synthesis.py` | Fundamental/technical/attribution contexts, synthesise_decision |
| `backend/ignite/agent/position_manager.py` | PositionManager, trail SL, scale in/out, exit conditions |
| `backend/ignite/store/agent_schema.sql` | agent_config, agent_decisions, agent_positions, agent_symbol_config |
| `backend/ignite/store/db.py` | Add agent tables to migration, CRUD methods |
| `backend/ignite/api/routes/agent.py` | Add /agent/status, /agent/toggle, /agent/positions, /agent/config |
| `backend/ignite/api/app.py` | Ensure agent worker health in /api/health |
| `backend/ignite/cli.py` | Add `ignite agent start` command |
| `frontend/src/components/AgentPanel.tsx` | Global toggle, status, chat launcher |
| `frontend/src/components/AgentChat.tsx` | Chat interface with quick actions |
| `frontend/src/components/AnalysisDrawer.tsx` | Add retract toggle (540px ↔ 60px) |
| `frontend/src/hooks/useAgent.ts` | New hooks for agent status, toggle, chat |
| `frontend/src/lib/api.ts` | Agent API endpoints |
| `frontend/src/lib/types.ts` | Agent status, toggle, chat types |
| `tests/test_agent_worker.py` | Worker lifecycle, scheduler, graceful shutdown |
| `tests/test_agent_engine.py` | Decision synthesis, guards, synthesis weights |
| `tests/test_position_manager.py` | Trail SL, scale in/out, exit conditions |
| `tests/test_agent_api.py` | Toggle, status, positions, config endpoints |

---

## Tasks

### Task 1: Agent Config + Database Schema

**Files:**
- Create: `backend/ignite/agent/config.py`
- Create: `backend/ignite/store/agent_schema.sql`
- Modify: `backend/ignite/store/db.py` (add agent tables to migration + CRUD)
- Modify: `backend/ignite/config.py` (add AgentConfig loading)

**Interfaces:**
- Produces: `AgentConfig` dataclass, `Store.agent_config()`, `Store.set_agent_config()`, `Store.agent_decisions*`, `Store.agent_positions*`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_agent_config.py
def test_agent_config_defaults():
    cfg = AgentConfig()
    assert cfg.enabled is False
    assert cfg.cycle_interval_min == 30
    assert cfg.session_open_hour == 3
    assert cfg.daily_loss_limit_pct == 0.03

def test_agent_config_from_env(monkeypatch):
    monkeypatch.setenv("IGNITE_AGENT_ENABLED", "true")
    monkeypatch.setenv("IGNITE_AGENT_CYCLE_INTERVAL_MIN", "15")
    cfg = AgentConfig()
    assert cfg.enabled is True
    assert cfg.cycle_interval_min == 15
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_config.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement `AgentConfig` in `backend/ignite/agent/config.py`**

```python
@dataclass(frozen=True)
class AgentConfig:
    enabled: bool = False
    symbols: tuple[str, ...] = ()
    timeframe: str = "M15"
    cycle_interval_min: int = 30
    session_open_hour: int = 3
    max_concurrent_analyses: int = 3
    position_check_interval_sec: int = 60
    max_concurrent_positions: int = 3
    daily_loss_limit_pct: float = 0.03
    trail_sl_atr: float = 1.5
    scale_in_atr: float = 1.5
    scale_out_levels: tuple[float, ...] = (1.0, 2.0, 3.0)
    max_correlation: float = 0.7
    session_end_hour: int = 21

    @classmethod
    def from_env(cls) -> "AgentConfig":
        ...
```

- [ ] **Step 4: Add agent schema to `backend/ignite/store/agent_schema.sql`**

```sql
CREATE TABLE IF NOT EXISTS agent_config (
    key       TEXT PRIMARY KEY,
    enabled   INTEGER NOT NULL DEFAULT 0,
    config_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_decisions (
    id              TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    timeframe       TEXT NOT NULL,
    analysis_id     TEXT,
    signal_side     TEXT NOT NULL,
    p_up            REAL,
    edge_atr        REAL,
    decision        TEXT NOT NULL,
    confidence      REAL,
    reasoning       TEXT,
    executed        INTEGER NOT NULL DEFAULT 0,
    execution_error TEXT,
    draft_id        TEXT,
    attribution_json TEXT,
    fundamental_json TEXT,
    technical_json TEXT,
    risk_json TEXT
);

CREATE TABLE IF NOT EXISTS agent_positions (
    ticket          TEXT PRIMARY KEY,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    entry_price     REAL NOT NULL,
    volume          REAL NOT NULL,
    sl              REAL,
    tp              REAL,
    opened_at       TEXT NOT NULL,
    managed_by_agent INTEGER NOT NULL DEFAULT 1,
    trail_sl        REAL,
    scale_in_count  INTEGER DEFAULT 0,
    scale_out_count INTEGER DEFAULT 0,
    max_favourable_atr REAL,
    max_adverse_atr REAL,
    last_managed_at TEXT,
    closed_at       TEXT,
    close_reason    TEXT,
    realised_pnl    REAL,
    r_multiple      REAL
);

CREATE TABLE IF NOT EXISTS agent_symbol_config (
    symbol      TEXT PRIMARY KEY,
    config_json TEXT NOT NULL,
    enabled     INTEGER NOT NULL DEFAULT 1
);
```

- [ ] **Step 5: Add agent CRUD to `backend/ignite/store/db.py`**

```python
def agent_config(self) -> dict[str, Any] | None:
    row = self._conn.execute("SELECT * FROM agent_config WHERE key='global'").fetchone()
    return dict(row) if row else None

def set_agent_config(self, enabled: bool, config_json: str) -> None:
    self._conn.execute(
        "INSERT INTO agent_config (key, enabled, config_json, updated_at) VALUES ('global', ?, ?, ?)"
        " ON CONFLICT(key) DO UPDATE SET enabled=excluded.enabled, config_json=excluded.config_json, updated_at=excluded.updated_at",
        (int(enabled), config_json, utc_now())
    )
    self._conn.commit()

def insert_agent_decision(self, decision: dict) -> None:
    ...

def agent_decisions(self, limit=100, symbol=None) -> list[dict]:
    ...

def upsert_agent_position(self, pos: dict) -> None:
    ...

def agent_positions(self) -> list[dict]:
    ...
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_agent_config.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/ignite/agent/config.py backend/ignite/store/agent_schema.sql backend/ignite/store/db.py backend/ignite/config.py tests/test_agent_config.py
git commit -m "feat(agent): config + schema + store CRUD"
```

---

### Task 2: Agent Worker Entrypoint + Scheduler

**Files:**
- Create: `backend/ignite/agent/worker.py`
- Modify: `backend/ignite/cli.py` (add `agent start` command)

**Interfaces:**
- Consumes: `AgentConfig`, `Runtime`, `AgentEngine`
- Produces: Runnable process with APScheduler

- [ ] **Step 1: Write failing tests**

```python
# tests/test_agent_worker.py
def test_worker_schedules_cron_and_interval(monkeypatch):
    """Scheduler has cron at 03:00 + interval 30min."""
    ...

def test_worker_graceful_shutdown_on_sigterm():
    """SIGTERM sets shutdown flag, waits for current cycle."""
    ...
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_worker.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `backend/ignite/agent/worker.py`**

```python
def main():
    settings = load_settings()
    config = AgentConfig.from_env()
    runtime = Runtime(settings)
    engine = AgentEngine(runtime, config)
    scheduler = BackgroundScheduler()
    scheduler.add_job(engine.run_cycle, 'cron', hour=config.session_open_hour, minute=0, id='session_open')
    scheduler.add_job(engine.run_cycle, 'interval', minutes=config.cycle_interval_min, id='interval')
    scheduler.start()
    # signal handling, logging, graceful shutdown
    ...
```

- [ ] **Step 4: Add CLI command in `backend/ignite/cli.py`**

```python
def cmd_agent(args):
    if args.agent_command == "start":
        # run worker
    elif args.agent_command == "status":
        # print agent status from DB
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_agent_worker.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/ignite/agent/worker.py backend/ignite/cli.py tests/test_agent_worker.py
git commit -m "feat(agent): worker entrypoint + scheduler + CLI"
```

---

### Task 3: Agent Engine — Core Decision Loop

**Files:**
- Create: `backend/ignite/agent/engine.py`
- Test: `tests/test_agent_engine.py`

**Interfaces:**
- Consumes: `Runtime`, `AgentConfig`, `AgentEngine`
- Produces: `CycleResult`, `SymbolDecision`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_agent_engine.py
def test_run_cycle_iterates_watchlist(rt):
    engine = AgentEngine(rt, AgentConfig(symbols=("XAUUSD",)))
    result = engine.run_cycle()
    assert len(result.symbol_decisions) == 1
    assert result.symbol_decisions[0].symbol == "XAUUSD"

def test_analyse_symbol_returns_decision(rt):
    engine = AgentEngine(rt, AgentConfig())
    decision = engine.analyse_symbol("XAUUSD", "M15")
    assert decision.symbol == "XAUUSD"
    assert decision.action in ("ENTER", "MANAGE", "SKIP")
    assert 0 <= decision.confidence <= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_engine.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `backend/ignite/agent/engine.py`**

```python
@dataclass
class SymbolDecision:
    symbol: str
    timeframe: str
    action: Literal["ENTER", "MANAGE", "SKIP", "ERROR"]
    signal_side: Literal["LONG", "SHORT", "NONE"]
    p_up: float
    edge_atr: float
    confidence: float
    reasoning: str
    draft_id: str | None
    executed: bool
    error: str | None

@dataclass
class CycleResult:
    cycle_id: str
    started_at: str
    completed_at: str
    symbol_decisions: list[SymbolDecision]

class AgentEngine:
    def __init__(self, rt: Runtime, config: AgentConfig):
        self.rt = rt
        self.config = config

    def run_cycle(self) -> CycleResult:
        if not self.config.enabled:
            return CycleResult(..., symbol_decisions=[])
        # Check guards: kill_switch, daily_loss_limit, max_positions
        symbols = self._get_symbols()
        decisions = []
        for symbol in symbols:
            decisions.append(self.analyse_symbol(symbol, self.config.timeframe))
        return CycleResult(..., symbol_decisions=decisions)

    def analyse_symbol(self, symbol: str, timeframe: str) -> SymbolDecision:
        # 1. Run analysis graph (reuse existing run_analysis)
        # 2. Build contexts: fundamental, technical, attribution
        # 3. Synthesise decision
        # 4. If ENTER + executable draft → confirm → execute
        # 5. Record to agent_decisions
        ...

    def _check_guards(self) -> GuardResult:
        # kill_switch, daily_loss_limit, max_concurrent_positions
        ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_engine.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/ignite/agent/engine.py tests/test_agent_engine.py
git commit -m "feat(agent): engine - core decision loop"
```

---

### Task 4: Synthesis — Fundamental + Technical + Attribution

**Files:**
- Create: `backend/ignite/agent/synthesis.py`
- Test: `tests/test_agent_synthesis.py`

**Interfaces:**
- Consumes: `Runtime`, `ForecastResult`, `RiskConfig`
- Produces: `FundamentalContext`, `TechnicalContext`, `AttributionContext`, `Decision`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_agent_synthesis.py
def test_build_fundamental_context(rt):
    ctx = build_fundamental_context(rt, "XAUUSD")
    assert "high_impact_events" in ctx
    assert "news_bias" in ctx

def test_build_technical_context(rt):
    ctx = build_technical_context(rt, "XAUUSD", "M15")
    assert ctx.trend in ("up", "down", "flat")
    assert ctx.volatility_regime in ("compression", "expansion", "normal")
    assert "key_levels" in ctx

def test_synthesise_decision_weights():
    decision = synthesise(
        forecast=mock_forecast(p_up=0.8, edge_atr=1.2),
        fundamental=mock_fundamental(high_impact_usd=True),
        technical=mock_technical(trend="up", regime="expansion"),
        attribution=mock_attribution(last_hit=True),
        risk=RiskConfig(),
    )
    assert decision.action == "ENTER"
    assert decision.side == "LONG"
    assert decision.confidence > 0.7
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_synthesis.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `backend/ignite/agent/synthesis.py`**

```python
@dataclass
class FundamentalContext:
    high_impact_events: list[dict]
    news_bias: str  # "bullish", "bearish", "neutral"
    next_event_time: str | None

@dataclass
class TechnicalContext:
    trend: Literal["up", "down", "flat"]
    volatility_regime: Literal["compression", "expansion", "normal"]
    key_levels: dict[str, float]  # prior_day_h, prior_day_l, session_h, session_l
    atr: float

@dataclass
class AttributionContext:
    last_forecast_p_up: float | None
    last_realised_move_atr: float | None
    hit_rate: float | None

def build_fundamental_context(rt: Runtime, symbol: str) -> FundamentalContext:
    # Calendar high-impact USD/EUR/CNH/JPY next 24h
    # News bias from recent headlines
    ...

def build_technical_context(rt: Runtime, symbol: str, timeframe: str) -> TechnicalContext:
    # EMA trend, ATR regime, prior day H/L, session H/L
    ...

def build_attribution_context(rt: Runtime, analysis_id: str) -> AttributionContext:
    # Compare last forecast vs realised
    ...

def synthesise(forecast, fundamental, technical, attribution, risk) -> Decision:
    # Weights: forecast 40%, technical 30%, fundamental 30%
    # Apply guards in order: blackout, spread, drift, risk caps, correlation
    ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_synthesis.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/ignite/agent/synthesis.py tests/test_agent_synthesis.py
git commit -m "feat(agent): synthesis - fundamental, technical, attribution"
```

---

### Task 5: Position Manager — Full Lifecycle

**Files:**
- Create: `backend/ignite/agent/position_manager.py`
- Test: `tests/test_position_manager.py`

**Interfaces:**
- Consumes: `Runtime`, `AgentConfig`, `AgentPosition`
- Produces: `PositionAction` (trail_sl, scale_in, scale_out, close)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_position_manager.py
def test_trail_sl_atr_based(rt):
    pos = AgentPosition(ticket="1", symbol="XAUUSD", side="BUY", entry=3900, sl=3880, volume=0.01)
    pm = PositionManager(rt, AgentConfig(trail_sl_atr=1.5))
    atr = 10.0
    new_sl = pm.trail_sl(pos, atr)
    assert new_sl == 3885.0  # 1.5 ATR below entry for BUY

def test_scale_in_at_1_5R(rt):
    pos = AgentPosition(ticket="1", side="BUY", entry=3900, sl=3885, volume=0.01, trail_sl=3895)
    pm = PositionManager(rt, AgentConfig(scale_in_atr=1.5))
    # Price moved 1.5R in favour
    action = pm.check_scale_in(pos, atr=10.0, current_price=3915)
    assert action is not None
    assert action.volume == 0.005  # 50% of original

def test_scale_out_at_1R_2R_3R(rt):
    pos = AgentPosition(ticket="1", side="BUY", entry=3900, sl=3885, tp=3930, volume=0.01)
    pm = PositionManager(rt, AgentConfig(scale_out_levels=(1.0, 2.0, 3.0)))
    # At 1R (3915)
    action = pm.check_scale_out(pos, current_price=3915)
    assert action is not None and action.volume == 0.0033  # 1/3

def test_exit_on_signal_reversal(rt):
    pos = AgentPosition(ticket="1", side="BUY", entry=3900, sl=3885)
    pm = PositionManager(rt, AgentConfig())
    # Signal now SHORT
    reason = pm.check_exit_conditions(pos, current_signal="SHORT")
    assert reason == "SIGNAL_REVERSAL"

def test_exit_on_daily_loss_limit(rt):
    rt.store.set_setting("daily_realised_pnl", "-300")  # 3% of 10k
    pos = AgentPosition(ticket="1", side="BUY", entry=3900)
    pm = PositionManager(rt, AgentConfig(daily_loss_limit_pct=0.03))
    reason = pm.check_exit_conditions(pos, equity=10000)
    assert reason == "DAILY_LOSS_LIMIT"

def test_exit_on_session_end(rt):
    with patch("backend.ignite.agent.position_manager.datetime") as mock_dt:
        mock_dt.utcnow.return_value = datetime(2026, 11, 12, 21, 0, 0, tzinfo=timezone.utc)
        pos = AgentPosition(ticket="1", side="BUY", entry=3900)
        pm = PositionManager(rt, AgentConfig(session_end_hour=21))
        reason = pm.check_exit_conditions(pos)
        assert reason == "SESSION_END"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_position_manager.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `backend/ignite/agent/position_manager.py`**

```python
@dataclass
class PositionAction:
    type: Literal["TRAIL_SL", "SCALE_IN", "SCALE_OUT", "CLOSE"]
    ticket: str
    new_sl: float | None = None
    volume: float | None = None
    reason: str | None = None

class PositionManager:
    def __init__(self, rt: Runtime, config: AgentConfig):
        self.rt = rt
        self.config = config

    def manage_all(self) -> list[PositionAction]:
        actions = []
        positions = self.rt.store.agent_positions()
        for pos in positions:
            actions.extend(self.manage_position(pos))
        return actions

    def manage_position(self, pos: AgentPosition) -> list[PositionAction]:
        actions = []
        # 1. Check exit conditions (reversal, daily loss, session end, correlation)
        # 2. Trail SL
        # 3. Scale in
        # 4. Scale out
        return actions

    def trail_sl(self, pos: AgentPosition, atr: float) -> float | None:
        if pos.side == "BUY":
            new_sl = max(pos.sl or 0, pos.entry_price - self.config.trail_sl_atr * atr)
        else:
            new_sl = min(pos.sl or float('inf'), pos.entry_price + self.config.trail_sl_atr * atr)
        if new_sl != pos.sl:
            return new_sl
        return None

    def check_scale_in(self, pos: AgentPosition, atr: float, current_price: float) -> PositionAction | None:
        # Scale in at 1.5R, 50% size, max 2 scale-ins
        ...

    def check_scale_out(self, pos: AgentPosition, current_price: float) -> PositionAction | None:
        # Scale out at 1R, 2R, 3R (1/3 each)
        ...

    def check_exit_conditions(self, pos: AgentPosition, current_signal=None, equity=None) -> str | None:
        # Signal reversal, daily loss limit, session end, correlation breach
        ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_position_manager.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/ignite/agent/position_manager.py tests/test_position_manager.py
git commit -m "feat(agent): position manager - full lifecycle"
```

---

### Task 6: Worker Integration — Engine + Position Manager + Scheduler

**Files:**
- Modify: `backend/ignite/agent/worker.py` (wire engine + position manager)
- Modify: `backend/ignite/agent/engine.py` (add position management call)
- Test: `tests/test_agent_worker.py` (extend)

**Interfaces:**
- Consumes: `AgentEngine`, `PositionManager`, `Runtime`, `AgentConfig`
- Produces: Complete cycle with position management

- [ ] **Step 1: Write failing tests**

```python
# tests/test_agent_worker.py (extend)
def test_worker_runs_full_cycle_with_positions(rt):
    """Worker runs cycle, creates positions, position manager manages them."""
    ...
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_worker.py::test_worker_runs_full_cycle_with_positions -v`
Expected: FAIL

- [ ] **Step 3: Wire in `backend/ignite/agent/worker.py`**

```python
def main():
    ...
    engine = AgentEngine(runtime, config)
    pos_manager = PositionManager(runtime, config)
    scheduler.add_job(engine.run_cycle, 'cron', hour=config.session_open_hour, minute=0, id='session_open')
    scheduler.add_job(engine.run_cycle, 'interval', minutes=config.cycle_interval_min, id='interval')
    scheduler.add_job(pos_manager.manage_all, 'interval', seconds=config.position_check_interval_sec, id='position_manager')
    ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_worker.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/ignite/agent/worker.py backend/ignite/agent/engine.py tests/test_agent_worker.py
git commit -m "feat(agent): worker integration - engine + position manager"
```

---

### Task 7: API Routes — Agent Status, Toggle, Positions, Config

**Files:**
- Modify: `backend/ignite/api/routes/agent.py`
- Test: `tests/test_agent_api.py`

**Interfaces:**
- Produces: REST endpoints for agent control

- [ ] **Step 1: Write failing tests**

```python
# tests/test_agent_api.py
def test_agent_status_endpoint(rt):
    client, _ = rt
    resp = client.get("/api/agent/status")
    assert resp.status_code == 200
    assert "enabled" in resp.json()
    assert "next_cycle" in resp.json()

def test_agent_toggle_endpoint(rt):
    client, rt_obj = rt
    # Enable
    resp = client.post("/api/agent/toggle", json={"enabled": True})
    assert resp.status_code == 200
    assert resp.json()["enabled"] is True
    # Verify DB
    assert rt_obj.store.agent_config()["enabled"] == 1
    # Disable
    resp = client.post("/api/agent/toggle", json={"enabled": False})
    assert resp.json()["enabled"] is False

def test_agent_positions_endpoint(rt):
    client, rt_obj = rt
    # Seed agent position
    rt_obj.store.upsert_agent_position({...})
    resp = client.get("/api/agent/positions")
    assert resp.status_code == 200
    assert len(resp.json()["positions"]) == 1

def test_agent_config_endpoint(rt):
    client, _ = rt
    resp = client.get("/api/agent/config")
    assert resp.status_code == 200
    assert "cycle_interval_min" in resp.json()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_api.py -v`
Expected: FAIL

- [ ] **Step 3: Implement endpoints in `backend/ignite/api/routes/agent.py`**

```python
@router.get("/agent/status")
def agent_status(rt: Runtime = Depends(get_rt)):
    config = rt.store.agent_config() or {"enabled": False}
    decisions_today = len([d for d in rt.store.agent_decisions(limit=1000) if d["created_at"].startswith(today_utc())])
    positions = rt.store.agent_positions()
    return {
        "enabled": bool(config.get("enabled")),
        "last_cycle": rt.store.setting("agent_last_cycle"),
        "next_cycle": compute_next_cycle(rt),
        "decisions_today": decisions_today,
        "executed_today": len([d for d in rt.store.agent_decisions(limit=1000) if d.get("executed")]),
        "positions_open": len(positions),
        "daily_pnl": sum(p.get("realised_pnl", 0) for p in positions),
        "daily_loss_limit": rt.risk_config().daily_loss_limit_pct,
    }

@router.post("/agent/toggle")
def agent_toggle(body: ToggleRequest, rt: Runtime = Depends(get_rt)):
    enabled = body.enabled
    rt.store.set_agent_config(enabled, json.dumps(rt.agent_config.__dict__))
    rt.events.publish("agent.toggled", {"enabled": enabled})
    return {"enabled": enabled}

@router.get("/agent/positions")
def agent_positions(rt: Runtime = Depends(get_rt)):
    return {"positions": rt.store.agent_positions()}

@router.get("/agent/positions/{ticket}")
def agent_position(ticket: str, rt: Runtime = Depends(get_rt)):
    pos = next((p for p in rt.store.agent_positions() if p["ticket"] == ticket), None)
    if not pos:
        raise ApiError(404, "not_found", f"no position {ticket}")
    return {"position": pos}

@router.post("/agent/positions/{ticket}/close")
def close_agent_position(ticket: str, rt: Runtime = Depends(get_rt)):
    # Execute close via MCP
    ...

@router.get("/agent/config")
def agent_config_get(rt: Runtime = Depends(get_rt)):
    return rt.agent_config.__dict__

@router.put("/agent/config")
def agent_config_put(body: ConfigRequest, rt: Runtime = Depends(get_rt)):
    # Update config in DB
    ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/ignite/api/routes/agent.py tests/test_agent_api.py
git commit -m "feat(agent): API routes - status, toggle, positions, config"
```

---

### Task 8: Frontend — AgentPanel, AgentChat, Collapsible Drawer

**Files:**
- Create: `frontend/src/components/AgentPanel.tsx`
- Create: `frontend/src/components/AgentChat.tsx`
- Modify: `frontend/src/components/AnalysisDrawer.tsx` (retract toggle)
- Create: `frontend/src/hooks/useAgent.ts`
- Modify: `frontend/src/lib/api.ts` (agent endpoints)
- Modify: `frontend/src/lib/types.ts` (agent types)
- Modify: `frontend/src/pages/Watchlist.tsx` (integrate AgentPanel)

**Interfaces:**
- Produces: React components, hooks, API types

- [ ] **Step 1: Write failing tests (typecheck + build)**

```bash
# TypeScript compilation
npm run typecheck
# Build
npm run build
```

- [ ] **Step 2: Run typecheck to verify it fails**

Run: `npm run typecheck`
Expected: FAIL (missing types/components)

- [ ] **Step 3: Implement types in `frontend/src/lib/types.ts`**

```typescript
export interface AgentStatus {
  enabled: boolean;
  last_cycle: string | null;
  next_cycle: string | null;
  decisions_today: number;
  executed_today: number;
  positions_open: number;
  daily_pnl: number;
  daily_loss_limit: number;
}

export interface AgentToggleRequest { enabled: boolean; }
export interface AgentToggleResponse { enabled: boolean; }

export interface AgentPosition {
  ticket: string;
  symbol: string;
  side: "buy" | "sell";
  entry_price: number;
  volume: number;
  sl: number | null;
  tp: number | null;
  trail_sl: number | null;
  opened_at: string;
  unrealised_pnl: number;
  max_favourable_atr: number | null;
  max_adverse_atr: number | null;
}

export interface ChatMessage {
  role: "user" | "agent";
  content: string;
  timestamp: string;
}
```

- [ ] **Step 4: Implement `frontend/src/lib/api.ts` agent endpoints**

```typescript
export const api = {
  // ... existing
  agentStatus: () => request<AgentStatus>("/agent/status"),
  agentToggle: (enabled: boolean) => request<AgentToggleResponse>("/agent/toggle", {
    method: "POST", body: JSON.stringify({ enabled })
  }),
  agentPositions: () => request<{ positions: AgentPosition[] }>("/agent/positions"),
  agentPosition: (ticket: string) => request<{ position: AgentPosition }>(`/agent/positions/${ticket}`),
  agentClosePosition: (ticket: string) => request("/agent/positions/${ticket}/close", { method: "POST" }),
  agentConfig: () => request<Record<string, any>>("/agent/config"),
  agentConfigUpdate: (config: Record<string, any>) => request("/agent/config", {
    method: "PUT", body: JSON.stringify(config)
  }),
  agentChat: (text: string) => request("/agent/chat", {
    method: "POST", body: JSON.stringify({ text })
  }),
};
```

- [ ] **Step 5: Implement `frontend/src/hooks/useAgent.ts`**

```typescript
export function useAgentStatus() {
  return useQuery({ queryKey: ["agent", "status"], queryFn: api.agentStatus, refetchInterval: 5000 });
}

export function useAgentToggle() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (enabled: boolean) => api.agentToggle(enabled),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["agent", "status"] }),
  });
}

export function useAgentChat() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (text: string) => api.agentChat(text),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["agent", "runs"] }),
  });
}
```

- [ ] **Step 6: Implement `frontend/src/components/AgentPanel.tsx`**

```tsx
export default function AgentPanel() {
  const status = useAgentStatus();
  const toggle = useAgentToggle();
  const openChat = useChatOpen(); // context or state

  return (
    <Panel title="Agent" subtitle={status.data?.enabled ? "LIVE" : "STANDBY"}>
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <span className={status.data?.enabled ? "text-long" : "text-fog"}>
            {status.data?.enabled ? "LIVE" : "STANDBY"}
          </span>
          <Badge tone={status.data?.enabled ? "long" : "neutral"}>
            {status.data?.enabled ? "ACTIVE" : "PAUSED"}
          </Badge>
        </div>
        <div className="grid grid-cols-2 gap-2 text-[11px]">
          <div><span className="text-fog">Next cycle</span><div className="font-mono">{formatTime(status.data?.next_cycle)}</div></div>
          <div><span className="text-fog">Decisions today</span><div className="font-mono">{status.data?.decisions_today}</div></div>
          <div><span className="text-fog">Positions</span><div className="font-mono">{status.data?.positions_open}</div></div>
          <div><span className="text-fog">P&L</span><div className="font-mono text-{status.data?.daily_pnl >= 0 ? 'long' : 'short'}">{money(status.data?.daily_pnl)}</div></div>
        </div>
        <div className="flex gap-2">
          <Button variant={status.data?.enabled ? "danger" : "primary"} onClick={() => toggle.mutate(!status.data?.enabled)}>
            {status.data?.enabled ? "Disable Agent" : "Enable Agent"}
          </Button>
          <Button variant="secondary" onClick={openChat}>Chat</Button>
        </div>
      </div>
    </Panel>
  );
}
```

- [ ] **Step 7: Implement `frontend/src/components/AgentChat.tsx`**

```tsx
export default function AgentChat({ isOpen, onClose }) {
  const chat = useAgentChat();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");

  const send = () => {
    if (!input.trim()) return;
    const userMsg = { role: "user", content: input, timestamp: new Date().toISOString() };
    setMessages(m => [...m, userMsg]);
    setInput("");
    chat.mutate(input, {
      onSuccess: (res) => setMessages(m => [...m, { role: "agent", content: res.output.narrative, timestamp: new Date().toISOString() }]),
    });
  };

  return (
    <div className="fixed bottom-4 right-4 w-[420px] h-[500px] ...">
      <header>...</header>
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[80%] rounded-lg px-3 py-2 ${m.role === "user" ? "bg-gold-500/20 text-gold-300" : "bg-ink-800 text-paper"}`}>
              {m.content}
            </div>
          </div>
        ))}
      </div>
      <footer>
        <input value={input} onChange={e => setInput(e.target.value)} onKeyDown={e => e.key === "Enter" && send()} placeholder="analyse XAUUSD M15, daily brief, what's my risk..." />
      </footer>
    </div>
  );
}
```

- [ ] **Step 8: Modify `frontend/src/components/AnalysisDrawer.tsx` for retract toggle**

```tsx
// Add state
const [isRetracted, setIsRetracted] = useState(() => localStorage.getItem("drawerRetracted") === "true");
const width = isRetracted ? 60 : 540;

// In return:
<aside className={`fixed right-0 top-[58px] z-50 flex h-[calc(100vh-58px)] transition-all duration-200 ease-out ${isRetracted ? "w-[60px]" : "w-[540px]"} ...`}>

// Retract handle
<button onClick={() => setIsRetracted(!isRetracted)} className="absolute -left-8 top-1/2 -translate-y-1/2 p-1 rounded-r-md border border-line bg-ink-900 hover:bg-ink-800">
  <ChevronLeftIcon className={isRetracted ? "rotate-180" : ""} />
</button>

// Conditional render
{!isRetracted ? (
  <FullDrawerContent />
) : (
  <RetractedIconStrip />
)}
```

- [ ] **Step 8: Integrate AgentPanel in `frontend/src/pages/Watchlist.tsx`**

```tsx
import AgentPanel from "../components/AgentPanel";
import AgentChat from "../components/AgentChat";

export default function Watchlist() {
  const [chatOpen, setChatOpen] = useState(false);
  ...
  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-[264px_minmax(0,1fr)]">
      <div className="space-y-3">
        <AgentPanel onChatOpen={() => setChatOpen(true)} />
        ...
      </div>
      ...
      {chatOpen && <AgentChat isOpen={chatOpen} onClose={() => setChatOpen(false)} />}
    </div>
  );
}
```

- [ ] **Step 9: Run typecheck + build to verify**

Run: `npm run typecheck && npm run build`
Expected: PASS (exit 0)

- [ ] **Step 10: Run UI verification**

Run: `npm run verify:ui`
Expected: 5/5 screens pass, 0 console errors

- [ ] **Step 11: Commit**

```bash
git add frontend/src/components/AgentPanel.tsx frontend/src/components/AgentChat.tsx frontend/src/components/AnalysisDrawer.tsx frontend/src/hooks/useAgent.ts frontend/src/lib/api.ts frontend/src/lib/types.ts frontend/src/pages/Watchlist.tsx
git commit -m "feat(frontend): AgentPanel, AgentChat, collapsible drawer, chat integration"
```

---

### Task 9: API Health + CLI Integration

**Files:**
- Modify: `backend/ignite/api/routes/system.py` (add agent worker health)
- Modify: `backend/ignite/api/app.py` (ensure agent routes included)
- Modify: `backend/ignite/cli.py` (agent start/status commands)

**Interfaces:**
- Consumes: Agent worker process status
- Produces: `/api/health` agent field, `ignite agent start|status`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_agent_health.py
def test_health_includes_agent_worker():
    client, _ = env
    resp = client.get("/api/health")
    assert resp.json()["agent_worker"]["ready"] is True
```

- [ ] **Step 2: Implement health check in `backend/ignite/api/routes/system.py`**

```python
def health(rt: Runtime = Depends(get_rt)):
    ...
    agent_worker = {"ready": False, "pid": None}
    try:
        # Check if agent worker process is alive (via PID file or DB heartbeat)
        pid = rt.store.setting("agent_worker_pid")
        if pid and is_process_alive(pid):
            agent_worker = {"ready": True, "pid": pid}
    except Exception:
        pass
    return { ..., "agent_worker": agent_worker }
```

- [ ] **Step 3: Add CLI commands in `backend/ignite/cli.py`**

```python
def cmd_agent(args):
    if args.agent_command == "start":
        # subprocess.Popen([sys.executable, "-m", "backend.ignite.agent.worker"])
    elif args.agent_command == "status":
        # read agent_config, print enabled, last cycle, next cycle
```

- [ ] **Step 5: Run tests + verify**

Run: `pytest tests/test_agent_health.py -v && npm run typecheck`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/ignite/api/routes/system.py backend/ignite/cli.py tests/test_agent_health.py
git commit -m "feat(agent): health check + CLI commands"
```

---

### Task 10: End-to-End Tests + UI Verification

**Files:**
- Test: `tests/test_agent_e2e.py`
- Test: `tests/test_agent_chat.py`

**Interfaces:**
- Full cycle: chat "analyse XAUUSD M15" → job → narrative
- UI: verify-ui passes

- [ ] **Step 1: Write E2E test**

```python
# tests/test_agent_e2e.py
def test_chat_analyse_triggers_job_and_narrative(rt):
    client, rt_obj = rt
    # 1. Chat "analyse XAUUSD M15"
    resp = client.post("/api/agent/chat", json={"text": "analyse XAUUSD M15"})
    assert resp.status_code == 200
    assert resp.json()["route"]["skill"] == "analysis_narrative"
    # 2. Job created
    job_id = resp.json()["output"]["analysis_id"]  # wait logic in chat
    # 3. Narrative generated
    assert resp.json()["output"]["narrative"] is not None
    assert resp.json()["output"]["status"] == "ok"
```

- [ ] **Step 2: Run full test suite**

Run: `pytest tests -q`
Expected: 55+ new tests pass

- [ ] **Step 3: Run UI verification**

Run: `cd frontend && npm run verify:ui`
Expected: 5/5 screens, 0 console errors

- [ ] **Step 4: Commit**

```bash
git add tests/test_agent_e2e.py tests/test_agent_chat.py
git commit -m "test(agent): e2e chat + UI verification"
```

---

## Final Validation

- [ ] All 55+ tests pass
- [ ] `npm run typecheck` passes
- [ ] `npm run build` passes
- [ ] `npm run verify:ui` passes (5/5 screens, 0 errors)
- [ ] Agent worker starts: `python -m backend.ignite.agent.worker`
- [ ] Toggle enables/disables in <1s
- [ ] Chat "analyse XAUUSD M15" → job → narrative
- [ ] Daily loss limit blocks new entries
- [ ] Session end (21:00) closes positions
- [ ] Drawer retracts/expands smoothly

---

*Plan complete. Ready for review and execution method selection.*