# Ignite Desk — Live Readiness Checklist

**Version:** 1.0  
**Date:** 2026-11-13  
**Status:** DRAFT — Complete all items before live deployment

---

## Pre-Flight Checks

### Infrastructure
- [ ] **MCP Connected** — MT5 terminal reachable via MCP, `terminal_get_info` returns `connection.state = "synchronized"`
- [ ] **Kronos Healthy** — Forecast worker returns `{"ready": true, "model": "..."}`, latency < 5s
- [ ] **Database Migrated** — Schema up to date (`_migrate()` ran), `agent_events`, `agent_decisions`, `audit_log` tables exist
- [ ] **Config Valid** — `agent_config` row exists, all ceilings respected, `operating_mode = "autonomous"`, `execution_mode = "live"`
- [ ] **Kill Switch OFF** — `kill_switch = 0` in settings, verified via `/api/health` and `/api/health/readiness`

### Account & Risk
- [ ] **Account Funded** — Equity > 0, `margin_free > 0`, account type = "live" (not demo)
- [ ] **Margin Adequate** — Free margin > 2x max concurrent position margin requirement
- [ ] **Risk Limits Set** — `risk_pct` ≤ 2%, `daily_loss_limit_pct` ≤ 6%, `max_concurrent_positions` ≤ 10, `max_positions_per_symbol` ≤ 2, `portfolio_risk_cap_pct` ≤ 15%
- [ ] **Daily Loss NOT Breached** — `/api/health/readiness` shows `daily_loss.ok = true`, PnL > -daily_limit

### Positions & Reconciliation
- [ ] **Positions Within Limits** — Open positions < `max_concurrent_positions`, per-symbol < `max_positions_per_symbol`
- [ ] **Reconciliation Green** — `/api/health/readiness` shows `positions.ok = true`, `per_symbol_positions.ok = true`, no orphaned positions
- [ ] **Reconciliation Tested** — Manual reconciliation run via `ReconciliationService(rt).check()` returns all `synced`/`closed`/`adopted`, no `orphaned` without explanation

### Health & Readiness
- [ ] **Health Endpoint Green** — `GET /api/health` returns `"ok": true`
- [ ] **Readiness Endpoint Green** — `GET /api/health/readiness` returns `"ready": true`, all checks `ok: true`
- [ ] **Kronos Ready** — Forecast worker health `"ready": true`, model loaded
- [ ] **MCP Connected** — Terminal synchronized, trade_allowed = true
- [ ] **LLM Available** — At least one LLM provider returns `ready: true`

### Test Suite
- [ ] **Backend Tests Pass** — `pytest tests -q` → all tests pass (163+ tests)
- [ ] **Frontend Typecheck** — `npm run typecheck` passes
- [ ] **Frontend Build** — `npm run build` succeeds

---

## Promotion Verification

### Shadow → Demo
- [ ] Promote shadow → demo via `/api/mode/promote` with `confirm=true`
- [ ] Verify execution_mode = "demo" in config
- [ ] Verify audit log entry: `action = "mode_promoted", from = "shadow", to = "demo"`
- [ ] Verify orders NOT sent in demo mode (gateway validates execution_mode)

### Demo → Live
- [ ] Promote demo → live via `/api/mode/promote` with `confirm=true`, `account_number="<live_account>"`
- [ ] Verify execution_mode = "live" in config
- [ ] Verify audit log entry: `action = "mode_promoted", from = "demo", to = "live", account = "<live_account>"`
- [ ] Verify live order sent through gateway (shadow mode rejected, live mode accepted)

### Live → Shadow (Demotion)
- [ ] Demote live → shadow via `/api/mode/demote` with `confirm=true`
- [ ] Verify execution_mode = "shadow" in config
- [ ] Verify audit log entry: `action = "mode_demoted", from = "live", to = "shadow"`

---

## Rollback Plan

### Code Rollback
- [ ] **Git Tag** — Current commit tagged as `v1.0.0-live-ready`
- [ ] **Revert Procedure** — `git revert <commit-range>` or `git checkout <tag>` to revert to shadow-only state
- [ ] **Verification** — After rollback, verify `execution_mode = "shadow"` and no live orders pending

### Database Rollback
- [ ] **Additive Schema Only** — All migrations are additive (`_migrate()` only adds columns/tables)
- [ ] **Data Compatibility** — Previous version can read current DB schema (no breaking changes)
- [ ] **Position Data** — Agent positions preserved, can be reconciled after rollback

### Operational Rollback
- [ ] **Kill Switch Tested** — Engage kill switch via `/api/settings` → verify all entries blocked, closes still work
- [ ] **Order Cancellation** — Manual close via MT5 verified as backup
- [ ] **Communication Plan** — Slack/email template ready for stakeholder notification

---

## Sign-Off

| Role | Name | Signature | Date |
|------|------|-----------|------|
| Lead Engineer | | | |
| Risk Officer | | | |
| Operations Lead | | | |

---

**Document Location:** `docs/LIVE_READINESS.md`  
**Last Updated:** 2026-11-13  
**Next Review:** Before each live session