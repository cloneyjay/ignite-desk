# Agent Hernes Harness — Full Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the complete Agent Hernes Harness — a cognitive trading agent with planning, reflection, memory, market intelligence, dynamic risk, execution quality, autonomy graduation, explainability, and continuous learning.

**Architecture:** Modular agent architecture with separate modules for reasoning, memory, intelligence, policy, learning, and communication. Each module has a single responsibility and communicates through well-defined interfaces. The orchestrator coordinates the bounded loop.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, SQLite, TanStack Query, React, Tailwind CSS, httpx, numpy, pandas, scikit-learn, hmmlearn (for regime detection), aiohttp (async HTTP).

**Spec:** `founders/agent-hernes.md` (the Hernes vision document)

## Global Constraints

- All broker writes go through `AgentExecutionGateway` (Slice 1 Task 4)
- Config from `ConfigService` only; ceilings enforced (Slice 1 Task 2)
- PnL & guards from `Ledger`; fail-closed (Slice 1 Task 3)
- Kill switch blocks entries & risk-increasing modifications only (spec §6.2)
- Defaults: `operating_mode="prepare"`, `execution_mode="shadow"`, risk 2%/trade, 6% daily, max 10 concurrent, 2/symbol, 15% portfolio cap
- Rollout modes: `shadow` → `demo` → `live`, promotion explicit/recorded; default `shadow`
- All broker writes go through `AgentExecutionGateway`; no direct broker calls
- All tool calls persist to `agent_events` with `decision_id`
- Config from `ConfigService` only; ceilings enforced
- PnL & guards from `Ledger`; fail-closed

## Review Focus

1. **Planning without execution** — Plans must not execute trades; only orchestrator executes via gateway
2. **Memory leaks** — Episodic/semantic stores must have TTL/retention policies
3. **Regime overfitting** — Regime classifier must have minimum sample requirements and confidence thresholds
4. **Memory bloat** — Scratchpad/episodic stores must have size limits and cleanup
5. **Learning feedback loops** — Policy updates must be auditable and reversible

---

### Task 1: Reasoning Module — Planner & Reflector

**Files:**
- Create: `backend/ignite/agent/reasoning/planner.py`
- Create: `backend/ignite/agent/reasoning/reflector.py`
- Create: `backend/ignite/agent/reasoning/__init__.py`
- Modify: `backend/ignite/agent/tools.py` (add plan/reflect tools)
- Test: `tests/test_reasoning.py`

**Interfaces:**
- Consumes: `Runtime`, `ToolRegistry`, `LLMClient`
- Produces: `Plan(plan_id, steps[], status)`, `Reflection(decision_id, outcome, insights)`

- [ ] **Step 1: Write failing tests**

```python
def test_planner_creates_multi_step_plan():
    rt = create_test_runtime()
    planner = Planner(rt)
    plan = planner.create_plan("Analyze XAUUSD and execute if bullish")
    assert len(plan.steps) >= 2
    assert all(hasattr(s, 'tool') and hasattr(s, 'expected_outcome') for s in plan.steps)

def test_planner_validates_steps():
    rt = create_test_runtime()
    planner = Planner(rt)
    with pytest.raises(ValidationError):
        planner.create_plan("")  # empty plan

def test_reflector_records_insight():
    rt = create_test_runtime()
    reflector = Reflector(rt)
    reflection = reflector.reflect("decision_123", "trade_executed", {"pnl": 150, "lesson": "should have scaled earlier"})
    assert reflection.decision_id == "decision_123"
    assert "lesson" in reflection.insights
```

- [ ] **Step 2: Run tests to verify they fail**
- [ ] **Step 3: Implement `Planner` and `Reflector` in `backend/ignite/agent/reasoning/`**
  - `Planner.create_plan(goal: str) -> Plan`: Uses LLM to decompose goal into tool steps with success criteria
  - `Planner.execute_plan(plan_id: str) -> PlanResult`: Executes steps sequentially, stops on failure
  - `Reflector.reflect(decision_id: str, outcome: str, context: dict) -> Reflection`: Stores insight in `agent_events`
  - Tools registered in `ToolRegistry`: `plan`, `reflect` (permission: prepare)

