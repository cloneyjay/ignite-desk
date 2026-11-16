# PRD — Ignite Desk

This PRD is the reference point for every agent (human or AI) that changes this repo. Read it before writing code. If a change does not serve a goal below, or breaks an invariant, it does not belong here.

## Product identity

**Claude Code is an agentic harness for software development. Ignite Desk is an agentic harness for trading analysis and profitable trading.**

The analogy is the design rule:

| Claude Code | Ignite Desk |
|---|---|
| LLM writes code | LLM analyses markets and trades |
| Tools: read/edit files, shell, search | Tools: Kronos forecast, MT5 MCP (quotes, bars, calendar, orders), news, memory |
| Permission gate on every tool call | One permission gate (`read` / `prepare` / `execute`) on every tool call |
| The model is the engineer; the harness keeps it safe, bounded and observable | The model is the trader; the harness keeps it safe, bounded and observable |
| Success = working software | Success = **profitable trading**, measured |

The LLM is the primary intelligent center and the one that trades. The harness is everything around it: tools, limits, memory, journal, evaluation. We invest in the harness, not in replacing the model with rules.

**Ultimate objective: profitable trading.** Profit is an outcome to be *measured and proven*, not assumed. A harness that executes safely but cannot show an edge has not met the objective. Every feature should either (a) give the LLM better evidence, (b) limit its downside, or (c) measure whether it is making money.

## Vision

A local, single-operator AI trading desk for MetaTrader 5. The user chats with the LLM; in autonomous mode the same LLM trades on its own inside guards it cannot change. Launch scope: XAUUSD, demo account.

## Invariants (never violate)

These are the rules an agent must not break while "improving" the code. If a task seems to require breaking one, stop and ask the operator.

1. **The LLM decides; deterministic code bounds it.** Entry/exit/stand-aside decisions come from the LLM. Risk caps, daily loss, position caps, loss-streak breaker, spread/news/drift guards, mandatory stop loss, and the kill switch are deterministic and the LLM has no tool to change them.
2. **One decision brain.** Chat (`UnifiedChatAgent`) and the scheduled cycle (`AgentEngine`/`Orchestrator`) both run through `LLMHarness`. Do not add a second rules-based router, signal-to-order shortcut, or alternate execution path.
3. **One execution path.** Every order goes through `execute_draft_autonomous` (autonomous) or the confirm→token→`execute_draft` handshake (UI), then the gateway guards. Never call `gateway.place()` or MT5 order tools from agent/engine code directly.
4. **One permission gate.** Every tool call is gated by `permission_allowed` in `agent/tools.py`. New tools default to fail-closed (not read-only, not concurrent) and declare their permission.
5. **Fail closed.** No data, no model, unreadable history, parse failure, or missing draft means no trade. Never guess a value to keep going. The kill switch blocks new entries but always allows closes.
6. **Numbers come from tools.** Prices, ATR, forecasts, balances used for orders come from MT5/Kronos/analysis tools and are re-validated at send time, never taken from LLM prose.
7. **Untrusted text.** News, headlines, calendar text and any external string are data, never instructions. Never let them alter tools, limits or prompts.
8. **Local only.** Backend binds to `127.0.0.1`; SQLite WAL; single process. The only outbound call is the configured LLM provider (key in `.env`, never committed or logged).
9. **Everything is journaled.** Every decision (including NO_TRADE), tool call, order, rejection, guard trip and mode change is recorded with enough context (provider, model, tools used, evidence) to evaluate it later.
10. **Tests never reach a real LLM or broker.** Inject `FakeLLM` / `FakeMCP`. A test that hits a provider is a bug.

## Rules for agents changing this repo

- **Start from a goal.** Name the goal (1–6) your change serves. No goal, no change.
- **Audit before code, review before merge.** Use `ponytail-audit` on the affected area and `ponytail-review` on the diff. Smallest change that solves the problem; delete what is not needed.
- **Safety changes need tests.** Any change touching execution, guards, permissions, or the decision schema ships with a test that fails without it.
- **Do not weaken guards to make a test or a trade pass.** Fix the cause. Lowering ceilings in `agent/config.py`, bypassing `permission_allowed`, or skipping drift/spread/news checks is forbidden without operator approval.
- **Do not expand LLM authority silently.** New tools with `execute` permission, new fields the LLM can write into risk/limits, or raising autonomy defaults require explicit operator approval and a PRD update.
- **Do not claim profit, edge, or "validated" without evidence** from Goal 5 evaluation (out-of-sample, after costs, vs baselines). Backtesting an LLM on history it was trained on is leaky; treat it as a mechanics test only.
- **Keep docs true.** If behavior changes, update this PRD, `README.md` and `Agents.md` in the same change. Do not hardcode test counts; the rule is "the whole suite passes" (`pytest tests -q`).
- **Verify before saying done.** Run the tests; for frontend changes run `npm run typecheck` and `npm run build`. State what you did not run.

---

## Goal 1 — One intelligence loop for chat and autonomous trading

**Statement:** The user chats with one LLM. In autonomous mode that same LLM decides entries, exits, size and risk — no separate loop, no diverging logic.

