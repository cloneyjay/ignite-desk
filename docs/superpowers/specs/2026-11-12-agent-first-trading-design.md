# Agent-First Autonomous Trading Platform — Design Spec

**Date:** 2026-11-12  
**Status:** Approved for implementation  
**Related:** PRD `2026-11-12-ignite-desk-prd.md`, Decisions D-001..D-036

---

## 1. Overview

Transform Ignite Desk from a **human-in-the-loop analysis tool** into an **agent-first autonomous trading platform** where a background agent continuously analyses the watchlist, executes trades, and manages positions through their full lifecycle — with a global UI toggle to enable/disable autonomous mode.

### 1.1 Scope

| In Scope | Out of Scope |
|----------|--------------|
| Dedicated agent worker process with 30-min scheduler | Multi-user / multi-account |
| Global agent toggle in UI | Strategy marketplace / backtest UI |
| Full trade lifecycle (entry → SL/TP → trail → scale → close) | Options / futures / multi-leg |
| Session-open (03:00) + 30-min interval triggers | ML model training / fine-tuning |
| Reuse risk.v1 + daily loss limit | Portfolio optimisation / allocation |
| Agent chat interface for queries/status | Mobile app / push notifications |
| Collapsible sidebar (AnalysisDrawer) | Cross-asset correlation engine |

### 1.2 Success Criteria

1. Agent runs autonomously at 03:00 + every 30 min when enabled
2. Global toggle in UI enables/disables within 1 second
3. Agent analyses all watchlist symbols per cycle
4. Full trade lifecycle managed without human intervention (while enabled)
5. All decisions auditable in `agent_decisions` + `agent_positions`
6. Chat interface answers "what's my risk", "analyse XAUUSD", "daily brief"
7. Sidebar retracts to 60px icon strip on toggle
8. All existing human-in-the-loop flows remain functional when agent disabled

---

## 2. Architecture

### 2.1 Process Topology

```
┌─────────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│   API (FastAPI)     │     │  Agent Worker       │     │  Kronos Worker      │
│   :8000             │     │  (new process)      │     │  :8765              │
├─────────────────────┤     ├─────────────────────┤     ├─────────────────────┤
│ - REST + SSE        │     │ - APScheduler       │     │ - Torch CPU         │
│ - Human-in-the-loop │     │ - Cron 03:00 +      │     │ - Single-flight     │
│ - Chat endpoint     │     │   Interval 30min    │     │ - Model loaded once │
│ - Settings/Account  │     │ - AgentDecisionLoop │     │ - Forecast API      │
│ - Knowledge/skills  │     │ - PositionManager   │     └─────────────────────┘
└──────────┬──────────┘     └──────────┬──────────┘            │
           │                           │                         │
           │                    ┌────────▼────────┐             │
           │                    │   SQLite (WAL)  │             │
           │                    │  - analyses     │             │
           │                    │  - drafts/orders│             │
           │                    │  - agent_decisions          │
           │                    │  - agent_positions          │
           │                    │  - agent_config             │
           │                    │  - agent_runs               │
           │                    └─────────────────┘             │
           │                                    │
           ▼                                    ▼
    ┌─────────────────────┐     ┌─────────────────────────────┐
    │  MT5 MCP :22346     │     │  Frontend (Vite/React)      │
    │  - quotes, bars     │     │  - Portfolio / Watchlist    │
    │  - orders/positions │     │  - Collapsible AnalysisDrawer│
    │  - calendar/news    │     │  - AgentPanel (toggle+chat) │
    └─────────────────────┘     └─────────────────────────────┘
```

### 2.2 Data Flow (Agent Cycle)

