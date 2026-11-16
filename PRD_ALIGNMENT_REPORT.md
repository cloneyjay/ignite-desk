# PRD Alignment Report — Ignite Desk

**Date:** 2026-11-16
**Scope:** Full backend + frontend review against `PRD.md` (the reference doc for all repo changes).
**Method:** Read every key file in `backend/ignite/` and `frontend/src/`, cross-referenced against the PRD's 10 invariants, 6 goals, and the PONYTAIL-AUDIT.md findings 3–6.

---

## Executive Summary

The PRD establishes Ignite Desk as **"Claude Code for trading"** — the LLM is the trader, the harness bounds and observes it. The codebase has made major progress (unified execution path, deleted legacy deterministic router, single LLM decision path for the autonomous cycle), but **significant gaps remain** against the PRD:

| Area | Status | Key Issue |
|------|--------|-----------|
| Goal 1 — One intelligence loop | ❌ PARTIAL | `UnifiedChatAgent` does not use `LLMHarness`; two separate LLM loops |
| Invariant #3 — One execution path | ❌ PARTIAL | Position manager and gateway tools bypass draft/guard path |
| Invariant #4 — One permission gate | ❌ PARTIAL | Direct MCP/gateway calls skip `permission_allowed` |
| Goal 5 — Evaluation & earned autonomy | ❌ NOT IMPLEMENTED | No decision→outcome linkage, no baselines, no auto-promotion |
| Goal 6 — Harness patterns (memory/context/skills) | ❌ PARTIAL | Memory/tools exist but no capped index, no session extraction, no skills |
| Draft expiry (PONYTAIL finding #1) | ❌ STILL BROKEN | `expire_stale_drafts` receives integer TTL instead of ISO timestamp |
| Auth token (PONYTAIL finding #4) | ⚠️ UNCLEAR | Code appears clean but audit doc still lists it |
| Redundant position await (PONYTAIL #5) | ⚠️ MINOR | 10s wasted poll on error path |
| position_manager KeyError (PONYTAIL #6) | ⚠️ MINOR | Silently masks schema problems |
| Docs stale (Agents.md, PONYTAIL-AUDIT.md) | ❌ YES | Test count not synced, findings 3–6 still listed |
| Frontend typecheck/build | ❌ NOT RUN | `npm run typecheck`/`build` never executed |

---

## Detailed Findings

### 1. Goal 1 — One Intelligence Loop (NOT FULLY MET)

**PRD Requirement:** "`UnifiedChatAgent` (chat) and `AgentEngine`/`Orchestrator` (autonomous cycle) both run through `LLMHarness`. A user message and a scheduler tick both route through `LLMHarness`." (PRD, Goal 1, Success criteria #2)

**Current State — Misaligned:**

- **`Orchestrator`** (`backend/ignite/agent/orchestrator.py:89`) correctly uses `LLMHarness` (`llm_harness.py:70`) for the autonomous cycle.
- **`UnifiedChatAgent`** (`backend/ignite/agent/chat_agent.py:105`) is a **completely separate class** with its own `respond()` method (line 116), its own `_get_tools()` (line 160), its own `_execute_tool()` (line 283), and its own tool-calling loop. It does **not** delegate to `LLMHarness`.
- This means chat messages and scheduler ticks use **different LLM invocation loops** with potentially different context, tool sets, and behavior — exactly what PONYTAIL-AUDIT finding #3 flags.

**Impact:** The "single intelligence" goal is only half-met. As the codebase evolves, the two loops can diverge in context, tools, or behavior.

**Required Fix:** Merge `UnifiedChatAgent` into `Orchestrator`/`LLMHarness` so a user message and a scheduler tick invoke the identical harness with the identical tool set and context budget.

---

### 2. Invariant #3 — One Execution Path (NOT FULLY MET)

**PRD Requirement:** "Every order goes through `execute_draft_autonomous` (autonomous) or the confirm→token→`execute_draft` handshake (UI), then the gateway guards. Never call `gateway.place()` or MT5 order tools from agent/engine code directly." (PRD, Invariant #3)

**Current State — Misaligned:**

- `execute_draft_autonomous` (`backend/ignite/services/execution.py:379`) is correctly used by `AgentEngine.analyse_symbol()` (line 158) and by the `execution_place_order` tool (`tools.py:1480`). ✓
- **BUT** `PositionManager._apply_action()` (`backend/ignite/agent/position_manager.py:108`) calls broker tools **directly**:
  - `modify_position_sl_tp(self.rt.mcp, ...)` (line 115)
  - `close_position(self.rt.mcp, ...)` (line 118)
  These bypass the draft system, the token system, the guard chain, and `execute_draft_autonomous`.
- **BUT** `execution_modify_position` tool (`tools.py:1493`) calls `rt.gateway.modify(ticket, sl, tp)` directly — not through the draft path.
- **BUT** `execution_close_position` tool (`tools.py:1500`) calls `rt.gateway.close(ticket, reason)` directly — not through the draft path.

**Impact:** Position management (trail SL, close, scale) and gateway modification/closure are **second execution paths** outside the draft/guard system. This violates Invariant #3.

**Required Fix:** Route all position modifications and closures through the draft/execution path (or explicitly document them as exempt with bypass-immune guards).

---

### 3. Invariant #4 — One Permission Gate (NOT FULLY MET)

**PRD Requirement:** "Every tool call is gated by `permission_allowed` in `agent/tools.py`." (PRD, Invariant #4)

**Current State — Misaligned:**

- `ToolRegistry.get_available()` (`tools.py:1252`) correctly filters by `permission_allowed`. ✓
- **BUT** `PositionManager._apply_action()` (`position_manager.py:108-118`) calls `modify_position_sl_tp` and `close_position` directly via MCP — these do **not** go through `permission_allowed`.
- **BUT** `execution_modify_position` (`tools.py:1493-1498`) and `execution_close_position` (`tools.py:1500-1504`) call `rt.gateway.modify()` and `rt.gateway.close()` — it's unclear if these pass through `permission_allowed` (they're called as tools, so they should, but the underlying gateway calls may bypass it).

**Impact:** Some order-modifying operations can execute without permission-gate evaluation.

**Required Fix:** Ensure every call that modifies or closes a position passes through `permission_allowed`.

---

### 4. Goal 5 — Evaluation & Earned Autonomy (NOT IMPLEMENTED)

**PRD Requirement:** Goal 5 requires:
1. Journaled decisions linked to outcomes (R multiple, MAE/MFE), including no-trades with hypothetical outcomes.
2. Comparison against baselines: no-trade, always-follow-Kronos, random same-risk — after spread/slippage/swap.
3. Model version pinned and logged per decision; model/prompt/tool change resets evaluation to shadow.
4. Autonomy ladder: shadow → demo → live with pre-set thresholds; auto-demotion on drawdown or loss streak.
5. Compact feedback to LLM (recent decisions, per-regime stats, lessons from closed trades).

**Current State — Nothing implemented:**

- `insert_agent_decision` (`db.py:805`) records decisions with `attribution_json` (provider, model, tools used, etc.) — the logging infrastructure exists. ✓
- **No decision→outcome linkage:** No code links a decision to its trade outcome (R multiple, MAE/MFE).
- **No baseline comparison:** No code compares against no-trade, follow-Kronos, or random baselines.
- **No model reset logic:** Model version is logged but there's no rule that a model/prompt/tool change resets evaluation to shadow.
- **No auto-promotion/demotion:** `promote_mode` (`runtime.py:263`) and `demote_mode` (`runtime.py:298`) are manual API calls only. No thresholds, no auto-demotion on drawdown/loss streak.
- **No compact feedback to LLM:** `_recent_journal` (`orchestrator.py:288`) returns last 8 decisions but no per-regime stats or lessons from closed trades.

**Impact:** Goal 5 ("Prove profitability") is completely unimplemented. The desk cannot show whether the LLM trades profitably, and autonomy is not earned on measured stats.

**Required Fix:** Build the evaluation harness (decision→outcome linkage, baseline comparison), add auto-promotion/demotion thresholds, add model reset-on-change logic, and feed compact stats back to the LLM.

---

### 5. Goal 6 — Harness Patterns (PARTIALLY IMPLEMENTED)

**PRD Requirement:** Memory layers separate (instruction/auto/session), context as budget, skills lazy-loaded, bypass-immune rules.

**Current State — Misaligned:**

- **Memory tools exist** (`semantic_remember`, `semantic_recall`, `episodic_record`, `episodic_query`, `procedural_learn`, `procedural_recall`, `procedural_query`, `scratchpad_*`) in `tools.py` lines 915–1604. ✓
- **BUT no capped index for auto-memory:** No evidence of an index cap that silently truncates old entries (as described in the harness patterns skill).
- **BUT no two-step save invariant:** No "topic file then index" save pattern for auto-memory.
- **BUT no session extraction:** No background agent that extracts session memories at session end.
- **BUT no instruction memory layer:** No separation between human-curated instruction memory and agent-written auto-memory.
- **Context budget:** `LLMHarness` has `max_steps`, `max_tool_calls`, `deadline_s`. `_recent_journal` limits to 8 decisions. But no explicit truncation recovery pointers or context compression.
- **Skills:** No lazy-loaded skills system. The `strategy_*` tools are not skills in the harness-patterns sense.

**Impact:** Goal 6 (extensible harness on ponytail patterns) is only partially met. Memory/context/skills patterns from the agentic-harness-patterns skill are not fully realized.

**Required Fix:** Implement capped auto-memory index, two-step save, session extraction, instruction memory layer, and lazy-loaded skills.

---

### 6. PONYTAIL-AUDIT Finding #1 — Draft Expiry (STILL BROKEN)

**PONYTAIL-AUDIT:** "`_expire_stale_drafts` is the scheduled job that transitions stale drafts to `expired`. Problem: It passed `self.settings.draft_ttl_s` (integer seconds) where an ISO timestamp is required. SQLite `TEXT <= INTEGER` is always false, so zero drafts were ever expired."

**Current State — STILL BROKEN:**

- `runtime.py:257`: `self.store.expire_stale_drafts(self.settings.draft_ttl_s)` — passes `draft_ttl_s` (an integer seconds value from settings).
- `db.py:246-252`: `def expire_stale_drafts(self, now_iso: str)` — the parameter is named `now_iso` but receives an integer. The SQL does `expires_at <= ?` comparing ISO TEXT to INTEGER — always false in SQLite.

**Impact:** Stale drafts never transition to `expired`. `pending_drafts()` grows unboundedly.

**Required Fix:** Pass `utc_now()` (ISO timestamp) instead of `self.settings.draft_ttl_s` to `expire_stale_drafts`.

---

### 7. PONYTAIL-AUDIT Finding #4 — Frontend Auth Token (UNCLEAR STATUS)

**PONYTAIL-AUDIT:** Frontend `api.ts` attaches `Authorization: Bearer <token>`; `auth.ts` generates/stores the token. But `deps.py` never verifies it. Security theater.

**Current State:** `frontend/src/lib/api.ts` does **not** attach any Authorization header. No `auth.ts` file exists in `frontend/src/lib/`. The code appears clean, but `PONYTAIL-AUDIT.md` still lists this as open.

**Impact:** If the code is already fixed, the audit doc is stale. If not, there's a false sense of security.

**Required Fix:** Verify whether auth token code exists anywhere in the frontend. If removed, update `PONYTAIL-AUDIT.md`. If present, remove it or add backend verification.

---

### 8. PONYTAIL-AUDIT Finding #5 — Redundant Position Await (MINOR)

**PONYTAIL-AUDIT:** `execution.py:L314` — after a broker send error is reconciled, the code calls `extract_order_ticket` then `_await_position` again with 10s timeout. The position was already found in the reconcile await.

**Current State:** `execution.py:316`: `position = reconciled_position or _await_position(rt, symbol, before, timeout_s=10.0)`. If `reconciled_position` is None (no position found after error), it polls again for up to 10 seconds for no new information.

**Impact:** Up to 10s of wasted polling on the error path.

**Required Fix:** Reuse the already-reconciled position or skip the second await.

---

### 9. PONYTAIL-AUDIT Finding #6 — position_manager KeyError (MINOR)

**PONYTAIL-AUDIT:** `position_manager.py` uses `row["features"]` which can KeyError if `features_json` column is missing.

**Current State:** `position_manager.py:318-320`:
```python
features = row.get("features")
if not isinstance(features, dict):
    features = json.loads(row.get("features_json") or "{}")
```
This uses `.get()` with defaults — defensive. But it silently masks schema problems (missing column returns `{}` instead of surfacing the error).

**Impact:** Missing schema columns produce silent failures instead of clear signals.

**Required Fix:** Surface schema problems explicitly instead of silently defaulting.

---

### 10. Stale Docs (Agents.md, PONYTAIL-AUDIT.md)

**PRD Rule #50:** "Keep docs true. If behavior changes, update this PRD, `README.md` and `Agents.md` in the same change. Do not hardcode test counts."

**Current State — Misaligned:**

- `Agents.md:54`: "All 228 tests pass" — the handoff says test count should be 228, but this needs verification against the actual suite.
- `PONYTAIL-AUDIT.md:62-64`: Lists findings 3–6 as still needing work, but the "Verdict" section says findings 3–6 still need work — the doc hasn't been updated to reflect current state.
- The handoff summary confirms: "`Agents.md`, `PONYTAIL-AUDIT.md` findings 3–6 still stale/test count not synced to 228."

**Impact:** Agents working on the repo may be misled by stale documentation.

**Required Fix:** Update `Agents.md` and `PONYTAIL-AUDIT.md` to reflect current state, sync test count to 228, mark resolved findings as fixed.

---

### 11. Frontend Typecheck/Build Not Run

**PRD Rule #51:** "For frontend changes run `npm run typecheck` and `npm run build`."

**Current State:** The handoff confirms: "Frontend checks: `npm run typecheck` / `build` never run (out of scope this session)."

**Impact:** Unknown if frontend TypeScript compiles or if the production bundle builds.

**Required Fix:** Run `npm run typecheck` and `npm run build` in `frontend/`.

---

### 12. Decision.risk → Draft Flow (UNVERIFIED)

**PRD Requirement:** The `Decision` schema (`decision.py:27-33`) has `Risk` with `lots`, `sl`, `tp`. The LLM's draft should use these values.

**Current State:** `draft_create` (`tools.py:1442`) receives `side`, `lots`, `reference_price`, `sl`, `tp` from tool arguments. The LLM calls `draft_create` during its tool-calling loop. However:
- `AgentEngine.analyse_symbol()` (`engine.py:158`) calls `execute_draft_autonomous(self.rt, str(decision.links.draft_id))` — the draft must already exist.
- It's unclear whether the LLM consistently creates a draft matching its `Decision.risk` values before execution.
- `_validate_entry` (`engine.py:213`) checks that draft side matches decision action, but does **not** verify that draft lots/SL/TP match decision risk.

**Impact:** The LLM's stated risk (lots/SL/TP) may not match what gets executed if the draft was created with different values.

**Required Fix:** Add validation that `draft.lots`, `draft.sl`, `draft.tp` match `decision.risk.lots`, `decision.risk.sl`, `decision.risk.tp` before execution.

---

### 13. Tool Budget Exhaustion Wastes Cycles

**PRD Requirement:** Per-cycle budgets (`max_steps`, `max_tool_calls`, deadline) enforced. (PRD, Goal 3, Success criteria #4)

**Current State:** `LLMHarness.run()` (`llm_harness.py:86-142`) enforces `max_steps` and `max_tool_calls`. When exhausted, `Orchestrator.run_cycle()` returns NO_TRADE (`orchestrator.py:119-122`). This is safe but wastes the entire cycle.

**Impact:** No recovery path when budget is exhausted; the cycle is lost.

**Required Fix:** Consider partial-credit or early-exit strategies rather than total cycle loss.

---

### 14. `_expire_stale_drafts` Parameter Name Mismatch

**Current State:** `db.py:246`: parameter named `now_iso: str` but receives `self.settings.draft_ttl_s` (integer seconds). The name is misleading.

**Impact:** Confusing API; future maintainers may pass an ISO timestamp expecting it to work, but it won't.

**Required Fix:** Rename parameter to `ttl_seconds` or fix the caller to pass `utc_now()`.

---

## Complete Checklist of Remaining Work

### Must Do (blocking PRD alignment)

1. [ ] **Fix draft expiry** — Pass `utc_now()` (ISO timestamp) to `expire_stale_drafts` instead of `self.settings.draft_ttl_s` (`runtime.py:257`, `db.py:246`)
2. [ ] **Unify chat and autonomous loops** — Make `UnifiedChatAgent` use `LLMHarness` so there's one intelligence loop (`chat_agent.py`, `orchestrator.py`)
3. [ ] **Unify execution path** — Route position manager and gateway tool calls through `execute_draft_autonomous`/`execute_draft` (`position_manager.py`, `tools.py:1493-1504`)
4. [ ] **Implement Goal 5 evaluation** — Decision→outcome linkage, baseline comparison, model reset-on-change, auto-promotion/demotion
5. [ ] **Validate draft risk matches decision risk** — Add check that `draft.lots/sl/tp` == `decision.risk.lots/sl/tp` (`engine.py:_validate_entry`)
6. [ ] **Update stale docs** — `Agents.md`, `PONYTAIL-AUDIT.md`, sync test count to 228
7. [ ] **Run frontend checks** — `npm run typecheck` and `npm run build`

### Should Do

8. [ ] **Fix redundant position await** — Skip second `_await_position` when `reconciled_position` exists (`execution.py:316`)
9. [ ] **Fix position_manager silent schema masking** — Surface missing column errors explicitly (`position_manager.py:318-320`)
10. [ ] **Verify auth token status** — Confirm `auth.ts` is removed from frontend; update `PONYTAIL-AUDIT.md` if resolved
11. [ ] **Implement Goal 6 memory patterns** — Capped auto-memory index, two-step save, session extraction, instruction memory layer
12. [ ] **Add truncation recovery pointers** — Context compression with recovery pointers

### Nice to Have

13. [ ] **Add tool budget recovery** — Don't waste entire cycle on exhaustion
14. [ ] **Lazy-loaded skills system** — Skills per harness patterns

---

## Answer to Your Core Question

> "Regarding this agentic trading harness, can it help do the sole purpose of trading? if not what design direction should I take?"

**Yes, but only after Goal 5 is implemented.** The harness currently satisfies the safety and execution requirements (the LLM can trade within guards), but it **cannot prove profitability** — which the PRD defines as the sole purpose ("Success = profitable trading, measured"). Without evaluation against baselines, earned autonomy, and outcome linkage, the harness is a safe execution environment but not a proven trading system.

**Design direction:** Focus on Goal 5 first (evaluation harness → earned autonomy), then Goal 6 (memory/context/skills for compounding improvement), while keeping the existing guard structure intact. Do not add live execution until the evaluation harness demonstrates positive expectancy after costs vs. baselines.

---

## Files Referenced

| File | Key Lines | Relevance |
|------|-----------|-----------|
| `backend/ignite/agent/orchestrator.py` | 1-266 | Single decision brain for autonomous cycle; uses LLMHarness |
| `backend/ignite/agent/engine.py` | 1-320 | Cycle driver; `_validate_entry`, loss-streak guard, draft validation |
| `backend/ignite/agent/llm_harness.py` | 1-160 | Bounded LLM tool-calling loop |
| `backend/ignite/agent/decision.py` | 1-74 | Decision schema (Action, Entry, Risk, Links) |
| `backend/ignite/agent/tools.py` | 95-1679 | ToolRegistry, 21 tools, `permission_allowed` |
| `backend/ignite/agent/chat_agent.py` | 105-426 | Separate LLM loop (NOT using LLMHarness) |
| `backend/ignite/agent/position_manager.py` | 1-365 | Position lifecycle; direct MCP calls bypass draft path |
| `backend/ignite/services/execution.py` | 179-495 | `execute_draft`, `execute_draft_autonomous`, `create_draft` |
| `backend/ignite/services/runtime.py` | 79-331 | Runtime; `_expire_stale_drafts` (broken), `promote_mode`, `demote_mode` |
| `backend/ignite/store/db.py` | 246-252, 805-864 | `expire_stale_drafts` (broken), `insert_agent_decision`, `agent_decisions` |
| `frontend/src/lib/api.ts` | 1-264 | No auth header (finding #4 may be resolved) |
| `frontend/src/pages/AgentWorkbench.tsx` | 26-546 | Chat UI, autonomous rail |
| `Agents.md` | 1-55 | Stale docs; test count not synced |
| `PONYTAIL-AUDIT.md` | 1-68 | Findings 3-6 still listed as open |
| `PRD.md` | 1-143 | Reference document for all changes |