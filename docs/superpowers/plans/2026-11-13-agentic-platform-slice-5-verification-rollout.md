# Verification & Rollout — Slice 5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete verification suite, implement shadow/demo/live promotion gates, and create live readiness checklist — the final gate before live trading.

**Architecture:** This slice adds the final production gates: mode promotion UI/API with audit trail, a live readiness validator that checks all subsystems, and a comprehensive test runner. The existing test suites are already in place; this slice wires them into CI gates and adds the promotion mechanism.

**Tech Stack:** Python/FastAPI, React/Vite, existing test infrastructure (pytest, TanStack Query), GitHub Actions or local CI scripts.

**Spec:** `docs/superpowers/specs/2026-11-13-agentic-trading-platform-design.md` (sections 13, 14, 15.5)

## Global Constraints

- Execution modes: `shadow` (default, validates only) → `demo` (sends to demo account) → `live` (sends to live account, confirmation dialog)
- Promotion is manual, audited, recorded with account number; demotion to `shadow` always available
- All existing tests must pass (148 backend, frontend typecheck/build)
- No automatic promotion; operator explicitly confirms each step
- Rollback = code revert + mode = `shadow`; DB remains readable (additive schema only)

## Review Focus

1. **Promotion without confirmation** → UI must require explicit confirmation with account number display; API must reject promotion without confirmation token
2. **Mode demotion data loss** → Demotion to `shadow` must be instant and lossless; no orders canceled, no data deleted
3. **Live readiness false positive** → Validator must check ALL subsystems (MCP, Kronos, DB, config, risk, account); any failure = not ready
3. **Test suite gap** → All 7 backend suites + frontend verify must pass; CI must run all before merge
4. **Rollback integrity** → Code revert + mode=`shadow` must leave DB readable; no migrations to reverse

---

### Task 1: Live Readiness Validator

**Files:**
- Create: `backend/ignite/services/readiness.py`
- Modify: `backend/ignite/api/routes/system.py` (add `/api/health/readiness` endpoint)
- Test: `tests/test_readiness.py`

**Interfaces:**
- Consumes: `Runtime` (MCP, Kronos, DB, Config, Ledger, Account)
- Produces: `ReadinessReport` with `ready: bool`, `checks: dict[str, CheckResult]`, `summary: str`

- [ ] **Step 1: Write failing test**

```python
def test_readiness_all_green(rt):
    rt.config_service.update({"operating_mode": "autonomous", "execution_mode": "live"})
    report = ReadinessService(rt).check()
    assert report.ready is True
    assert all(c.ok for c in report.checks.values())

def test_readiness_kronos_down(rt):
    rt.forecast.health.return_value = {"ready": False}
    report = ReadinessService(rt).check()
    assert report.ready is False
    assert not report.checks["kronos"].ok
```

- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement `ReadinessService` in `backend/ignite/services/readiness.py`**
  - Checks: MCP reachable, terminal connected, trade_allowed, Kronos healthy, DB writable, config valid (ceilings), kill switch off, account equity > 0, margin_free > 0, risk config valid, daily loss not breached, positions within limits
  - Returns `ReadinessReport(ready, checks, summary)`
- [ ] **Step 4: Add `/api/health/readiness` endpoint in `system.py`**
- [ ] **Step 5: Run tests to verify pass**
- [ ] **Step 6: Commit**

```bash
git add backend/ignite/services/readiness.py backend/ignite/api/routes/system.py tests/test_readiness.py
git commit -m "feat(readiness): live readiness validator"
```

---

### Task 2: Mode Promotion API & Audit

**Files:**
- Modify: `backend/ignite/api/routes/system.py` (add `/api/mode/promote`, `/api/mode/demote`)
- Modify: `backend/ignite/services/runtime.py` (add `promote_mode`, `demote_mode`)
- Test: `tests/test_mode_promotion.py`

**Interfaces:**
- `POST /api/mode/promote { target: "demo"|"live", confirm: true, account_number: string }` → `{ ok: bool, mode: string }`
- `POST /api/mode/demote { confirm: true }` → `{ ok: bool, mode: "shadow" }`
- Audit log entry: `mode_promoted` / `mode_demoted` with `from`, `to`, `account`, `operator`, `timestamp`

- [ ] **Step 1: Write failing test**