```
┌──────────────────────────────────────────────────────────────────────┐
│                        AGENT CYCLE (every 30 min)                    │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  1. SCHEDULER TICK (03:00, 03:30, 04:00...)                         │
│        │                                                             │
│        ▼                                                             │
│  2. LOAD CONFIG & GUARDS                                            │
│     - agent_enabled flag (global toggle)                            │
│     - kill_switch (blocks all)                                       │
│     - daily_loss_limit (realised + open risk)                        │
│     - max_concurrent_positions (from risk.v1)                       │
│        │                                                             │
│        ▼                                                             │
│  3. FOR EACH WATCHLIST SYMBOL (parallel, max 3 concurrent)          │
│     a. Fetch bars (288 M15 / 512 H1)                                │
│     b. Run Analysis Graph:                                          │
│        bars → features (ATR, EMA, vol) → Kronos forecast (25 paths) │
│        → signal.v1 (p_up, edge_atr) → risk.v1 (size, SL, TP)       │
│        → draft (if signal != NONE)                                  │
│     c. SYNTHESIS:                                                    │
│        - Forecast: p_up, edge_atr, dispersion, horizon              │
│        - Fundamental: calendar high-impact, news bias               │
│        - Technical: trend (EMA), volatility regime, key levels      │
│        - Attribution: compare last forecast vs realised             │
│     d. DECISION:                                                     │
│        - If signal valid + draft executable + guards pass → execute │
│        - Record to agent_decisions (even if NO TRADE)               │
│        │                                                             │
│        ▼                                                             │
│  4. POSITION MANAGEMENT (runs every 60s, independent)               │
│     - For each agent-managed position:                              │
│       * Trail SL (ATR-based or structure-based)                     │
│       - Scale in (add to winner per risk.v1)                        │
│       - Scale out (partial TP at 1R, 2R, 3R)                        │
│       - Full close on: signal reversal, daily loss hit,            │
│         correlation breach, session end (21:00 UTC)                 │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. Components

### 3.1 Backend — New Modules

#### 3.1.1 `backend/ignite/agent/worker.py`
**Entrypoint** — runs as separate process `python -m backend.ignite.agent.worker`

```python
# Responsibilities:
# - APScheduler: cron(03:00) + interval(30min)
# - Signal handling (SIGTERM → graceful shutdown)
# - Single-flight lock (prevent overlapping cycles)
# - Logging: structured JSON to stdout + rotating file
# - Health endpoint: GET /health on :8766 (optional)
```

#### 3.1.2 `backend/ignite/agent/engine.py`
**Core Decision Engine** — pure functions, no I/O, fully testable

```python
# Public API:
class AgentEngine:
    def __init__(self, runtime: Runtime, config: AgentConfig):
        ...

    def run_cycle(self) -> CycleResult:
        """One full analysis cycle across all watchlist symbols."""
        ...

    def analyse_symbol(self, symbol: str, timeframe: str) -> SymbolDecision:
        """Run analysis graph + synthesis for one symbol."""
        ...

# Decision synthesis:
def synthesise_decision(
    forecast: ForecastResult,
    fundamental: FundamentalContext,
    technical: TechnicalContext,
    risk: RiskConfig,
    attribution: AttributionContext,
) -> Decision:
    """
    Returns: Decision { action: ENTER|MANAGE|SKIP, side, confidence, reasoning }
    """
```

#### 3.1.3 `backend/ignite/agent/position_manager.py`
**Position Lifecycle Manager** — runs every 60s independently

```python
class PositionManager:
    def __init__(self, runtime: Runtime, config: PositionManagerConfig):
        ...

    def manage_all(self) -> List[PositionAction]:
        """Iterate agent-managed positions, return actions to execute."""
        ...

    def trail_sl(self, pos: AgentPosition, atr: float) -> float | None:
        """Return new SL price or None."""
        ...

    def check_scale_in(self, pos: AgentPosition, atr: float) -> ScaleAction | None:
        """Add to winner if move > 1.5R and risk budget allows."""
        ...

    def check_scale_out(self, pos: AgentPosition, current_price: float) -> ScaleAction | None:
        """Partial TP at 1R, 2R, 3R per risk.v1."""
        ...

    def check_exit_conditions(self, pos: AgentPosition) -> ExitReason | None:
        """Signal reversal, daily loss, correlation, session end."""
        ...
```

#### 3.1.4 `backend/ignite/agent/synthesis.py`
**Decision Synthesis** — combines forecast, fundamental, technical, attribution

```python
def build_fundamental_context(rt: Runtime, symbol: str) -> FundamentalContext:
    """Calendar high-impact events + news bias for next 24h."""

def build_technical_context(rt: Runtime, symbol: str, timeframe: str) -> TechnicalContext:
    """Trend (EMA), volatility regime, key levels (prior day H/L, session H/L)."""

def build_attribution_context(rt: Runtime, analysis_id: str) -> AttributionContext:
    """Compare last cycle's forecast vs realised move."""

def synthesise(forecast, fundamental, technical, attribution, risk) -> Decision:
    """Weighted synthesis → action + confidence + reasoning."""