- [ ] **Step 4: Run tests to verify they pass**
- [ ] **Step 5: Commit**

```bash
git add backend/ignite/agent/reasoning/ backend/ignite/agent/tools.py tests/test_reasoning.py
git commit -m "feat(agent): planner and reflector with plan/reflect tools"
```

---

### Task 2: Memory System — Episodic, Semantic, Procedural

**Files:**
- Create: `backend/ignite/agent/memory/episodic.py`
- Create: `backend/ignite/agent/memory/semantic.py`
- Create: `backend/ignite/agent/memory/procedural.py`
- Create: `backend/ignite/agent/memory/scratchpad.py`
- Create: `backend/ignite/agent/memory/__init__.py`
- Modify: `backend/ignite/agent/tools.py` (add memory tools)
- Modify: `backend/ignite/store/db.py` (add memory tables)
- Modify: `backend/ignite/store/schema.sql` (add memory tables)
- Test: `tests/test_memory.py`

**Interfaces:**
- Consumes: `Runtime`, `Store`
- Produces: `EpisodicMemory`, `SemanticMemory`, `ProceduralMemory`, `Scratchpad`

- [ ] **Step 1: Write failing tests**

```python
def test_scratchpad_read_write():
    rt = create_test_runtime()
    pad = Scratchpad(rt)
    pad.write("analysis", {"symbol": "XAUUSD", "bias": "bullish"})
    assert pad.read("analysis")["bias"] == "bullish"

def test_episodic_query_by_symbol():
    rt = create_test_runtime()
    ep = EpisodicMemory(rt)
    ep.record("trade", {"symbol": "XAUUSD", "side": "long", "pnl": 200})
    ep.record("trade", {"symbol": "EURUSD", "side": "short", "pnl": -50})
    trades = ep.query(symbol="XAUUSD")
    assert len(trades) == 1
    assert trades[0]["pnl"] == 200

def test_semantic_remember_recall():
    rt = create_test_runtime()
    sm = SemanticMemory(rt)
    sm.remember("xauusd_nfp_pattern", {"pattern": "reverses at 14:00 UTC"}, tags=["XAUUSD", "NFP"])
    results = sm.recall("XAUUSD NFP")
    assert len(results) == 1
    assert results[0]["value"]["pattern"] == "reverses at 14:00 UTC"

def test_procedural_learn_heuristic():
    rt = create_test_runtime()
    pm = ProceduralMemory(rt)
    pm.learn("spread_widening", "reduce_size_by_50", {"condition": "spread > 20pts"})
    heuristic = pm.recall("spread_widening")
    assert heuristic["action"] == "reduce_size_by_50"
```

- [ ] **Step 2: Run tests to verify they fail**
- [ ] **Step 3: Implement memory modules**
  - Schema: `scratchpad`, `episodic_memory`, `semantic_memory`, `procedural_memory` tables
  - `Scratchpad`: TTL-based key-value with structured slots
  - `EpisodicMemory`: Append-only episodes with filters (symbol, timeframe, outcome)
  - `SemanticMemory`: Vector-style (JSON + tags) with TF-IDF or embedding search
  - `ProceduralMemory`: Condition-action rules with confidence scores
  - Tools: `scratchpad.read/write`, `episodic.query`, `semantic.remember/recall`, `procedural.learn/recall` (permission: read/prepare)

- [ ] **Step 4: Run tests to verify they pass**
- [ ] **Step 5: Commit**

```bash
git add backend/ignite/agent/memory/ backend/ignite/agent/tools.py backend/ignite/store/db.py backend/ignite/store/schema.sql tests/test_memory.py
git commit -m "feat(agent): memory system — scratchpad, episodic, semantic, procedural"
```

---

### Task 3: Market Intelligence — Multi-TF, Regime, Intermarket, Order Flow

