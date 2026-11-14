# Ignite Desk Agent Workbench Specification

| | |
|---|---|
| **Status** | Active implementation specification |
| **Scope** | Local, single-operator, agent-first trading workbench |
| **Primary route** | `/` and `/agent` |
| **Markets** | Configured watchlist |
| **Operating modes** | Observe, Prepare, Autonomous |

## 1. Product goal

Ignite Desk is an agent workbench, not a dashboard with a command field. The
operator should be able to hold an ongoing conversation with the agent, see
which tools it is using, inspect authoritative results, and decide whether the
agent may prepare or execute actions.

The interface must make the agent's work legible:

1. What did the operator ask?
2. What is the agent doing now?
3. Which tools and data did it use?
4. What facts were returned?
5. What decision did it make?
6. What action is proposed or executing?
7. Which guard blocked or allowed the action?
8. What happened after execution?

## 2. Operating modes

### Observe

Read-only account, market, calendar, risk, and analysis tools are available.
No drafts or orders may be created.

### Prepare

The agent may create deterministic analyses and time-limited drafts. Execution
requires the existing explicit confirmation flow.

### Autonomous

The worker may create, validate, execute, and supervise trades for the
configured watchlist. Every order must pass the shared execution gateway and
all deterministic guards. The LLM never receives a broker execution tool.

Enabling autonomous mode is an explicit action and must show the current
account mode, risk limits, session hours, news blackout policy, and kill-switch
state.

## 3. Workbench layout

```text
┌──────────────┬───────────────────────────────────┬─────────────────────┐
│ Conversations│ Agent conversation                 │ Live context        │
│              │                                   │                     │
│ New chat     │ User message                      │ Operating mode      │
│ Recent       │ Agent response                    │ Current cycle       │
│ Saved runs   │ Tool activity                     │ Account / risk      │
│              │ Tool result                       │ Open positions      │
│              │ Decision / draft card             │ Pending actions      │
│              │                                   │ Guardrails           │
│              ├───────────────────────────────────┤                     │
│              │ Composer + quick actions           │                     │
└──────────────┴───────────────────────────────────┴─────────────────────┘
```

The conversation remains the primary surface. Activity history is a secondary
view, not a wall above the composer.

## 4. Conversation contract

Every conversation has:

- Stable ID.
- Title.
- Created and updated timestamps.
- Archived state.
- Ordered messages.

Every message has:

- Stable ID.
- Role: `user`, `agent`, `tool`, or `system`.
- Text content.
- Timestamp.
- Optional tool name, arguments, result, status, and latency.
- Optional links to analysis, draft, order, position, or run IDs.

The composer must support:

- Enter to send.
- Shift+Enter for a newline.
- Retry failed messages.
- Quick prompts.
- Disabled/loading state.
- Explicit error state that preserves the failed request.

## 5. Tool activity

Tool activity is displayed as compact expandable rows:

```text
✓ account.get_snapshot       42 ms
✓ account.get_positions      18 ms
✓ market.get_bars            83 ms
✓ news.get_blackouts         31 ms
✓ risk.evaluate              12 ms
```

Tool rows show status, arguments, duration, and a safe result preview. Sensitive
credentials and raw broker payloads are never rendered into the conversation.

## 6. Decision and action cards

Decision cards are structured and authoritative:

- Symbol and timeframe.
- Decision: `LONG`, `SHORT`, `NO TRADE`, `WAIT`, or `MONITOR`.
- Probability and expected edge.
- Risk and projected R:R.
- Positive evidence.
- Failed conditions and vetoes.
- News and blackout state.
- Draft state and expiry.
- Execution state.
- Links to analysis, run, draft, order, and position.

Autonomous executions show:

- Why the action was allowed.
- Which guards passed.
- Broker response.
- Reconciliation result.
- Position ownership and supervision state.

## 7. Live context rail

The right rail shows:

- Observe / Prepare / Autonomous mode.
- Demo or Live account label.
- Agent and worker heartbeat.
- Current cycle state and progress.
- Equity, open risk, daily loss, and risk cap.
- Open positions.
- Pending drafts or approval requests.
- Terminal, MCP, Kronos, stream, and kill-switch status.

The context rail may collapse on tablet and move below the conversation on
mobile, but the mode and kill switch must remain accessible.

## 8. Backend architecture

The platform uses these boundaries:

- `AgentConversationService`: sessions and messages.
- `AgentOrchestrator`: state machine and tool sequence.
- `AgentToolRegistry`: typed tools and permissions.
- `AgentDecisionService`: structured decisions and evidence.
- `AgentExecutionGateway`: the only broker write path.
- `AgentPositionSupervisor`: reconciliation and lifecycle management.
- `AgentEventStore`: persistent event history and replay.
- `AgentNotificationService`: in-app and desktop alerts.

The existing analysis, draft, execution, runtime, and event services remain the
authoritative domain services. The workbench is an observable client of those
services, not a second trading implementation.

## 9. Required API

- `GET /api/agent/sessions`
- `POST /api/agent/sessions`
- `GET /api/agent/sessions/{id}/messages`
- `POST /api/agent/chat`
- `GET /api/agent/overview`
- `GET /api/events`

`POST /api/agent/chat` accepts `session_id` and returns the assistant message,
route, tool activity, structured output, and related domain IDs.

## 10. Safety requirements

- The LLM cannot call broker execution tools.
- Autonomous mode must be persisted and visible.
- Every order is revalidated against live state immediately before sending.
- Kill switch, daily loss, max trade risk, max positions, session, blackout,
  spread, drift, margin, terminal, expiry, and idempotency guards are mandatory.
- Missing or stale data blocks execution.
- Worker restart cannot duplicate a cycle or order.
- Every tool call, decision, order, failure, and notification is auditable.

## 11. Delivery phases

### Phase 1: Workbench foundation

Persistent sessions/messages, real conversation layout, tool activity rows,
structured response cards, and existing chat compatibility.

### Phase 2: Agent orchestration

Typed tool registry, streaming tool events, current-cycle state machine, and
decision/evidence serialization.

### Phase 3: Autonomous supervision

Persistent worker events, restart recovery, position reconciliation, alerts,
and full autonomous execution lifecycle.

### Phase 4: Verification

Mocked broker tests, safety regression tests, browser tests, recovery tests, and
live-account operational checklist.

## 12. Definition of done

The redesign is complete when an operator can hold a persistent conversation,
see the tools and evidence used by the agent, inspect a structured decision,
enable autonomous mode, observe every autonomous cycle and execution, recover
after a restart without duplication, and receive clear alerts for every
important unattended event.

