# Ignite Desk — Agentic Trading Platform Design

| | |
|---|---|
| **Status** | Implemented: slice 1 (foundation), slice 2 (agent loop), slice 3 (execution & supervision) |
| **Date** | 2026-11-13 |
| **Scope** | Local, single-operator, autonomous trading platform |
| **Supersedes** | `2026-11-13-agent-workbench-spec.md` §2 and §10 (LLM execution authority) |
| **Stack** | Python 3.11 / FastAPI, React 18 / Vite, Kronos forecast worker, MT5 via MCP |

## 1. Purpose

Ignite Desk is a local trading platform in which an LLM agent is the trader. The
agent observes the market, reasons over deterministic evidence, authors trades,
manages open positions, and explains itself. A deterministic execution gateway
and a position supervisor make the agent's actions safe, observable, and
replayable.

The platform is not a dashboard with a chat box, and it is not a rules engine
with an LLM narrator. The agent has real tools and real authority; the platform
guarantees that every action is valid, attributable, and recoverable.

### 1.1 Definition of done

One full autonomous cycle is observable end to end:

```
trigger → context pack → agent tool loop → structured decision
        → gateway validation → order → protected position
        → trail / scale / close → reconciled PnL → replayable audit
```

Every guard demonstrably blocks when its condition is true. No guard can fail
open. The operator can reconstruct any trade from persisted events alone.

### 1.2 Non-goals

- Multi-user tenancy, remote access, or cloud deployment.
- Replacing MT5 as the broker or implementing its own matching engine.
- Backtesting and historical simulation (separate future project).
- Portfolio optimisation across correlated instruments (risk caps only).

## 2. Operating model and authority

### 2.1 Modes

Three modes, persisted in `agent_config` and always visible in the UI:

| Mode | Agent may | Broker writes |
|---|---|---|
| `observe` | read tools, analysis, chat | none |
| `prepare` | analysis, drafts, evaluation | none |
| `autonomous` | full tool set, including execution | yes, through the gateway |

Mode is independent of `enabled`. `enabled` controls whether scheduled cycles
run; mode controls what the agent is permitted to do when it runs. An agent in
`prepare` mode may run cycles and produce drafts, but every send is rejected.

### 2.2 Execution authority

The agent is the trader. It chooses symbol, side, order type, lot size, stop
loss, take profit, and it may modify, scale, or close any position it owns.

The execution gateway **validates** every request and **never rewrites** it.
A valid request is sent exactly as the agent specified. An invalid request is
rejected with a typed reason that the agent must handle. There is no silent
clamping in the gateway.

Two exceptions are contract enforcement, not preference:

1. `lots` must conform to the broker's `volume_step`, `volume_min`, and
   `volume_max`. A non-conforming size is rejected, not rounded.
2. Prices must conform to `digits` and minimum stop distance. Non-conforming
   prices are rejected, not nudged.

### 2.3 Mandatory invariants

These always hold, in every mode and for every caller (agent, chat, REST):

- Kill switch blocks new entries and risk-increasing modifications. It never
  blocks a close or a risk-reducing modification; an operator must always be
  able to flatten.
- Daily loss stop blocks new entries; it never blocks exits.
- Portfolio open-risk cap and per-symbol position cap block new entries.
- Margin must be sufficient at the requested size.
- Market must be open and the symbol must be tradeable.
- Spread must be under the configured ceiling.
- News blackout blocks new entries within the configured window.
- Every order carries an idempotency key that is unique in the database.
- Every fill is reconciled against the broker before it is reported as done.
- A position without verified SL/TP is treated as `unprotected`, never as safe.
- Missing, stale, or unavailable data blocks the affected action.

A rejection is a first-class outcome. It is persisted, surfaced to the agent,
and shown in the UI with the reason.

## 3. Risk envelope

Defaults are configured in the UI and stored in `agent_config`. Values are
validated against an absolute ceiling that the UI cannot exceed.

| Setting | Value | Ceiling |
|---|---|---|
| `risk_pct` per trade | 0.02 | 0.03 |
| `max_risk_pct` (per-trade hard cap) | 0.02 | 0.03 |
| `daily_loss_limit_pct` | 0.06 | 0.10 |
| `max_concurrent_positions` | 10 | 15 |
| `max_positions_per_symbol` | 2 | 3 |
| `portfolio_risk_cap_pct` | 0.15 | 0.20 |