**Files:**
- Create: `backend/ignite/agent/intelligence/market_intel.py`
- Create: `backend/ignite/agent/intelligence/regime.py`
- Create: `backend/ignite/agent/intelligence/intermarket.py`
- Create: `backend/ignite/agent/intelligence/order_flow.py`
- Create: `backend/ignite/agent/intelligence/__init__.py`
- Modify: `backend/ignite/agent/tools.py` (add intel tools)
- Test: `tests/test_market_intel.py`

**Interfaces:**
- Consumes: `Runtime`, `ForecastClient`, `MarketData`
- Produces: `MarketIntel`, `RegimeClassification`, `IntermarketCorrelation`, `OrderFlowAnalysis`

- [ ] **Step 1: Write failing tests**

```python
def test_multi_tf_synthesis():
    rt = create_test_runtime()
    intel = MarketIntel(rt)
    result = intel.synthesize("XAUUSD", ["M1", "M5", "M15", "H1", "H4", "D1"])
    assert "trend" in result and "structure" in result and "regimes" in result

def test_regime_classification():
    rt = create_test_runtime()
    regime = RegimeClassifier(rt)
    result = regime.classify("XAUUSD", lookback=500)
    assert result.regime in ("trend_up", "trend_down", "range", "volatile", "breakout")
    assert 0 <= result.confidence <= 1

def test_intermarket_correlation():
    rt = create_test_runtime()
    im = IntermarketAnalyzer(rt)
    result = im.analyze("XAUUSD", ["DXY", "US10Y", "US500"])
    assert "correlation" in result and "lead_lag" in result

def test_order_flow_analysis():
    rt = create_test_runtime()
    of = OrderFlowAnalyzer(rt)
    result = of.analyze("XAUUSD", depth=10)
    assert "cvd" in result and "delta" in result and "absorption" in result
```

- [ ] **Step 2: Run tests to verify they fail**
- [ ] **Step 3: Implement intelligence modules**
  - `MarketIntel`: Multi-TF synthesis using existing `compute_structure` + forecast
  - `RegimeClassifier`: HMM-based (hmmlearn) with regime persistence, transition probabilities
  - `IntermarketAnalyzer`: Rolling correlation + Granger causality for lead/lag
  - `OrderFlowAnalyzer`: CVD, delta, absorption detection from tick/Level 2 data
  - Tools: `market.intel`, `regime.classify`, `intermarket.correlation`, `orderflow.analyze` (permission: read)

- [ ] **Step 4: Run tests to verify they pass**
- [ ] **Step 5: Commit**

```bash
git add backend/ignite/agent/intelligence/ backend/ignite/agent/tools.py tests/test_market_intel.py
git commit -m "feat(agent): market intelligence — multi-TF, regime, intermarket, order flow"
```

---

### Task 5: Dynamic Risk Intelligence

**Files:**
- Create: `backend/ignite/agent/intelligence/risk_intel.py`
- Modify: `backend/ignite/agent/tools.py` (add risk tools)
- Test: `tests/test_risk_intel.py`

**Interfaces:**
- Consumes: `Runtime`, `Ledger`, `MarketIntel`, `Positions`
- Produces: `RiskDecomposition`, `DynamicSizing`, `AdaptiveExit`, `CorrelationHedge`

- [ ] **Step 1: Write failing tests**

```python
def test_risk_decomposition():
    rt = create_test_runtime()
    ri = RiskIntel(rt)
    result = ri.decompose(rt.positions())
    assert "var" in result and "es" in result and "correlation_risk" in result

def test_dynamic_sizing():
    rt = create_test_runtime()
    ri = RiskIntel(rt)
    result = ri.size("XAUUSD", "long", signal_strength=0.8)
    assert result.size <= rt.config().max_risk_pct * rt.ledger.daily().day_start_equity / ri._risk_per_lot("XAUUSD")

def test_adaptive_exit():
    rt = create_test_runtime()
    ri = RiskIntel(rt)
    result = ri.exit_plan({"symbol": "XAUUSD", "side": "buy", "entry": 3930, "sl": 3920, "tp": 3950})
    assert "trail_type" in result and "trail_param" in result
```

