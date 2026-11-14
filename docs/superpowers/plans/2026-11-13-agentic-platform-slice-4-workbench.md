# Workbench — Slice 4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the agent-first workbench UI with real-time SSE updates, keyset pagination, session token auth, decision cards, tool rows from agent_events, and composer with proper UX.

**Architecture:** The workbench is a React SPA with three-panel layout (left: conversations, center: chat with tool rows/decision cards, right: live context rail). SSE drives real-time updates for cycle state, tool calls, and decisions. Keyset pagination loads messages on scroll. Session token auth protects mutating routes. The contract types are derived from the backend API and checked in CI.

**Tech Stack:** React 18, TanStack Query, Vite, TypeScript, Tailwind CSS, native SSE (EventSource).

**Spec:** `docs/superpowers/specs/2026-11-13-agentic-trading-platform-design.md` (sections 9, 10, 11)

## Global Constraints

- Three-panel layout: left (270px) conversations, center (flex) chat, right (300px) context rail
- SSE at `/api/events` drives cycle state, tool calls, decisions, fills
- Keyset pagination for messages: `before` cursor (`created_at|id`), limit 200, newest first
- Session token auth: all mutating routes require `Authorization: Bearer <token>` header
- Contract types in `frontend/src/lib/types.ts` mirror backend API exactly
- No derived business logic in types; validation is backend's job
- CORS restricted to local origins; bind host loopback by default
- Chat write intents require imperative phrasing; questions/negations never produce broker write
- Secrets and raw broker payloads never rendered in conversation

## Review Focus

1. **SSE connection loss** → UI must fall back to polling gracefully, show connection status
2. **Keyset pagination at conversation boundaries** → First load gets newest 200; scroll up loads older; never duplicate or skip messages
3. **Session token expiry** → Mutating requests return 401; UI prompts re-auth without losing composer state
4. **SSE event order** → Tool calls appear in order received; decision card appears after all tool calls for that decision
5. **Composer UX** — Enter sends, Shift+Enter newline, retry button on error, quick prompts, explicit error state from ApiError

---

### Task 1: SSE real-time integration

**Files:**
- Create: `frontend/src/hooks/useEvents.ts`
- Modify: `frontend/src/pages/AgentWorkbench.tsx`, `frontend/src/components/AgentPanel.tsx`
- Test: `frontend/tests/useEvents.test.tsx` (if test infra exists, else manual verification)

**Interfaces:**
- Consumes: `/api/events` SSE stream (event types: `analysis.progress`, `agent.toggled`, `agent.cycle.blocked`, `agent.cycle.completed`, `decision.final`, `tool.call`, `position.opened`, `position.protected`, `position.trailed`, `position.scaled`, `position.closed`, `position.orphaned`, `kill_switch`)
- Produces: `useEvents` hook returning `{ subscribe: () => void, unsubscribe: () => void, lastEvent: Event | null, connectionState: "connecting" | "connected" | "disconnected" }`

- [ ] **Step 1: Write failing test** (manual: open workbench, verify real-time updates without polling)
- [ ] **Step 2: Implement `useEvents` hook in `frontend/src/hooks/useEvents.ts`**
  - Use native `EventSource` with reconnection logic (exponential backoff, max 30s)
  - Expose `connectionState` enum: `"connecting" | "connected" | "disconnected" | "error"`
  - Parse SSE events by `event.type` field; call registered callbacks
  - Handle browser tab visibility: disconnect on hidden, reconnect on visible
- [ ] **Step 3: Integrate in `AgentWorkbench.tsx`**
  - Call `useEvents` on mount; subscribe to cycle/decision/tool events
  - Update `overview`/`status`/`positions` from SSE events instead of polling
  - Show connection indicator in header (green/amber/red dot)
