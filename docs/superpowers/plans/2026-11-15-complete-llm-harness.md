# Plan: Complete the LLM intelligence harness for Ignite Desk

## Global Constraints

- One execution path: drift, spread, margin, news-blackout, kill-switch guards apply whether triggered by chat or scheduler.
- Execution re-validates at send time: state, expiry, single-use token, kill switch, price drift, spread, open position on symbol, margin, news blackout, broker trade_check_market_order.
- Fail closed: no draft/token → no trade. Shadow mode → no send.
- Backend bound to 127.0.0.1; single process; SQLite WAL; `pytest tests -q` all pass.
- The LLM is the primary intelligent center: Kronos and MT5 MCP are tools accessed through one harness. `UnifiedChatAgent` (chat) and `AgentEngine`/`Orchestrator` (autonomous cycle) are one LLM-based harness — one tool registry, one permission gate, one execution path.

## Context

A prior implementation pass deleted the old deterministic router (`chat.py`, `desk_router.py`) and routed `AgentEngine` execution through `execute_draft_autonomous` instead of the `gateway.place` bypass. Two audit findings remain (two separate LLM loops, frontend auth token, redundant position await, bare key access) plus the core Goal 1 work: merging the two LLM loops into one.

## Tasks

### Task 1: Merge UnifiedChatAgent and AgentEngine into a single LLM intelligence loop

Create one LLM harness entry point that both chat messages and scheduler ticks route through. The same tool registry, permission gate, context budget, and execution path (`execute_draft_autonomous`) serve both modes. Delete or thin the now-redundant parallel loop so there is no second decision brain.

Files to touch:
- `backend/ignite/agent/chat_agent.py` — keep as the LLM-first conversational loop entry
- `backend/ignite/agent/engine.py` — route through the same harness as chat
- `backend/ignite/agent/orchestrator.py` — ensure tool selection matches the unified harness
- `backend/ignite/agent/tools.py` — shared tool registry already exists; confirm `permission_allowed` is the single gate
- `backend/ignite/api/routes/agent.py` — chat endpoint already calls `UnifiedChatAgent`; confirm no second router remains

Acceptance:
- One LLM invocation path for both chat and autonomous cycle
- Scheduler tick invokes the same harness as a user message
- No remaining `gateway.place` bypass in engine
- All 230 tests pass

### Task 2: Fix frontend auth token — remove client-side token or add backend verification

`frontend/src/lib/auth.ts` generates a sessionStorage token and `frontend/src/lib/api.ts` attaches `Authorization: Bearer <token>` to mutating requests, but `backend/ignite/api/deps.py` never verifies it. Remove the client-side token generation/header code (lean — deletes lines), or add real backend verification.

Files to touch:
- `frontend/src/lib/auth.ts` — remove token generation/storage
- `frontend/src/lib/api.ts` — remove `getAuthHeader` attachment on mutating requests
- `backend/ignite/api/deps.py` — confirm no verification is expected (or add it)

Acceptance:
- No client-side auth token that authorizes nothing
- If backend verification added, every mutating endpoint checks it
- Frontend typecheck (`npm run typecheck`) passes

### Task 3: Remove redundant second position await in execute_draft

`backend/ignite/services/execution.py:L314` calls `_await_position` again for up to 10 s after the position was already found in the reconcile await. Reuse the already-reconciled position instead of polling again.

Files to touch:
- `backend/ignite/services/execution.py` — reuse reconciled position

Acceptance:
- No second `_await_position` call after a position is already found
- Error-path tests pass

### Task 4: Fix position_manager.py bare key access

`backend/ignite/agent/position_manager.py` uses `row["features_json"]` bare key access that can KeyError if the column is missing. Use `row.get("features_json")` consistent with defensive style elsewhere.

Files to touch:
- `backend/ignite/agent/position_manager.py` — defensive key access

Acceptance:
- No bare key access that can KeyError on missing columns
- Existing tests pass