- [ ] **Step 2: Run tests to verify they fail**
- [ ] **Step 3: Implement risk intelligence**
  - `RiskDecompose`: VaR (historical/parametric), Expected Shortfall, tail risk, correlation risk, concentration
  - `DynamicSizing`: Kelly fraction × regime multiplier × correlation penalty × volatility scaling
  - `AdaptiveExit`: Regime-based trailing (ATR × regime_multiplier), partial TP at structure levels (0.5R, 1R, 2R), time-based stops
  - `CorrelationHedge`: Minimum variance hedge ratio, cost estimation
  - Tools: `risk.decompose`, `risk.size`, `risk.exit_plan`, `risk.hedge` (permission: prepare)

- [ ] **Step 4: Run tests to verify they pass**
- [ ] **Step 5: Commit**

```bash
git add backend/ignite/agent/intelligence/risk_intel.py backend/ignite/agent/tools.py tests/test_risk_intel.py
git commit -m "feat(agent): dynamic risk intelligence — decomposition, sizing, exits, hedging"
```

---

### Task 6: Execution Quality — Smart Routing & Slippage

**Files:**
- Create: `backend/ignite/agent/intelligence/execution_intel.py`
- Modify: `backend/ignite/services/gateway.py` (add TWAP/VWAP/iceberg)
- Modify: `backend/ignite/agent/tools.py` (add execution tools)
- Test: `tests/test_execution_intel.py`

**Interfaces:**
- Consumes: `Runtime`, `Gateway`, `MarketData`
- Produces: `SlippagePrediction`, `VenueSelection`, `ExecutionPlan`, `FillManagement`

- [ ] **Step 1: Write failing tests**

```python
def test_slippage_prediction():
    rt = create_test_runtime()
    ei = ExecutionIntel(rt)
    pred = ei.predict_slippage("XAUUSD", 0.1, "buy")
    assert "expected_slippage" in pred and "confidence" in pred

def test_venue_selection():
    rt = create_test_runtime()
    ei = ExecutionIntel(rt)
    venue = ei.select_venue("XAUUSD", 0.1)
    assert "venue" in venue and "expected_fill_rate" in venue

def test_twap_execution():
    rt = create_test_runtime()
    ei = ExecutionIntel(rt)
    plan = ei.create_twap("XAUUSD", 1.0, "buy", duration_min=60)
    assert len(plan.slices) > 1 and sum(s.size for s in plan.slices) == 1.0
```

- [ ] **Step 2: Run tests to verify they fail**
- [ ] **Step 3: Implement execution intelligence**
  - `SlippagePrediction`: Historical slippage model by venue/size/volatility/time
  - `VenueSelection`: Score venues by latency, fill rate, rebate, toxicity
  - `ExecutionPlan`: TWAP/VWAP/POV slicing, iceberg, sniper logic
  - `FillManagement`: Partial fill handling, residual management, timeout logic
  - Gateway: Add `execute_twap`, `execute_vwap`, `execute_iceberg` methods
  - Tools: `execution.predict_slippage`, `execution.select_venue`, `execution.create_twap` (permission: execute)

- [ ] **Step 4: Run tests to verify they pass**
- [ ] **Step 5: Commit**

```bash
git add backend/ignite/agent/intelligence/execution_intel.py backend/ignite/services/gateway.py backend/ignite/agent/tools.py tests/test_execution_intel.py
git commit -m "feat(agent): execution intelligence — slippage, venue, TWAP/VWAP, fill management"
```

---

### Task 7: Autonomy Graduation & Policy Engine

**Files:**
- Create: `backend/ignite/agent/policy/autonomy.py`
- Create: `backend/ignite/agent/policy/policy_engine.py`
- Create: `backend/ignite/agent/policy/exception.py`
- Create: `backend/ignite/agent/policy/__init__.py`
- Modify: `backend/ignite/agent/config.py` (add autonomy_level, policy_path)
- Modify: `backend/ignite/agent/config.py` (AgentConfig additions)
- Modify: `backend/ignite/agent/tools.py` (register execute tools conditionally)
- Test: `tests/test_autonomy.py`

