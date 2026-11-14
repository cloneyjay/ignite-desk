# Ignite Desk Agent-First Console Specification

| | |
|---|---|
| **Status** | Active implementation specification |
| **Date** | 2026-11-12 |
| **Owner** | cloneyjay |
| **Scope** | Localhost, single operator, XAUUSD-focused MetaQuotes demo workflow |
| **Related specification** | [Ignite Desk PRD](./2026-11-12-ignite-desk-prd.md) |

## 1. Purpose

Ignite Desk will be an agent operating console for a discretionary trader. The agent
will observe market, account, risk, and news state; explain what it sees; prepare
analysis and draft orders; and request explicit human approval before execution.

The chart, watchlist, and history remain available, but they become supporting
evidence for the agent workflow rather than the primary navigation model.

## 2. Product promise

When the operator opens Ignite Desk, the first screen must answer:

1. Is the agent healthy and running?
2. What is the agent doing now?
3. What did it decide most recently?
4. What evidence and rules support that decision?
5. What risk is currently open?
6. Is there an action waiting for human approval?
7. What changed since the previous cycle?

The interface must make the safe action obvious and the unsafe action difficult.

## 3. Non-negotiable safety rules

These rules apply to all phases:

- The agent never sends an order directly.
- A human must explicitly approve every execution.
- The backend remains the source of truth for validation, risk, expiry,
  idempotency, blackout checks, and kill-switch enforcement.
- Chat text cannot bypass draft validation or invoke broker execution.
- Missing terminal, market, model, calendar, or risk data produces a visible
  blocked state, never a guessed value.
- Deterministic calculations remain deterministic and versioned.
- LLM output is commentary, prioritisation, and explanation only.
- Every agent run and decision is auditable.
- Live-account actions require the existing additional confirmation.

## 4. Terminology

| Term | Meaning |
|---|---|
| Observation cycle | A read-only agent pass over account, positions, symbols, bars, news, and risk |
| Decision | A structured conclusion such as `LONG`, `SHORT`, `NO TRADE`, `WAIT`, or `MONITOR` |
| Evidence | The numerical and system facts supporting a decision |
| Draft | A backend-created, time-limited, validated trade proposal |
| Approval request | A draft that is executable only after human confirmation |
| Run | An immutable agent skill invocation with provider, model, latency, inputs, and output |
| Blocked | A safe state where the requested operation cannot continue |

## 5. Target user experience

### 5.1 Default route

`/agent` becomes the default landing page. The current portfolio route remains
available at `/portfolio` or `/` during migration and is linked from navigation.

### 5.2 Agent console layout

Desktop layout:

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ Agent status · mode · terminal · model · kill switch                     │
├───────────────────────────────────────┬──────────────────────────────────┤
│ Activity and decision stream           │ Context                          │
│                                       │                                  │
│ Current cycle                         │ Equity / exposure                 │
│ Latest decision card                  │ Open positions                    │
│ Approval request                      │ Daily loss                        │
│ Recent agent runs                     │ Current symbols                   │
│                                       │ System health                     │
├───────────────────────────────────────┴──────────────────────────────────┤
│ Command input: Ask the agent to observe, analyse, explain, or prepare     │
└──────────────────────────────────────────────────────────────────────────┘
```

Responsive behavior:

- At tablet width, the context column moves below the activity stream.
- At mobile width, cards stack vertically and the command input stays visible.
- No essential safety state is hidden behind hover-only UI.
- The kill switch remains reachable without opening a secondary route.

### 5.3 Status header

The header displays:

- Agent state: `OFF`, `STARTING`, `RUNNING`, `PAUSED`, or `ERROR`
- Account mode: `DEMO` or `LIVE`
- Terminal connection state
- Kronos/model state
- Stream connection state
- Kill-switch state
- Last cycle and next cycle timestamps

Each state has a visible label, not only a color. Colors are supplementary.

### 5.4 Current cycle card

The current cycle card displays:

- Cycle state: `idle`, `observing`, `analysing`, `reviewing`, `awaiting_approval`,
  `executing`, `reconciling`, `completed`, or `blocked`
- Symbol and timeframe
- Current step and progress
- Start time and elapsed time
- Human-readable status message
- Block reason, if blocked
- Link to the relevant analysis or draft

### 5.5 Decision card

Every decision is rendered as structured data:

- Decision: `LONG`, `SHORT`, `NO TRADE`, `WAIT`, or `MONITOR`
- Symbol and timeframe
- Created time and freshness
- Signal version and risk version
- Probability, expected move, ATR, spread, and projected R:R where applicable
- Positive evidence
- Failed conditions and vetoes
- News/blackout status
- Risk impact
- Agent commentary
- Actions: `Open analysis`, `Prepare draft`, `View run`

Numbers shown in commentary must match authoritative analysis and draft values.

### 5.6 Approval request

An approval request is visually prioritised above ordinary activity. It displays:

- Side and symbol
- Lots
- Reference price
- Stop loss and take profit
- Risk in USD and percentage
- Worst-case loss
- Margin requirement
- Spread and price drift
- Draft expiry countdown
- Blackout and kill-switch state
- Validation checks

Actions:

- `Review`
- `Approve and execute`
- `Reject`
- `Ask agent`

`Approve and execute` always opens the existing confirmation dialog. It never
executes directly from a chat response or an activity card.

### 5.7 Activity stream

The stream is ordered newest-first and supports filtering by:

- All
- Decisions
- Analyses
- Risk
- News
- Executions
- System

Each item includes timestamp, category, severity, concise summary, and a link
to the full immutable run or domain object.

### 5.8 Command input

The command input supports natural language requests already routed by the backend:

- `analyse XAUUSD M15`
- `what is my risk right now`
- `why was the last setup rejected`
- `prepare a trade plan for XAUUSD`
- `show today's agent runs`

