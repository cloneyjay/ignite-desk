# Plan: Goal 5 Dashboard UI & Goal 6 Memory/Skills

## Context
Ignite Desk agentic trading harness. Goal 5 evaluation is largely implemented and promotion thresholds are gated. Remaining: surface evaluation results in the dashboard (baseline report + promotion eligibility) and implement Goal 6 memory/skills patterns partially.

Global Constraints:
- All changes must keep test suite green (`pytest tests -q` passes).
- No new LLM authority without permission gate; fail-closed.
- Do not modify gitignored docs (AGENTS.md, PONYTAIL-AUDIT.md) in this branch.
- Frontend changes must pass `npm run typecheck` and `npm run build`.
- Commit and push after each task.

## Tasks

### Task 1: Frontend evaluation dashboard panel
**Spec:** Add a panel to AgentWorkbench / AutonomousRail showing baseline comparison and promotion eligibility.
- Add API helpers `api.agentBaselineReport(symbol, lookbackDays)` and `api.agentPromotionEligibility()` in `frontend/src/lib/api.ts` (backend endpoints exist: GET /agent/evaluation/baseline, GET /agent/evaluation/promotion).
- Add TypeScript types for BaselineReport and PromotionEligibility in `frontend/src/lib/types.ts`.
- Create `frontend/src/components/EvaluationPanel.tsx`:
  - Fetches baseline report for XAUUSD (lookbackDays 30, configurable).
  - Shows agent vs no-trade / follow-Kronos / random sum R and disclaimer.
  - Fetches promotion eligibility.
  - Shows measured stats vs PROMOTION_THRESHOLDS_V1, each check pass/fail, overall eligible flag, target mode.
  - Uses existing UI primitives (Panel, Badge, MetricTile).
- Mount the panel in the right rail of AgentWorkbench (`frontend/src/pages/AgentWorkbench.tsx`) under AutonomousRail or as a new tab. Keep UI minimal.
- Tests: no frontend tests required, but ensure `npm run typecheck` and `npm run build` pass.

### Task 2: Goal 6 auto-memory skeleton (capped index + two-step save)
**Spec:** Implement minimal auto-memory layer per agentic-harness-patterns.
- Add `backend/ignite/agent/memory.py` with:
  - `MemoryStore` class backed by SQLite table `agent_memory` (id, key, content_json, created_at, access_count).
  - Capped index: max 200 entries, LRU eviction on insert.
  - Two-step save: `propose_memory(key, content)` → returns proposal id; `commit_memory(proposal_id)` persists and updates index; `reject_memory(proposal_id)` discards.
  - `get_memory(key)` returns content and increments access_count.
- Add store methods in `backend/ignite/store/db.py`:
  - `upsert_memory`, `list_memory`, `delete_memory`, `propose_memory` tables.
- Add a tool `memory_save` to `backend/ignite/agent/tools.py` exposing propose/commit via tool registry (tool requires prepare mode).
- Add unit tests in `tests/test_memory.py` covering capped index eviction, two-step save, and proposal rejection.
- Do NOT integrate into orchestrator yet; just provide the layer and tests.

### Task 3: Goal 6 skills discovery skeleton (budget-capped + lazy load)
**Spec:** Provide skills discovery with budget cap and lazy loading.
- Add `backend/ignite/agent/skills/registry.py`:
  - `Skill` dataclass (name, description, loader callable, enabled).
  - `SkillRegistry` with `discover()` that scans `backend/ignite/agent/skills/` for modules with a `skill_meta` dict, but enforces a discovery budget (max 50 modules scanned, 200ms wall time). Stop early and log audit.
  - `load(name)` lazy-loads the module on first use, caches the loaded module.
- Add two example skill stubs in `backend/ignite/agent/skills/` (e.g., `example_math.py` with skill_meta, and a simple `loader`).
- Add unit tests in `tests/test_skills.py` covering discovery budget cap, lazy load, and registry lookup.
- No orchestrator integration yet; just the registry and tests.

## Acceptance Criteria
- Task 1: Frontend typecheck/build passes, baseline and promotion data display correctly, no API errors.
- Task 2: `pytest tests/test_memory.py -q` passes, capped index enforced, two-step save works.
- Task 3: `pytest tests/test_skills.py -q` passes, discovery respects budget, lazy load works.
- Full suite `pytest tests -q` passes.
- Each task committed separately.