```

#### 3.1.5 `backend/ignite/agent/config.py`
**Agent Configuration** — loaded from env + DB

```python
@dataclass(frozen=True)
class AgentConfig:
    enabled: bool = False                    # global toggle
    symbols: tuple[str, ...] = ()            # empty = all watchlist
    timeframe: str = "M15"
    cycle_interval_min: int = 30
    session_open_hour: int = 3               # 03:00 UTC
    max_concurrent_analyses: int = 3
    position_check_interval_sec: int = 60
    max_concurrent_positions: int = 3        # from risk.v1
    daily_loss_limit_pct: float = 0.03       # 3% equity
    trail_sl_atr: float = 1.5
    scale_in_atr: float = 1.5
    scale_out_levels: tuple[float, ...] = (1.0, 2.0, 3.0)  # R multiples
    max_correlation: float = 0.7
    session_end_hour: int = 21               # 21:00 UTC flat
```

### 3.2 Database Schema (SQLite)

```sql
-- Agent configuration (single row, key = 'global')
CREATE TABLE IF NOT EXISTS agent_config (
    key       TEXT PRIMARY KEY,
    enabled   INTEGER NOT NULL DEFAULT 0,
    config_json TEXT NOT NULL,        -- JSON of AgentConfig
    updated_at TEXT NOT NULL
);

-- Every agent decision (audit trail)
CREATE TABLE IF NOT EXISTS agent_decisions (
    id              TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    timeframe       TEXT NOT NULL,
    analysis_id     TEXT,              -- FK to analyses
    signal_side     TEXT NOT NULL,     -- LONG|SHORT|NONE
    p_up            REAL,
    edge_atr        REAL,
    decision        TEXT NOT NULL,     -- ENTER|MANAGE|SKIP|ERROR
    confidence      REAL,
    reasoning       TEXT,
    executed        INTEGER NOT NULL DEFAULT 0,
    execution_error TEXT,
    draft_id        TEXT,
    attribution_json TEXT,             -- forecast vs realised
    fundamental_json TEXT,            -- calendar + news summary
    technical_json TEXT,              -- trend, regime, levels
    risk_json TEXT                    -- sizing, caps used
);

-- Agent-managed positions
CREATE TABLE IF NOT EXISTS agent_positions (
    ticket          TEXT PRIMARY KEY,  -- MT5 position ticket
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,     -- BUY|SELL
    entry_price     REAL NOT NULL,
    volume          REAL NOT NULL,
    sl              REAL,
    tp              REAL,
    opened_at       TEXT NOT NULL,
    managed_by_agent INTEGER NOT NULL DEFAULT 1,
    trail_sl        REAL,              -- current trailing SL
    scale_in_count  INTEGER DEFAULT 0,
    scale_out_count INTEGER DEFAULT 0,
    max_favourable_atr REAL,          -- max excursion in favour
    max_adverse_atr REAL,             -- max excursion against
    last_managed_at TEXT,
    closed_at       TEXT,
    close_reason    TEXT,              -- TP|SL|SIGNAL_REVERSAL|DAILY_LOSS|SESSION_END|MANUAL
    realised_pnl    REAL,
    r_multiple      REAL
);

-- Agent config overrides per symbol (optional)
CREATE TABLE IF NOT EXISTS agent_symbol_config (
    symbol       TEXT PRIMARY KEY,
    config_json  TEXT NOT NULL,       -- overrides AgentConfig fields
    enabled      INTEGER NOT NULL DEFAULT 1
);
```

### 3.3 API Routes (extend `backend/ignite/api/routes/agent.py`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/agent/status` | GET | `{ enabled, last_cycle, next_cycle, decisions_today, positions_open, daily_pnl, daily_loss_limit }` |
| `/agent/toggle` | POST | `{ enabled: true/false }` — flips global toggle |
| `/agent/chat` | POST | Natural language → skill routing (existing) |
| `/agent/decisions` | GET | Paginated `agent_decisions` with filters |
| `/agent/positions` | GET | Current agent-managed positions |
| `/agent/positions/{ticket}` | GET | Position detail + management log |
| `/agent/positions/{ticket}/close` | POST | Manual close of agent position |
| `/agent/config` | GET/PUT | Get/update `agent_config` |

### 3.4 Frontend Components

#### 3.4.1 `AgentPanel` (new)
**Location:** `frontend/src/components/AgentPanel.tsx`