- [ ] **Step 4: Verify manually** — open workbench, trigger agent cycle, verify real-time updates without refetch
- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useEvents.ts frontend/src/pages/AgentWorkbench.tsx
git commit -m "feat(ui): SSE real-time updates for cycle, decisions, tools"
```

---

### Task 2: Keyset pagination for messages

**Files:**
- Modify: `backend/ignite/api/routes/agent.py` (agent_session_messages endpoint), `backend/ignite/store/db.py` (agent_messages)
- Modify: `frontend/src/hooks/useAgent.ts` (useAgentMessages), `frontend/src/pages/AgentWorkbench.tsx` (MessageList virtualization)
- Test: `tests/test_hygiene.py::test_messages_return_newest_window` (already exists)

**Interfaces:**
- Backend: `agent_messages(session_id, limit=200, before: str | None = None)` → cursor `"created_at|id"`
- Frontend: `useAgentMessages(sessionId)` returns `{ messages, loadMore: () => Promise<void>, hasMore: boolean, isLoading: boolean }`

- [ ] **Step 1: Verify backend test passes** (already in `test_hygiene.py`)
- [ ] **Step 2: Update `agent_messages` in `backend/ignite/store/db.py`** (already done in slice 3 task 8)
- [ ] **Step 3: Update `agent_session_messages` endpoint in `backend/ignite/api/routes/agent.py`** to accept `before` cursor param
- [ ] **Step 4: Update `useAgentMessages` in `frontend/src/hooks/useAgent.ts`** to support `loadMore` with `before` cursor
- [ ] **Step 5: Add "Load older messages" button in `AgentWorkbench.tsx`** (above message list, appears when `hasMore`)
- [ ] **Step 6: Verify manually** — create 250+ messages, scroll up, verify seamless pagination
- [ ] **Step 7: Commit**

```bash
git add backend/ignite/api/routes/agent.py frontend/src/hooks/useAgent.ts frontend/src/pages/AgentWorkbench.tsx
git commit -m "feat(api): keyset pagination for agent messages"
```

---

### Task 3: Session token authentication

**Files:**
- Create: `frontend/src/lib/auth.ts`
- Modify: `frontend/src/lib/api.ts` (add auth header to mutating requests), `frontend/src/main.tsx` (initialize token)
- Test: Manual verification

**Interfaces:**
- Produces: `getAuthToken() -> string | null`, `setAuthToken(token: string) -> void`, `clearAuthToken() -> void`
- All mutating routes in `api.ts` include `Authorization: Bearer <token>` header

- [ ] **Step 1: Implement `auth.ts`** in `frontend/src/lib/auth.ts`
  - Token stored in memory (not localStorage) for session lifetime
  - `initializeAuth()` called on app startup: if no token, call `/api/auth/token` (new endpoint) or generate from session
  - For now: generate a random token on first load and persist in sessionStorage
- [ ] **Step 2: Add `/api/auth/token` endpoint** in `backend/ignite/api/routes/system.py` (or create auth router)
  - Returns `{ token: string, expires_at: string }` for current session
- [ ] **Step 3: Update `api.ts`** to inject `Authorization` header for POST/PUT/DELETE
- [ ] **Step 4: Add 401 handling** in `request()` — on 401, clear token, redirect to login (or re-initialize)
- [ ] **Step 5: Verify manually** — open workbench, send message, verify auth header present
- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/auth.ts frontend/src/lib/api.ts backend/ignite/api/routes/system.py frontend/src/main.tsx
git commit -m "feat(auth): session token for mutating routes"
```

---

### Task 4: Contract types and AgentOverview sync

**Files:**
- Modify: `frontend/src/lib/types.ts` (update `AgentOverview`, `AgentStatus`, `AgentPosition`, add `AgentRisk`, `AgentAccount`), `frontend/src/pages/AgentWorkbench.tsx` (ContextRail uses new types)
- Test: `tests/test_contracts.py` (already exists, verifies backend contract)

**Interfaces:**
- `AgentOverview.risk` now has `{ open_risk_usd, open_risk_pct, cap_pct, daily_pnl, daily_loss_limit_pct }`
- `AgentOverview.account` now has `{ equity, profit, server, currency, margin_free, mode }`
- `AgentStatus.daily_pnl` equals `AgentOverview.risk.daily_pnl`
- `AgentPosition` adds `status`, `max_favourable_atr`, `max_adverse_atr`

- [ ] **Step 1: Update types in `frontend/src/lib/types.ts`** to match backend contract from slice 3
- [ ] **Step 2: Update `ContextRail` in `AgentWorkbench.tsx`** to use new `risk` and `account` shapes
- [ ] **Step 3: Add `AgentPosition.status` badge** in position list (if rendered)
- [ ] **Step 4: Run `npm run typecheck`** — verify no type errors
- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/types.ts frontend/src/pages/AgentWorkbench.tsx
git commit -m "feat(types): sync contract types with slice 3 backend"
```

---

### Task 5: Tool rows and decision cards from agent_events

**Files:**
- Modify: `frontend/src/components/MessageBubble.tsx` (expand tool rows), `frontend/src/pages/AgentWorkbench.tsx` (decision card component)
- Create: `frontend/src/components/DecisionCard.tsx`, `frontend/src/components/ToolRow.tsx`
- Test: Manual verification

**Interfaces:**
- ToolRow: renders `name`, `args_preview`, `latency_ms`, `status`, expandable `result_preview`
- DecisionCard: renders `action`, `conviction`, `thesis`, `evidence`, `failed_conditions`, `entry`, `risk`, `expected_rr`, `invalidate_if`, `links`

- [ ] **Step 1: Create `ToolRow` component** in `frontend/src/components/ToolRow.tsx`
  - Collapsed: shows `name`, `status` badge, `latency_ms`
  - Expanded: shows `arguments` (pretty JSON), `result_preview`, `latency_ms`
  - Status colors: green (ok), red (failed), amber (pending)
- [ ] **Step 2: Create `DecisionCard` component** in `frontend/src/components/DecisionCard.tsx`
  - Header: action badge (LONG=green, SHORT=red, NO_TRADE=amber), conviction %
  - Body: thesis, evidence list, failed_conditions
  - Footer: entry (market/limit + price), risk (lots, SL, TP), expected RR, invalidate_if
  - Links: analysis_id, draft_id, decision_id as clickable refs
- [ ] **Step 3: Update `MessageBubble`** in `frontend/src/components/MessageBubble.tsx`
  - For `role="tool"`, render `ToolRow` instead of inline text
  - For `role="agent"` with decision, render `DecisionCard` below narrative
- [ ] **Step 5: Verify manually** — send chat message that triggers tool calls, verify tool rows expand; wait for decision, verify card renders
- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ToolRow.tsx frontend/src/components/DecisionCard.tsx frontend/src/components/MessageBubble.tsx frontend/src/pages/AgentWorkbench.tsx
git commit -m "feat(ui): tool rows and decision cards from agent_events"
```