The UI must show:

- Submitted request
- Routing skill
- Confidence
- Running state
- Result
- Errors and recovery action

The input must reject empty requests and disable while submitting. Errors must
be explicit and preserve the failed request for retry.

## 6. Information architecture

### Primary navigation

1. Agent
2. Watchlist
3. Portfolio
4. History
5. News & calendar

### Supporting routes

- `/agent`: default operating console
- `/watchlist`: chart and symbol evidence
- `/portfolio`: account and position detail
- `/history`: closed-trade review
- `/news`: calendar, news, and blackout detail
- `/agent/runs/:id`: immutable run detail
- `/agent/settings`: agent configuration

### Deep links

Decision cards must deep-link to:

- Analysis drawer
- Draft detail
- Agent run detail
- Position detail where available

## 7. Data contracts

### 7.1 Agent overview

Add a consolidated read endpoint:

`GET /api/agent/overview`

Response:

```json
{
  "status": {
    "enabled": true,
    "state": "running",
    "last_cycle": "2026-11-12T20:00:00Z",
    "next_cycle": "2026-11-12T20:15:00Z",
    "decisions_today": 2,
    "executed_today": 0,
    "daily_pnl": 0,
    "daily_loss_limit": 0.03
  },
  "health": {
    "terminal": "connected",
    "kronos": "ready",
    "llm": "ready",
    "kill_switch": false
  },
  "account": {
    "equity": 2991.35,
    "open_pnl": 0,
    "open_risk_usd": 0,
    "open_risk_pct": 0,
    "risk_cap_pct": 0.02
  },
  "positions": [],
  "current_cycle": null,
  "approval": null,
  "latest_decision": null,
  "recent_runs": []
}
```

The endpoint may compose existing services internally, but must return explicit
nulls and states instead of silently omitting unavailable data.

### 7.2 Decision schema

```json
{
  "id": "decision-id",
  "created_at": "2026-11-12T20:00:00Z",
  "symbol": "XAUUSD",
  "timeframe": "M15",
  "decision": "NO TRADE",
  "status": "blocked",
  "reasons": ["inside blackout window"],
  "evidence": {
    "p_up": 0.51,
    "edge_atr": 0.12,
    "spread_points": 13,
    "signal_version": "signal.v1",
    "risk_version": "risk.v1"
  },
  "analysis_id": "analysis-id",
  "draft_id": null,
  "run_id": "run-id"
}
```

### 7.3 Agent runs

`GET /api/agent/runs` remains the list endpoint. The UI must preserve:

- Run id
- Skill
- Subject
- Provider
- Model
- Status
- Fallback state
- Latency
- Validation checks
- Narrative
- Error

The detail endpoint must expose ordered tool calls, arguments, truncated results,
and final response as required by the existing PRD.

## 8. Backend work

### Phase 1

- Add `/api/agent/overview`.
- Reuse existing status, account, health, positions, runs, and draft services.
- Add structured current-cycle and decision serialization.
- Ensure missing dependencies produce explicit blocked/error fields.
- Add tests for healthy, disabled, disconnected, and kill-switch states.