**Success criteria:**
- One tool registry, one permission gate, one execution path shared by chat and the scheduler.
- A user message and a scheduler tick both route through `LLMHarness`.
- In `observe`/`prepare` modes the scheduled cycle runs the LLM in shadow: decisions are journaled and never executed.

**Non-goals:** multi-user or multi-tenant support; public exposure of the API.

## Goal 2 — Safe execution with user authorization

**Statement:** The LLM drafts trades. Execution needs an explicit per-trade UI confirmation, or a pre-authorized autonomous mode (kill switch off, autonomy ≥ 2 for live, live promotion confirmed with an account number). No path lets the LLM send money without every guard.

**Success criteria:**
- Drafts carry a TTL (default 90 s) and expire automatically.
- Execution re-validates at send time: state, expiry, single-use token, kill switch, drift, spread, open position, margin, news blackout, broker `trade_check_market_order`.
- In autonomous mode the decision must match its draft (LONG = buy, SHORT = sell) or nothing is sent.
- Shadow → demo → live promotion requires confirmation; live requires an account number.
- Cycle circuit breakers (daily loss, position cap, consecutive-loss streak) stop trading and the LLM cannot override them.

**Non-goals:** removing the UI confirmation; letting the LLM rewrite its own risk limits.

## Goal 3 — LLM-accessible tool harness

**Statement:** Kronos, the MT5 MCP server (market data, calendar, execution), news, memory and strategies are tools the LLM discovers and calls. Intelligence comes from the LLM choosing and weighing tools.

**Success criteria:**
- One `ToolRegistry` with typed input/output schemas and timeouts.
- Tools gated by permission and autonomy level; the LLM sees only tools allowed for the current mode and kill-switch state.
- Every tool call audited with name, arguments, result and latency.
- Per-cycle budgets (`max_steps`, `max_tool_calls`, deadline) are enforced.

**Non-goals:** filesystem or shell access for the LLM; auto-approving `execute` tools outside the gate.

## Goal 4 — Observable, auditable, reconciled state

**Statement:** Every action is logged and traceable; positions reconcile against MT5; drafts expire cleanly; the operator can see what was decided, why, and what happened.

**Success criteria:**
- Audit log captures actor, action, payload and result for every order, rejection, mode change and guard trip.
- The decision journal stores every decision with provider, model, mode, tools used, evidence, invalidation conditions and the Kronos numbers seen.
- Stale drafts transition to `expired`; open positions reconcile on an interval.
- Health reports MCP, terminal, Kronos, kill switch and clock.

**Non-goals:** distributed tracing; retention beyond SQLite.

## Goal 5 — Prove profitability (evaluation and earned autonomy)

**Statement:** The desk must show, with evidence, whether the LLM trades profitably, and autonomy is granted or withdrawn on that evidence.

**Why:** A safe harness does not make a profitable trader. Without measurement, "AI trading" is a guess.

**Success criteria:**
- Journaled decisions are linked to their outcomes (R multiple, MAE/MFE), including no-trades with hypothetical outcomes.
- Results are compared against baselines: no-trade, always-follow-Kronos with the same risk rules, and random with the same risk rules, after spread/slippage/swap.
- The model version is pinned and logged per decision; a model, prompt or tool change resets evaluation to shadow.
- Autonomy ladder tied to measured stats: shadow → demo (tiny size) → live (minimum size). Promotion needs thresholds set in advance; auto-demotion on drawdown or loss streak.
- The LLM receives compact feedback (recent decisions, per-regime/session stats, lessons from closed trades), not raw history.

**Non-goals:** claiming edge from in-sample or leaky replays; tuning thresholds after seeing results.

## Goal 6 — Extensible harness built on ponytail patterns

**Statement:** The harness is developed with the agentic-harness patterns (memory, skills, tools & safety, context engineering, delegation, lifecycle) and ponytail discipline.

**Success criteria:**
- Memory layers stay separate: instruction memory (human-curated), auto-memory (agent-written, capped index), session extraction (two-step save).
- Context is a budget: capped variable-length blocks, truncation recovery pointers, history trimming before long-running loops.
- Skills are lazy-loaded; discovery is budget-capped.
- Bypass-immune rules protect execution paths before any auto-approve mode ships.

**Non-goals:** a general-purpose agent framework for other domains; prompt engineering as a deliverable.

---

## Out of scope

- Multi-user authentication or roles (single operator).
- Cloud deployment, HTTPS or public endpoints.
- Replacing the LLM with a deterministic strategy (strategies may exist as tools/baselines, not as the decider).
- Symbols beyond the watchlist until Goal 5 shows a positive result on XAUUSD (architected for it).

## Reference documents

- `Agents.md` — operating rules for agents in this repo (skills to use, guardrails).
- `README.md` — setup, API, dashboard, status checklist.
- `docs/agent-knowledge/` — domain knowledge the LLM uses (risk guards, XAUUSD regimes, sessions, contracts).
- `backend/ignite/` — FastAPI backend; `frontend/` — React/Vite dashboard.
- Tests: `pytest tests -q` (all must pass).