---

### Task 6: Composer UX and error handling

**Files:**
- Modify: `frontend/src/pages/AgentWorkbench.tsx` (composer form), `frontend/src/components/AgentChat.tsx` (if exists)
- Test: Manual verification

**Interfaces:**
- Composer: Enter sends, Shift+Enter newline, disabled during pending, shows error inline
- Retry button on failed messages (re-sends same text)
- Quick prompts as buttons above composer
- Explicit error state: ApiError shows `code` and `message` in toast + inline

- [ ] **Step 1: Update composer in `AgentWorkbench.tsx`**
  - `<textarea>` with `onKeyDown`: Enter sends (unless Shift), Shift+Enter newline
  - Disable during `chat.isPending`
  - Show error inline below composer (from `chat.error`)
  - Retry button appears on error: re-sends same text
- [ ] **Step 2: Add quick prompts** (already in `QUICK_PROMPTS` array) as buttons above composer
- [ ] **Step 3: Error handling** — `ApiError` in `useAgentChat` mutation `onError` shows toast with `code` and `message`; also sets inline error for retry
- [ ] **Step 4: Verify manually** — send message, verify Enter sends, Shift+Enter newlines, error shows retry
- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/AgentWorkbench.tsx
git commit -m "feat(ui): composer UX — Enter/Shift+Enter, retry, quick prompts, errors"
```

---

### Task 7: Layout fix and polish

**Files:**
- Modify: `frontend/src/pages/AgentWorkbench.tsx` (grid layout), `frontend/src/App.tsx` (global styles)
- Test: Manual verification on different viewport sizes

**Interfaces:**
- Left rail: fixed 270px, no scroll wrapper
- Center: flex-1, min-w-0, overflow hidden
- Right rail: fixed 300px
- Sidebar layout bug fixed: removed fixed 56px wrapper, grid owns viewport

- [ ] **Step 1: Fix grid layout in `AgentWorkbench.tsx`**
  - `grid min-h-[calc(100vh-100px)] gap-4 xl:grid-cols-[270px_minmax(0,1fr)_300px]`
  - Remove any fixed-height wrappers on left/right rails
  - Ensure center panel has `min-w-0 flex-1 overflow-hidden`
- [ ] **Step 2: Verify responsive** — resize window, verify no horizontal scroll, rails stay fixed width
- [ ] **Step 3: Polish** — consistent spacing, badge tones, loading states, empty states
- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/AgentWorkbench.tsx frontend/src/App.tsx
git commit -m "feat(ui): workbench layout fix and polish"
```

---

### Task 8: Slice 4 verification

- [ ] **Step 1: Run backend suite**
  Run: `pytest tests -q`
  Expected: all pass (Slice 1-3 + new Slice 4 tests)

- [ ] **Step 2: Run frontend checks**
  Run: `npm run typecheck && npm run build` in `frontend/`
  Expected: both pass

- [ ] **Step 3: Manual workbench verification**
  - Open workbench, verify SSE connects (green dot)
  - Send chat message, verify tool rows appear in real-time
  - Wait for decision, verify decision card renders
  - Scroll up in chat, verify pagination loads older messages
  - Toggle autonomous mode, verify SSE updates rail
  - Trigger error, verify retry works
  - Resize window, verify layout holds

- [ ] **Step 4: Update spec status**
  Change design spec header to include `Implemented: slice 4 (workbench)`

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-11-13-agentic-trading-platform-design.md
git commit -m "docs: mark slice 4 (workbench) implemented"
```