```
┌─────────────────────────────────────────────────────────────┐
│  Agent          [● LIVE] [Toggle ON/OFF]                    │
├─────────────────────────────────────────────────────────────┤
│  Status:  LIVE · Next cycle: 03:30 UTC (in 12m)            │
│  Today:   12 decisions · 3 executed · 2 positions open     │
│  P&L:     +$247.50  |  Daily loss limit: -$90.00 (3%)      │
├─────────────────────────────────────────────────────────────┤
│  [Chat]  [Decisions]  [Positions]  [Settings]              │
└─────────────────────────────────────────────────────────────┘
```

#### 3.4.2 Collapsible AnalysisDrawer (modify existing)

**Current:** Fixed 540px slide-in from right  
**New:** Retractable to 60px icon strip

```
┌──────────────────┐     ┌─────────────────────────────────────┐
│ EXPANDED (540px) │ ──► │ RETRACTED (60px)                    │
├──────────────────┤     ├─────────────────────────────────────┤
│ Signal  LONG     │     │ ▸                                    │
│ Draft  0.01 lots │     │ ▸                                    │
│ Execute [▼]      │     │ ▸                                    │
│ AI Commentary    │     │ ▸                                    │
└──────────────────┘     └─────────────────────────────────────┘
        ▲                       ▲
        │                       │
   Click handle            Hover to preview
   or button                Click to expand
```

**Implementation:**
- State: `drawerWidth: 540 | 60` + `isRetracted: boolean`
- CSS: `transition: width 200ms ease`
- Hover on retracted → temporary preview (no layout shift)
- Persist preference in `localStorage`

#### 3.4.3 `AgentChat` (new)
**Location:** `frontend/src/components/AgentChat.tsx`

```
┌─────────────────────────────────────────────────────────────┐
│ Agent Chat                              [⌘K to focus]      │
├─────────────────────────────────────────────────────────────┤
│ Agent:  Analysis complete. XAUUSD M15 → NO TRADE.          │
│         p_up 0.44, edge -0.33 ATR.                         │
├─────────────────────────────────────────────────────────────┤
│ You:    analyse XAUUSD M5                                   │
│ Agent:  Starting analysis...                                │
│ Agent:  XAUUSD M5 → SHORT, p_up 0.28, edge -1.2 ATR.       │
│         Draft: 0.01 lots, SL 1985.50, TP 1945.20.           │
├─────────────────────────────────────────────────────────────┤
│ You:    daily brief                                         │
│ Agent:  Overnight: M15 LONG, M5 SHORT. 5 high-impact       │
│         events today (USD CPI, FOMC).                       │
├─────────────────────────────────────────────────────────────┤
│  [Input: "What's my risk?" / "close XAUUSD" / ...]         │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. UI Changes Detail

### 4.1 Collapsible AnalysisDrawer

**File:** `frontend/src/components/AnalysisDrawer.tsx`

**Changes:**
- Add `isRetracted` state + `toggleRetract()` + `handleHoverPreview()`
- Width: `w-[540px]` → `w-[60px]` when retracted
- Transition: `transition-all duration-200 ease-out`
- Retracted view: vertical icon strip (signal, draft, execute, AI)
- Hover on retracted → tooltip preview (no layout shift)
- Persist in `localStorage.setItem('drawerRetracted', 'true')`

**CSS Classes:**
```css
.drawer-expanded { width: 540px; }
.drawer-retracted { width: 60px; }
.drawer-transition { transition: width 200ms cubic-bezier(0.4, 0, 0.2, 1); }
.drawer-retracted:hover .preview-tooltip { opacity: 1; visibility: visible; }
```

### 4.2 AgentPanel (new component)

**File:** `frontend/src/components/AgentPanel.tsx`

**Props:**
```typescript
interface AgentPanelProps {
  onToggle: (enabled: boolean) => void;
  onChatOpen: () => void;
}
```

**Queries:** `useAgentStatus()`, `useAgentToggle()`, `useAgentChat()`

### 4.3 AgentChat

**File:** `frontend/src/components/AgentChat.tsx`

**Features:**
- Floating panel (bottom-right) or embedded in AgentPanel
- Keyboard shortcut `⌘K` / `Ctrl+K` to focus input
- Message history with syntax highlighting for numbers
- Quick actions: "analyse XAUUSD M15", "daily brief", "what's my risk", "close XAUUSD"
- Streaming response indicator

---

## 5. Configuration & Deployment

### 5.1 Environment Variables (add to `.env.example`)

```bash
# Agent Worker
IGNITE_AGENT_ENABLED=false
IGNITE_AGENT_SYMBOLS=                    # empty = all watchlist
IGNITE_AGENT_TIMEFRAME=M15
IGNITE_AGENT_CYCLE_INTERVAL_MIN=30
IGNITE_AGENT_SESSION_OPEN_HOUR=3
IGNITE_AGENT_MAX_CONCURRENT=3
IGNITE_AGENT_POSITION_CHECK_SEC=60
IGNITE_AGENT_DAILY_LOSS_PCT=0.03
IGNITE_AGENT_TRAIL_SL_ATR=1.5
IGNITE_AGENT_SCALE_IN_ATR=1.5
IGNITE_AGENT_SCALE_OUT_LEVELS=1.0,2.0,3.0
IGNITE_AGENT_MAX_CORRELATION=0.7
IGNITE_AGENT_SESSION_END_HOUR=21
```

### 5.2 Process Supervision

**Development:** Run manually
```bash
# Terminal 1: Kronos worker
python -m backend.ignite.forecasting.worker