**Interfaces:**
- Consumes: `Runtime`, `ConfigService`, `PolicyEngine`
- Produces: `AutonomyEngine`, `PolicyEngine`, `ExceptionHandler`

- [ ] **Step 1: Write failing tests**

```python
def test_autonomy_levels():
    rt = create_test_runtime()
    ae = AutonomyEngine(rt)
    rt.config_service.update({"autonomy_level": 2})
    tools = rt.tool_registry.get_available("autonomous", False)
    assert any(t.name == "execution.place_order" for t in tools)
    rt.config_service.update({"autonomy_level": 0})
    tools = rt.tool_registry.get_available("autonomous", False)
    assert not any(t.name == "execution.place_order" for t in tools)

def test_policy_enforcement():
    rt = create_test_runtime()
    pe = PolicyEngine(rt)
    rt.config_service.update({"policy_path": "policy.json"})
    # policy.json: {"max_drawdown_pct": 0.05, "max_leverage": 10, "forbidden_symbols": ["BTCUSD"]}
    result = pe.validate({"symbol": "BTCUSD", "size": 1.0, "leverage": 20})
    assert not result.ok and "forbidden" in result.error
```

- [ ] **Step 2: Run tests to verify they fail**
- [ ] **Step 3: Implement autonomy & policy**
  - `AutonomyEngine`: Levels 0-4, tool registration gating, mode transition logic
  - `PolicyEngine`: JSON schema validation, constraint checking (drawdown, leverage, symbols, correlation, time), audit trail
  - `ExceptionHandler`: Human-in-the-loop escalation for policy violations, timeout fallback
  - Config: `autonomy_level`, `policy_path`, policy schema validation
  - Tool registration: Execute tools only when `autonomy_level >= 2` and policy passes

- [ ] **Step 4: Run tests to verify they pass**
- [ ] **Step 5: Commit**

```bash
git add backend/ignite/agent/policy/ backend/ignite/agent/config.py backend/ignite/agent/tools.py backend/ignite/agent/config.py tests/test_autonomy.py
git commit -m "feat(agent): autonomy graduation & policy engine — levels 0-4, policy enforcement, exceptions"
```

---

### Task 8: Explainability & Communication

**Files:**
- Create: `backend/ignite/agent/communication/reasoner.py`
- Create: `backend/ignite/agent/communication/explainer.py`
- Create: `backend/ignite/agent/communication/learner.py`
- Create: `backend/ignite/agent/communication/__init__.py`
- Modify: `backend/ignite/agent/tools.py` (add explain tool)
- Test: `tests/test_communication.py`

**Interfaces:**
- Consumes: `Runtime`, `Memory`, `DecisionHistory`
- Produces: `ReasoningStream`, `DecisionExplanation`, `LearningDashboard`

- [ ] **Step 1: Write failing tests**

```python
def test_reasoning_stream():
    rt = create_test_runtime()
    reasoner = Reasoner(rt)
    stream = reasoner.stream("Analyzing XAUUSD...")
    assert "thinking" in next(stream) and "tool" in next(stream)

def test_decision_explanation():
    rt = create_test_runtime()
    explainer = Explainer(rt)
    decision = create_test_decision()
    explanation = explainer.explain(decision)
    assert "thesis" in explanation and "evidence" in explanation and "counterfactuals" in explanation
```

- [ ] **Step 2: Run tests to verify they fail**
- [ ] **Step 3: Implement communication**
  - `Reasoner`: Real-time SSE stream of reasoning tokens, tool calls, intermediate conclusions
  - `Explainer`: Decision tree with evidence, counterfactuals ("if SL was 10pts wider..."), links to evidence
  - `Learner`: Dashboard showing extracted patterns, hypothesis track record, regime-specific performance
  - Tools: `explain.decision`, `explain.reasoning`, `learn.pattern` (permission: read)

- [ ] **Step 4: Run tests to verify they pass**
- [ ] **Step 5: Commit**