### Phase 2

- Persist observation cycles and decisions as immutable records.
- Emit event-stream events for cycle start, progress, decision, approval request,
  execution, reconciliation, and failure.
- Add idempotent approval-request retrieval.

### Phase 3

- Add a scheduler for read-only observation cycles.
- Ensure scheduler cannot call execution methods.
- Enforce session, daily loss, symbol, and concurrency configuration.
- Add recovery and retry policies with bounded timeouts.

## 9. Frontend work

### Phase 1

- Add Agent route and make it the default page.
- Add API types for overview, decisions, cycles, and runs.
- Implement `AgentConsole`.
- Implement `AgentStatusHeader`.
- Implement `CycleCard`.
- Implement `DecisionCard`.
- Implement `ApprovalCard` using existing draft confirmation flow.
- Implement `ActivityStream`.
- Replace placeholder `AgentChat` with a functional command input.
- Add loading, empty, offline, blocked, and error states.

### Phase 2

- Add run detail page.
- Add decision filters.
- Add live event updates.
- Add chart/analysis deep links.
- Add agent settings page.

### Phase 3

- Add approval queue interactions.
- Add post-trade supervision cards.
- Add desktop notifications only after the in-app workflow is reliable.

## 10. Design system rules

- Agent state must use both text and color.
- Gold indicates attention or primary action.
- Green indicates healthy/allowed/positive.
- Red indicates blocked, dangerous, or negative.
- Amber indicates warning or pending review.
- Blue is informational only.
- Cards use a consistent hierarchy: title, state, evidence, action.
- Avoid decorative gradients and excessive animation.
- Use monospace for prices, percentages, times, IDs, and risk values.
- Keep primary actions visible; do not hide approval behind hover.
- Preserve keyboard focus and visible focus rings.
- Minimum touch target is 36px for controls.

## 11. State and error behavior

Every major surface must support:

- Loading
- Ready
- Empty
- Stale
- Blocked
- Error
- Offline

Rules:

- Stale data must show its timestamp.
- Errors must identify the failed subsystem.
- A disabled action must explain why it is disabled.
- No component may render a success-shaped fallback for failed data.
- Retry actions must be scoped to the failed resource.

## 12. Security and execution boundaries

- Chat endpoint remains non-executing.
- Frontend controls are not security boundaries.
- Backend revalidates every draft at confirmation and execution.
- Kill switch blocks all execution paths.
- Draft TTL and price-drift checks remain mandatory.
- Tool arguments and results are truncated in UI, but preserved according to
  backend retention policy.
- Do not expose credentials, broker tokens, or provider secrets in the browser.

## 13. Testing requirements

### Backend

- Overview response contract tests.
- Agent state transition tests.
- Decision serialization tests.
- Missing dependency and kill-switch tests.
- Chat routing tests.
- Confirm/execute safety regression tests.

### Frontend

- Agent console renders all major states.
- Command submission, success, failure, and retry.
- Decision card links to analysis and run detail.
- Approval card never bypasses confirmation.
- Kill-switch state disables approval.
- Responsive layout tests at desktop, tablet, and mobile widths.

### Browser verification

The UI verification flow must confirm:

1. Agent is the default landing page.
2. Overview loads with visible status.
3. A command can be submitted.
4. A blocked decision is explained.
5. An approval request requires confirmation.
6. Existing watchlist, portfolio, history, and news pages still load.

## 14. Delivery sequence

1. Specification and data contracts
2. Agent overview endpoint
3. Agent route and console shell
4. Command input and run stream
5. Structured decision cards
6. Approval card integration
7. Event-stream updates
8. Scheduler and observation cycles
9. Run detail and configuration
10. Full browser and safety regression suite

Each phase must leave the application buildable and safe to use.

## 15. Definition of done

The agent-first migration is complete when:

- `/agent` is the default route.
- The first screen shows health, current cycle, latest decision, exposure, and
  pending approvals without navigating elsewhere.
- The command input works against the existing agent router.
- Decisions are structured, timestamped, explainable, and deep-linked.
- Draft approval still requires explicit human confirmation.
- No execution path is available through chat.
- Agent runs are inspectable and auditable.
- Offline, blocked, stale, and error states are explicit.
- Existing domain pages remain functional.
- Type checks, production build, backend tests, and browser verification pass.