# Terminal 2: API
python -m backend.ignite.api

# Terminal 3: Agent worker
python -m backend.ignite.agent.worker

# Terminal 4: Frontend
cd frontend && npm run dev
```

**Production (systemd):**
```ini
# /etc/systemd/system/ignite-agent.service
[Unit]
Description=Ignite Desk Agent Worker
After=network.target ignite-api.service
Requires=ignite-api.service

[Service]
Type=simple
User=ignite
WorkingDirectory=/opt/ignite-desk
EnvironmentFile=/opt/ignite-desk/.env
ExecStart=/opt/ignite-desk/.venv/bin/python -m backend.ignite.agent.worker
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

---

## 6. Testing Strategy

### 6.1 Unit Tests (new)

| Module | Tests |
|--------|-------|
| `agent/engine.py` | Synthesis logic, decision weights, guard ordering |
| `agent/position_manager.py` | Trail SL, scale in/out, exit conditions |
| `agent/synthesis.py` | Fundamental/technical/attribution weighting |
| `agent/config.py` | Env parsing, defaults, validation |
| `agent/worker.py` | Scheduler triggers, graceful shutdown |

### 6.2 Integration Tests

| Test | Description |
|------|-------------|
| `test_agent_cycle.py` | Full cycle: watchlist → analyses → decisions → positions |
| `test_position_manager.py` | Trail SL, scale in/out, exit on reversal |
| `test_agent_toggle.py` | API toggle enables/disables within 1s |
| `test_agent_chat.py` | Chat routes to skills, returns structured output |

### 6.3 UI Tests (verify-ui)

- Drawer retracts/expands on button click
- Drawer hover preview on retracted state
- Agent toggle updates UI within 500ms
- Chat sends message, receives structured response
- AgentPanel shows correct status/positions/P&L

---

## 7. Migration & Rollout

### 7.1 Database Migration
- Run on startup: `agent_config` + `agent_decisions` + `agent_positions` + `agent_symbol_config`
- No existing data migration needed (new tables)

### 7.2 Feature Flags
- `IGNITE_AGENT_ENABLED=false` by default
- Deploy agent worker alongside API
- Enable via UI toggle when ready

### 7.3 Rollback Plan
- Set `IGNITE_AGENT_ENABLED=false` → agent stops immediately
- All existing human-in-the-loop flows unaffected
- No schema changes to existing tables

---

## 8. Open Decisions (to resolve during implementation)

| ID | Question | Leaning |
|----|----------|---------|
| AD-001 | Trail SL: ATR-based (1.5×ATR) vs structure-based (swing low/high) | ATR-based for simplicity, structure for high-conviction |
| AD-002 | Scale-in: same size as original or reduced? | 50% of original size |
| AD-003 | Correlation check: pairwise Pearson on 20-bar returns? | Yes, 20-bar rolling |
| AD-004 | News bias weight in synthesis: 20% / 30% / 50%? | 30% fundamental, 40% technical, 30% forecast |
| AD-004 | Agent chat: WebSocket for streaming or polling? | Polling (TanStack Query) for simplicity |

---

## 9. Approval

**Design Review:** ✅ Approved by user  
**Spec Self-Review:** Completed (placeholder scan, consistency, scope, ambiguity)  
**Ready for:** `writing-plans` skill invocation

---

*Next step: Invoke `writing-plans` skill to generate detailed implementation plan.*