Consequences that must be implemented, not just documented:

- `RiskConfig.max_risk_pct` must be raised to at least `risk_pct`, otherwise
  `analysis.risk.plan()` rejects every plan (it currently caps at 0.010).
- Daily loss is measured against equity at the server-day open and includes
  realised plus floating PnL. It can trip intraday from open positions.
- Portfolio risk is the sum of per-position risk at entry. With 2% per trade,
  the 15% cap binds before the 10-position count cap when positions are
  full-size.
- If equity, `SymbolSpec`, or stop distance is unavailable, sizing fails and
  the trade is rejected. There is no default lot fallback.

## 4. Topology

**One trading process.** The API process hosts the runtime, scheduler, agent
orchestrator, execution gateway, and position supervisor. They share one
`Runtime`: one MCP session, one store, one event bus, one execution lock.

The Kronos forecast worker remains a separate process because it is stateless
and inference-bound.

Consequences:

- No cross-process double-trade race. `execution_lock` is the only lock needed.
- Tool calls execute in-process against warm caches.
- Per-symbol lanes allow concurrent analysis while supervision continues.
- One config, one kill switch, one PnL source.
- `backend/ignite/agent/worker.py` is removed. Its scheduler jobs move into
  `Runtime` and start with the application lifespan. A single entry point,
  `python -m backend.ignite`, starts the API and the trading loop together.
  There is no second Runtime owner and no separate worker process.

`app.py` exposes a single application factory. The module-level `app =
create_app()` is removed so settings and the runtime are constructed once.

### 4.1 Runtime graph

```
Settings ──► Runtime
              ├── MCPClient
              ├── Store (SQLite, WAL)
              ├── EventBus
              ├── ForecastClient
              ├── LLMClient (tool-calling)
              ├── ConfigService
              ├── Ledger (PnL, reconciliation)
              ├── AgentOrchestrator ──► ToolRegistry ──► ExecutionGateway
              ├── PositionSupervisor
              └── Scheduler (APScheduler)
```

## 5. Agent loop

### 5.1 Triggering

Cycles are triggered by any of:

- session open
- bar close for each configured timeframe
- interval fallback (`cycle_interval_min`)
- high-impact news event entering or leaving the blackout window
- price crossing an agent-registered level
- operator chat message
- manual "run cycle now"

Each trigger enters a per-symbol single-flight lane. A second trigger for a
symbol already running is coalesced, not queued twice. The global concurrency
limit is `max_concurrent_analyses`.

### 5.2 Context pack

Assembled deterministically before the model is called, then hashed:

- account: equity, balance, free margin, currency, demo/live, leverage
- open positions with lifecycle state and current risk
- daily PnL, remaining daily budget, remaining portfolio budget
- symbol spec and current quote/spread
- bars summary: last close, ATR, session, volatility regime
- Kronos forecast: p10 / p50 / p90, horizon, dispersion
- analysis result if one exists for the bar
- news: upcoming events, active blackout, recent releases
- knowledge cards selected by symbol and regime
- recent decisions and their outcomes for this symbol
- mode, kill switch, and config version

The context hash, provider, model, and prompt version are persisted with the
decision.

### 5.3 Tool calling

`LLMClient` gains an OpenAI-compatible tool-calling path:

- Native `tools` / `tool_calls` when the provider supports it.
- A strict JSON action envelope fallback when it does not.
- Provider chain, timeouts, and token budgets are preserved.
- Malformed tool arguments produce a typed error returned to the model, not a
  silent retry with different data.

The orchestrator runs a bounded loop:

| Budget | Default |
|---|---|
| max steps | 8 |
| wall clock | 90 s per symbol |
| max tool calls | 16 |
| max prompt tokens per step | provider limit minus reserve |
| cancellation | kill switch, mode change, shutdown |

If the loop exhausts its budget, the decision is `NO_TRADE` with reason
`budget_exhausted`. It never defaults to a trade.

### 5.4 Structured decision

The final model turn must produce the decision schema:

```json
{
  "symbol": "XAUUSD",
  "timeframe": "M15",
  "action": "LONG | SHORT | NO_TRADE | WAIT | MONITOR | CLOSE | MODIFY",
  "conviction": 0.0,
  "thesis": "one paragraph",
  "evidence": ["..."],
  "failed_conditions": ["..."],
  "entry": {"type": "market|limit", "price": 0.0},
  "risk": {"lots": 0.0, "sl": 0.0, "tp": 0.0},
  "expected_rr": 0.0,
  "invalidate_if": ["..."],
  "links": {"analysis_id": null, "draft_id": null, "decision_id": "..."}
}
```