```bash
git add backend/ignite/agent/communication/ backend/ignite/agent/tools.py tests/test_communication.py
git commit -m "feat(agent): explainability — reasoning stream, decision explainer, learning dashboard"
```

---

### Task 9: Learning Loop — Backtest, A/B, Policy Gradient, Regime Adapter

**Files:**
- Create: `backend/ignite/agent/learning/backtest_integration.py`
- Create: `backend/ignite/agent/learning/ab_test.py`
- Create: `backend/ignite/agent/learning/policy_gradient.py`
- Create: `backend/ignite/agent/learning/regime_adapter.py`
- Create: `backend/ignite/agent/learning/__init__.py`
- Test: `tests/test_learning.py`

**Interfaces:**
- Consumes: `Runtime`, `Memory`, `DecisionHistory`, `MarketData`
- Produces: `BacktestReport`, `ABTestReport`, `PolicyUpdate`, `RegimePolicy`

- [ ] **Step 1: Write failing tests**

```python
def test_continuous_backtest():
    rt = create_test_runtime()
    bt = BacktestIntegration(rt)
    report = bt.run(counterfactual_decisions=100)
    assert "sharpe" in report and "max_drawdown" in report

def test_ab_test():
    rt = create_test_runtime()
    ab = ABTest(rt)
    ab.register_variant("control", {"risk_pct": 0.02})
    ab.register_variant("treatment", {"risk_pct": 0.03})
    report = ab.run(days=30)
    assert "winner" in report and "p_value" in report
```

- [ ] **Step 2: Run tests to verify they fail**
- [ ] **Step 3: Implement learning loop**
  - `BacktestIntegration`: Replay decisions with counterfactuals, compute metrics
  - `ABTest`: Multi-armed bandit for policy variants, statistical significance
  - `PolicyGradient`: REINFORCE on sizing/exit parameters, baseline subtraction
  - `RegimeAdapter`: Online regime detection → policy parameter swap (separate params per regime)
  - Tools: `learn.backtest`, `learn.ab_test`, `learn.update_policy` (permission: prepare)

- [ ] **Step 4: Run tests to verify they pass**
- [ ] **Step 5: Commit**

```bash
git add backend/ignite/agent/learning/ backend/ignite/agent/tools.py tests/test_learning.py
git commit -m "feat(agent): learning loop — backtest, A/B test, policy gradient, regime adapter"
```

---

### Task 10: Frontend Integration — Workbench Enhancements

**Files:**
- Modify: `frontend/src/pages/AgentWorkbench.tsx` (add planning, memory, learning panels)
- Create: `frontend/src/components/PlanPanel.tsx`
- Create: `frontend/src/components/MemoryPanel.tsx`
- Create: `frontend/src/components/LearningDashboard.tsx`
- Create: `frontend/src/components/ReasoningStream.tsx`
- Modify: `frontend/src/lib/types.ts` (add new types)
- Modify: `frontend/src/hooks/useAgent.ts` (add new hooks)

**Interfaces:**
- New UI components for planning, memory, reasoning, learning
- Types for Plan, Reflection, MemoryEntry, LearningReport

- [ ] **Step 1: Add types to `frontend/src/lib/types.ts`**
- [ ] **Step 2: Create UI components**
- [ ] **Step 3: Integrate into `AgentWorkbench.tsx`**
- [ ] **Step 4: Add hooks to `useAgent.ts`**
- [ ] **Step 5: Run typecheck + build**
- [ ] **Step 6: Commit**

```bash
git add frontend/src/ frontend/src/components/ frontend/src/hooks/ frontend/src/lib/types.ts
git commit -m "feat(ui): Hernes workbench — planning, memory, reasoning, learning panels"
```

---

### Task 11: Integration Tests & Verification

**Files:**
- Create: `tests/test_hernes_integration.py`
- Test: `tests/test_hernes_e2e.py`

**Interfaces:**
- End-to-end: Plan → Execute → Reflect → Learn cycle

- [ ] **Step 1: Write failing integration test**