```python
def test_promote_shadow_to_demo(rt):
    rt.config_service.update({"execution_mode": "shadow"})
    resp = client.post("/api/mode/promote", json={"target": "demo", "confirm": True, "account_number": "12345"})
    assert resp.json()["mode"] == "demo"
    assert rt.config().execution_mode == "demo"
    audit = rt.store.get_audit_log()[-1]
    assert audit["action"] == "mode_promoted"
    assert audit["payload"]["from"] == "shadow"

def test_promote_requires_confirmation(rt):
    resp = client.post("/api/mode/promote", json={"target": "live", "confirm": False})
    assert resp.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement promotion logic in `Runtime` and endpoints in `system.py`**
  - Validate: target mode is next step only (`shadow`→`demo`→`live`), `confirm=true`, account_number provided for `live`
  - Update `ConfigService`, publish `mode.promoted` event, audit log
  - Demotion: only to `shadow`, requires `confirm=true`
- [ ] **Step 4: Run tests to verify pass**
- [ ] **Step 5: Commit**

```bash
git add backend/ignite/services/runtime.py backend/ignite/api/routes/system.py tests/test_mode_promotion.py
git commit -m "feat(mode): promotion/demotion API with audit"
```

---

### Task 3: Mode Promotion UI

**Files:**
- Modify: `frontend/src/pages/AgentWorkbench.tsx` (add promotion controls to AutonomousRail)
- Modify: `frontend/src/lib/api.ts` (add `promoteMode`, `demoteMode`)
- Test: Manual verification

**Interfaces:**
- AutonomousRail shows current mode badge, "Promote to Demo" / "Promote to Live" buttons (disabled if not eligible)
- Click → confirmation modal with account number input (for live), `confirm` checkbox
- On success: toast, mode badge updates, rail refreshes

- [ ] **Step 1: Add `promoteMode`/`demoteMode` to `api.ts`**
- [ ] **Step 2: Add promotion controls to `AutonomousRail` in `AgentWorkbench.tsx`**
  - Show current mode, promote/demote buttons
  - Confirmation modal with account number (for live), confirm checkbox
  - Call API, show toast, refresh status
- [ ] **Step 2: Verify manually** — promote shadow→demo→live, demote live→shadow, verify badges, audit log
- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/pages/AgentWorkbench.tsx
git commit -m "feat(ui): mode promotion controls in workbench"
```

---

### Task 4: Test Suite CI Gate

**Files:**
- Create: `.github/workflows/ci.yml` (or local `scripts/ci.sh`)
- Test: All existing test suites

**Interfaces:**
- CI runs: `pytest tests -q`, `cd frontend && npm run typecheck && npm run build`
- All 148 backend tests + frontend typecheck/build must pass
- Runs on push to main, PR; blocks merge on failure

- [ ] **Step 1: Create CI workflow / script**
- [ ] **Step 2: Verify all suites pass locally**
- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add test suite gate for all slices"
```

---

### Task 5: Live Readiness Checklist (Documentation)

**Files:**
- Create: `docs/LIVE_READINESS.md`
- Test: Manual verification

**Interfaces:**
- Checklist document with: MCP connected, Kronos healthy, DB migrated, config valid, kill switch off, account funded, margin adequate, risk limits set, daily loss not breached, positions within limits, readiness endpoint green, test suite passing, promotion to demo tested, demotion tested, rollback plan documented

- [ ] **Step 1: Write checklist document**
- [ ] **Step 2: Verify manually against running system**
- [ ] **Step 3: Commit**

```bash
git add docs/LIVE_READINESS.md
git commit -m "docs: live readiness checklist"
```

---

### Task 6: Slice 5 Verification & Spec Update

- [ ] **Step 1: Run full backend suite** — `pytest tests -q` (all 148+ new tests pass)
- [ ] **Step 2: Run frontend checks** — `npm run typecheck && npm run build`
- [ ] **Step 3: Manual end-to-end** — promote shadow→demo→live, place order, demote, verify audit
- [ ] **Step 4: Update spec status** — "Implemented: slice 1 (foundation), slice 2 (agent loop), slice 3 (execution & supervision), slice 4 (workbench), slice 5 (verification & rollout)"
- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-11-13-agentic-trading-platform-design.md
git commit -m "docs: mark slice 5 (verification & rollout) implemented"
```