A decision that fails schema validation is recorded as `INVALID` and produces
no order. Free-form narration is stored alongside it for the conversation.

### 5.5 Tool registry

Tools are typed, permission-scoped, and audited. Each has a JSON schema, a
permission (`read`, `prepare`, `execute`), a timeout, and a result schema.

| Tool | Permission | Purpose |
|---|---|---|
| `account.snapshot` | read | balances, margin, mode |
| `account.positions` | read | open positions, ownership |
| `market.quote` | read | bid/ask/spread |
| `market.bars` | read | OHLCV window |
| `market.spec` | read | `SymbolSpec` |
| `market.structure` | read | swings, levels, regime |
| `news.calendar` | read | events and blackout state |
| `news.headlines` | read | recent releases |
| `forecast.run` | prepare | Kronos forecast |
| `analysis.run` | prepare | deterministic analysis + draft |
| `risk.evaluate` | prepare | validate a hypothetical order |
| `draft.create` | prepare | time-limited draft |
| `draft.evaluate` | prepare | revalidate a draft against live state |
| `execution.place_order` | execute | send an order |
| `execution.modify_position` | execute | change SL/TP |
| `execution.close_position` | execute | close by ticket |
| `execution.scale` | execute | partial close or add |
| `position.list` | read | agent-owned positions |
| `position.history` | read | closed trades and PnL |
| `level.register` | prepare | register a price trigger |
| `chat.respond` | read | final narration |

Execution tools are only registered when mode is `autonomous` and the kill
switch is off. Registration is re-evaluated per cycle, so a mode change takes
effect immediately.

## 6. Execution gateway

`AgentExecutionGateway` is the single broker write path. All callers use it.

### 6.1 Pipeline

1. **Idempotency.** `client_order_id` is `decision_id:attempt`. A unique index
   rejects duplicates; a duplicate submit returns the original result.
2. **Kill switch and mode.** Reject with `KILL_SWITCH` or `MODE`.
3. **Symbol and market.** Symbol must be in the watchlist, the spec must be
   fresh (TTL 1 hour), and the market must be open.
4. **Spread.** Reject above `max_spread_points` for the symbol's spec.
5. **News.** Reject new entries inside the blackout window.
6. **Daily loss.** Reject new entries when realised plus floating loss exceeds
   `daily_loss_limit_pct` of day-open equity.
7. **Exposure.** Reject when the position count, per-symbol count, or portfolio
   risk cap would be exceeded.
8. **Margin.** Reject when free margin at the requested size is insufficient.
9. **Order validity.** Validate lots against step/min/max and prices against
   digits and `stops_level`. Reject, never adjust.
10. **Send.** Call the broker with the exact request.
11. **Resolve.** Identify the resulting position by deal/order ticket, never by
    "first new position on the symbol".
12. **Protect.** Assert the position carries the requested SL and TP within one
    `digits` unit. If not, retry `modify_position` once. If still unprotected,
    close the position and mark the decision `PROTECTION_FAILED`.
13. **Reconcile.** Persist the fill, update lifecycle state, compute realised
    risk and R, and emit events.

Retries are limited to explicit requote or price-changed retcodes, once, after
refreshing the quote. Every other retcode is a terminal rejection.

### 6.2 Idempotency and failure

- A send that times out is marked `UNKNOWN`, not `FAILED`. The reconciler
  resolves it against broker history before any retry is allowed.
- A partial fill is recorded with the filled volume; the remainder is cancelled
  explicitly.
- An order that cannot be matched to a position after the timeout is
  `UNRESOLVED` and blocks further entries on that symbol until reconciled.

## 7. Position supervisor

Runs on its own interval and after every execution event.

- Reconciles broker positions against `agent_positions` on startup and each
  cycle.
- Adopts positions with the `ignite ` comment prefix that are missing locally,
  and records a warning event.
- Marks positions missing from the broker as closed and pulls realised PnL and
  R from deal history.
- Never manages a position it cannot match to a symbol spec.
- Trails from `SymbolSpec`: distance in ATR, rounding to `digits`, and a hard
  minimum of `stops_level` points.