```python
def test_full_hernes_cycle():
    rt = create_test_runtime()
    rt.config_service.update({"autonomy_level": 2, "execution_mode": "shadow"})
    # 1. Plan
    planner = Planner(rt)
    plan = planner.create_plan("Analyze XAUUSD and execute if bullish")
    # 2. Execute (via orchestrator)
    # 3. Reflect
    reflector = Reflector(rt)
    reflection = reflector.reflect(plan.decision_id, "trade_executed", {"pnl": 100})
    # 4. Learn
    learner = Learner(rt)
    pattern = learner.extract()
    assert pattern is not None
```

- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Fix integration issues**
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit**

```bash
git add tests/test_hernes_integration.py tests/test_hernes_e2e.py
git commit -m "test(agent): Hernes integration — full plan→execute→reflect→learn cycle"
```

---

### Task 12: Final Verification & Spec Update

- [ ] **Step 1: Run full backend suite**

```bash
pytest tests -q
# Expected: all pass (baseline + new tests)
```

- [ ] **Step 2: Run frontend checks**

```bash
cd frontend && npm run typecheck && npm run build
# Expected: both pass
```

- [ ] **Step 3: Update spec status**

```bash
# Edit docs/superpowers/specs/2026-11-13-agentic-trading-platform-design.md
# Status: Implemented: slice 1-5 + Hernes harness
git add docs/superpowers/specs/2026-11-13-agentic-trading-platform-design.md
git commit -m "docs: mark Hernes harness implemented"
```

- [ ] **Step 4: Final commit**

```bash
git add .
git commit -m "feat(hernes): complete Agent Hernes Harness — planning, memory, intelligence, risk, execution, autonomy, explainability, learning"
```

---

## Summary of New Files

```
backend/ignite/agent/
├── reasoning/
│   ├── __init__.py
│   ├── planner.py
│   └── reflector.py
├── memory/
│   ├── __init__.py
│   ├── episodic.py
│   ├── semantic.py
│   ├── procedural.py
│   └── scratchpad.py
├── intelligence/
│   ├── __init__.py
│   ├── market_intel.py
│   ├── regime.py
│   ├── intermarket.py
│   ├── order_flow.py
│   ├── risk_intel.py
│   └── execution_intel.py
├── policy/
│   ├── __init__.py
│   ├── autonomy.py
│   ├── policy_engine.py
│   └── exception.py
├── communication/
│   ├── __init__.py
│   ├── reasoner.py
│   ├── explainer.py
│   └── learner.py
├── learning/
│   ├── __init__.py
│   ├── backtest_integration.py
│   ├── ab_test.py
│   ├── policy_gradient.py
│   └── regime_adapter.py
├── communication/
│   ├── __init__.py
│   ├── reasoner.py
│   ├── explainer.py
│   └── learner.py
├── policy/
│   ├── __init__.py
│   ├── autonomy.py
│   ├── policy_engine.py
│   └── exception.py
├── memory/
│   ├── __init__.py
│   ├── episodic.py
│   ├── semantic.py
│   ├── procedural.py
│   └── scratchpad.py
├── tools.py (extended)
└── config.py (extended)

frontend/src/
├── components/
│   ├── PlanPanel.tsx
│   ├── MemoryPanel.tsx
│   ├── LearningDashboard.tsx
│   └── ReasoningStream.tsx
├── hooks/
│   └── useAgent.ts (extended)
├── lib/
│   └── types.ts (extended)
└── pages/
    └── AgentWorkbench.tsx (extended)

tests/
├── test_reasoning.py
├── test_memory.py
├── test_market_intel.py
├── test_risk_intel.py
├── test_execution_intel.py
├── test_autonomy.py
├── test_communication.py
├── test_learning.py
├── test_hernes_integration.py
└── test_hernes_e2e.py
```

---

## Execution Notes

- **Execute inline** (native) — single context, TDD per task, commit per task
- **TDD mandatory** — write test, watch fail, implement, watch pass, commit
- **One task at a time** — complete each task fully before next
- **Update ledger** after each task completion
- **Final review** after Task 12 — fresh context review of entire branch