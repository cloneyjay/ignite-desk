# Plan: unify execution under one guard set (audit finding 2)

## Context
PONYTAIL-AUDIT.md finding 2 (Must fix): execution and risk rules live in two
places and disagree. `services/execution.py` (`evaluate_draft` +
`execute_draft_autonomous`) guards the UI/draft path; `services/gateway.py`
(`validate`) + `agent/engine.py` (`_analyse_symbol_orchestrator` →
`gateway.place`) guard the autonomous cycle with a different set that skips
draft state, expiry, single-use token, and price-drift-versus-reference. The
autonomous path executes without the draft/token layering the UI path requires.

## Global constraints (from PRD/agents.md)
- One execution path: drift, spread, margin, news-blackout, kill-switch guards
  apply whether triggered by chat or the scheduler.
- Execution re-validates at send time: state, expiry, single-use token, kill
  switch, price drift, spread, open position on symbol, margin, news blackout,
  broker trade_check_market_order.
- Fail closed: no draft/token → no trade. Shadow mode → no send.
- Backend bound to 127.0.0.1; single process; SQLite WAL; all 224 tests must
  keep passing.

## Tasks
1. Add `create_draft` to `services/execution.py` (fixes the latent missing
   function referenced by `agent/tools.py` `_draft_create`; centralises draft
   creation behind the shared guard set).
2. Route `AgentEngine._analyse_symbol_orchestrator` execution through
   `execute_draft_autonomous` on `decision.links.draft_id` (shadow-gated,
   fail-closed when no draft), replacing the direct `gateway.place` bypass.
3. Add tests covering: shadow mode sends nothing; a valid draft executes via
   the shared guard set; kill switch blocks autonomous execution; no draft → no
   send; `create_draft` persists and audits a draft.
4. Run ponytail-review on the diff; run `pytest tests -q` (224 must pass).

## Rulings
(none yet)