- Persists SL and volume changes before and after the broker call, and skips a
  modify when live state already matches. No repeated identical modification
  requests.
- Honours break-even and scale-out levels from config, and records MFE/MAE.
- Applies a maximum position age and an optional weekend flatten policy.
- Emits `position.opened`, `position.protected`, `position.trailed`,
  `position.scaled`, `position.closed`, `position.orphaned`,
  `position.unprotected`.

## 8. State and persistence

### 8.1 Config ownership

`agent_config` is the single source of truth:

```sql
CREATE TABLE agent_config (
  key TEXT PRIMARY KEY,
  version INTEGER NOT NULL,
  config_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

- `ConfigService` seeds the row from environment on first boot.
- Reads return an immutable `AgentConfig`.
- Writes are `dataclasses.replace` → Pydantic validation → ceiling check →
  version increment → persist → publish `config.changed`.
- Agent, supervisor, gateway, and routes all read the same resolved config.
  No component caches a stale copy across a version change.
- `enabled` and `mode` live in the same row and are read at cycle start.

### 8.2 Positions

`agent_positions` gains:

| Column | Purpose |
|---|---|
| `status` | `pending/open/protected/trailing/partial/closing/closed/orphaned/unprotected` |
| `decision_id` | link to the decision that opened it |
| `entry_deal` | broker deal ticket |
| `position_ticket` | broker position ticket |
| `initial_risk_usd` | risk at entry |
| `initial_sl` | original stop |
| `mfe`, `mae` | excursion tracking |
| `last_synced_at` | reconciliation freshness |
| `broker_snapshot_json` | last known broker state |

### 8.3 PnL

- `Runtime.realised_today()` reads broker deal history with a 30 s cache.
- `Runtime.daily_pnl()` = realised today + floating on open positions.
- `agent_status.daily_pnl` reads the ledger, never open position rows.
- Closed positions store realised PnL and R computed from the actual fill and
  stop, including partial exits.

### 8.4 Events and audit

```sql
CREATE TABLE agent_events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  id TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  kind TEXT NOT NULL,
  severity TEXT NOT NULL,
  symbol TEXT,
  decision_id TEXT,
  payload_json TEXT NOT NULL
);
CREATE INDEX idx_agent_events_decision ON agent_events (decision_id, seq);
CREATE INDEX idx_agent_events_created ON agent_events (created_at);
```

Every tool call, guard evaluation, rejection, order, fill, protection check,
reconcile, and lifecycle transition writes one row. Chat tool rows are projected
from this table, so fabricated traces are impossible.

### 8.5 Messages

`agent_messages` is paginated by `(created_at, id)` descending and reversed for
render. `expire_stale_drafts` runs on a 60 s scheduler job.

## 9. API contract

New and changed routes:

| Route | Purpose |
|---|---|
| `GET /api/agent/overview` | one snapshot: status, account, risk, positions, drafts, decisions, mode, kill switch, health |
| `GET /api/agent/events?decision_id=` | audit replay |
| `GET /api/agent/sessions` | list conversations |
| `POST /api/agent/sessions` | create conversation |
| `GET /api/agent/sessions/{id}/messages?before=` | keyset pagination |
| `POST /api/agent/chat` | agent turn, returns real tool trace |
| `PUT /api/agent/config` | validated config update |
| `POST /api/agent/mode` | mode change, audited |
| `POST /api/agent/positions/{ticket}/close` | gateway close |

`GET /api/agent/overview` returns:

```json
{
  "status": {
    "enabled": true,
    "mode": "autonomous",
    "kill_switch": false,
    "heartbeat": "...",
    "cycle": {"state": "idle|running", "symbol": "...", "step": "..."},
    "daily_pnl": 0.0,
    "daily_loss_limit_pct": 0.06
  },
  "account": {
    "equity": 0.0, "balance": 0.0, "profit": 0.0,
    "currency": "USD", "server": "...", "leverage": 0,
    "margin_free": 0.0, "mode": "demo|live"
  },
  "risk": {
    "open_risk_usd": 0.0, "open_risk_pct": 0.0,
    "cap_pct": 0.15, "daily_pnl": 0.0,
    "daily_loss_limit_pct": 0.06, "remaining": 0.0
  },
  "positions": [],
  "drafts": [],
  "decisions": [],
  "guardrails": {"kill_switch": false, "risk": {}, "mode": "autonomous"},
  "generated_at": "..."
}
```

The response shape is the TypeScript contract. `frontend/src/lib/contracts.ts`
is generated from the OpenAPI schema and checked in CI.

## 10. Frontend

The workbench follows `2026-11-13-agent-workbench-spec.md` §3–§7:

- Left: conversation list (new chat, recent, archived).
- Center: conversation with user, agent, real tool rows, and decision cards.
- Right: live context rail with mode, demo/live label, heartbeat, cycle state,
  equity, open risk, daily PnL, positions, drafts, and component health.
- Composer: Enter sends, Shift+Enter newline, retry, quick prompts, explicit
  error state.
- Mode and kill switch are always visible.

Tool rows render `agent_events`: name, args preview, latency, status, expandable
result. Decision cards render the structured decision, failed guards, and links.

SSE drives cycle and tool updates. Polling remains a fallback with a 15 s
interval. The sidebar layout bug is fixed by removing the fixed 56 px wrapper
and letting the grid own the viewport.

## 11. Security

- All mutating routes require a session token issued at startup and injected
  into the SPA. Token is required for order, close, config, and mode routes.
- CORS stays restricted to local origins.
- The bind host remains loopback by default; binding to a non-loopback address
  requires an explicit environment flag and logs a warning.
- Chat write intents require imperative phrasing. Questions, negations, and
  hypotheticals never produce a broker write.
- Secrets and raw broker payloads are not rendered in the conversation.

## 12. Failure semantics

| Condition | Behaviour |
|---|---|
| Kill switch unreachable | block writes |
| Config unreadable | block writes |
| PnL source unavailable | block new entries |
| Spec stale | block writes for that symbol |
| Broker timeout on send | `UNKNOWN`, reconcile before retry |
| SL/TP missing after fill | retry once, then close, mark failure |
| Position missing from store | adopt with warning |
| Position missing from broker | close locally, reconcile PnL |
| MCP session lost | reinitialize, block writes until healthy |
| LLM unavailable | decision `NO_TRADE`, template narration |
| Forecast worker down | block entries, allow exits |
| Event bus full | drop with counter, persist events independently |

## 13. Rollout

Execution mode is a stored, visible setting:

| Mode | Behaviour | Promotion |
|---|---|---|
| `shadow` | full agent loop, gateway validates, nothing sent | default |
| `demo` | orders sent to the demo account | manual, audited |
| `live` | orders sent to the live account | manual, audited, confirmation dialog |

Promotion is one recorded action with the account number shown. No automatic
promotion. Demotion to `shadow` is always available and takes effect
immediately.

## 14. Testing

| Suite | Covers |
|---|---|
| `test_guard_matrix.py` | every guard rejects and logs when its dependency is broken |
| `test_gateway.py` | idempotency, ticket binding, SL/TP assertion, requote-once, partial fill |
| `test_reconciliation.py` | broker-closed PnL/R, orphans, unknown orders |
| `test_agent_loop.py` | tool calling, budgets, malformed args, schema rejection |
| `test_config_service.py` | round-trip, validation, ceiling, hot reload |
| `test_concurrency.py` | parallel symbols, no duplicate orders, no lock errors |
| `test_contracts.py` | OpenAPI schema matches generated TS types |
| frontend `verify:ui` | workbench render, mode banner, tool rows, decision card |

Existing tests must continue to pass. The suite is run before every slice is
declared complete.

## 15. Implementation slices

1. **Foundation.** Config service, single process, real PnL ledger,
   `agent_events`, gateway skeleton, fix the P0 crashes (close arity, frozen
   config, overview contract, dangerous messages).
2. **Agent loop.** LLM tool calling, typed registry, orchestrator with lanes and
   budgets, real traces, structured decisions.
3. **Execution and supervision.** Guard chain, ticket binding, protection
   assertion, spec-driven trailing, reconciliation.
4. **Workbench.** Contract, components, SSE, layout, auth token.
5. **Verification and rollout.** Test suites, shadow/demo/live gates, live
   readiness checklist.

## 16. Migration and rollback

- Schema changes are additive; `_migrate()` adds columns and tables.
- Existing `agent_config` rows are backfilled with `version=1` and the current
  JSON.
- Existing positions are reconciled on first boot and marked `orphaned` if the
  broker disagrees.
- Rollback is a code revert plus leaving execution mode at `shadow`. The
  database remains readable by the previous version because all changes are
  additive.
