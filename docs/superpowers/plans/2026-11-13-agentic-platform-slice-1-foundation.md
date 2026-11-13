# Agentic Trading Platform — Slice 1: Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the platform safe and truthful enough to build on: one config owner, real PnL, an append-only agent event log, a single execution gateway, one trading process, and the P0 crash fixes.

**Architecture:** `Runtime` owns a `ConfigService`, a `Ledger`, and an `AgentExecutionGateway`. Every broker write goes through the gateway. Every state change writes an `agent_events` row. The API process starts the trading loop in its lifespan; the separate worker process is removed.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, SQLite (WAL), pytest, React 18 + TypeScript.

**Spec:** `docs/superpowers/specs/2026-11-13-agentic-trading-platform-design.md`

## Global Constraints

- Python 3.11; existing dependencies only. Pydantic v2 is already available through FastAPI.
- All money values are USD floats; prices are rounded to `SymbolSpec.digits`.
- Risk defaults: `risk_pct=0.02`, `max_risk_pct=0.02`, `daily_loss_limit_pct=0.06`, `max_concurrent_positions=10`, `max_positions_per_symbol=2`, `portfolio_risk_cap_pct=0.15`.
- Ceilings: `risk_pct<=0.03`, `max_risk_pct<=0.03`, `daily_loss_limit_pct<=0.10`, `max_concurrent_positions<=15`, `max_positions_per_symbol<=3`, `portfolio_risk_cap_pct<=0.20`.
- Guards fail closed: unavailable data blocks the action and writes an event.
- The gateway validates and rejects; it never rewrites lots or prices.
- SQLite changes are additive; `Store._migrate()` must bring old files forward.
- Commands run from the repository root. Tests: `python -m pytest tests -q`.
- Commit after every task.

## Review Focus

1. A fill arrives with no SL/TP attached → the position must be closed and the decision marked `PROTECTION_FAILED`, never reported as protected.
2. Two concurrent orders on the same symbol → exactly one fills; the other is rejected `MAX_PER_SYMBOL`.
3. Config is updated mid-cycle → the next cycle observes the new values; no cycle sees a half-written config.
4. The PnL source times out → new entries are blocked, exits still work, and the reason is persisted.
5. The same `decision_id` is submitted twice → exactly one broker order exists.

---

### Task 1: Persist agent events and config versions

**Files:**
- Modify: `backend/ignite/store/schema.sql`
- Modify: `backend/ignite/store/db.py`
- Test: `tests/test_events_store.py`

**Interfaces:**
- Consumes: existing `Store`, `utc_now()`.
- Produces:
  - `Store.append_agent_event(kind: str, severity: str = "info", symbol: str | None = None, decision_id: str | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]`
  - `Store.agent_events(decision_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]`
  - `Store.write_agent_config(enabled: bool, config_json: str) -> int` returning the new version.
  - `Store.read_agent_config() -> dict[str, Any] | None` with `version` included.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_events_store.py
from backend.ignite.store.db import Store


def test_append_and_read_event(tmp_path):
    store = Store(tmp_path / "t.db")
    event = store.append_agent_event(
        "order.rejected", severity="warning", symbol="XAUUSD",
        decision_id="d1", payload={"code": "SPREAD"},
    )
    assert event["kind"] == "order.rejected"
    assert event["payload"] == {"code": "SPREAD"}
    assert event["seq"] == 1
    rows = store.agent_events(decision_id="d1")
    assert len(rows) == 1
    assert rows[0]["symbol"] == "XAUUSD"


def test_event_seq_increments(tmp_path):
    store = Store(tmp_path / "t.db")
    store.append_agent_event("a")
    second = store.append_agent_event("b")
    assert second["seq"] == 2


def test_config_version_increments(tmp_path):
    store = Store(tmp_path / "t.db")
    assert store.read_agent_config() is None
    assert store.write_agent_config(True, '{"enabled": true}') == 1
    assert store.write_agent_config(False, '{"enabled": false}') == 2
    row = store.read_agent_config()
    assert row["version"] == 2
    assert row["enabled"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_events_store.py -q`
Expected: FAIL with `AttributeError: 'Store' object has no attribute 'append_agent_event'`

- [ ] **Step 3: Add schema and store methods**

In `schema.sql`, add after `agent_config`:

```sql
CREATE TABLE IF NOT EXISTS agent_events (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    id           TEXT NOT NULL UNIQUE,
    created_at   TEXT NOT NULL,
    kind         TEXT NOT NULL,
    severity     TEXT NOT NULL DEFAULT 'info',
    symbol       TEXT,
    decision_id  TEXT,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_events_decision
    ON agent_events (decision_id, seq);
CREATE INDEX IF NOT EXISTS idx_agent_events_created
    ON agent_events (created_at);
```

In `_migrate()`, add `agent_config.version` (`INTEGER NOT NULL DEFAULT 1`) and the five new `agent_positions` columns from the spec §8.2: `status TEXT NOT NULL DEFAULT 'open'`, `decision_id TEXT`, `entry_deal TEXT`, `initial_risk_usd REAL`, `initial_sl REAL`, `mfe REAL`, `mae REAL`, `last_synced_at TEXT`, `broker_snapshot_json TEXT`.

`append_agent_event` writes one row with `id=uuid4().hex`, returns the row as a dict with `payload` decoded. `agent_events` selects `ORDER BY seq DESC LIMIT ?`, decodes `payload_json`, and reverses the list so callers get chronological order.

`write_agent_config` performs one `INSERT ... ON CONFLICT(key) DO UPDATE` that sets `version = agent_config.version + 1` and `enabled=excluded.enabled`; it then reads the row and returns `version`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_events_store.py -q`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/ignite/store/schema.sql backend/ignite/store/db.py tests/test_events_store.py
git commit -m "feat(store): agent event log and config versioning"
```

---

### Task 2: Single config owner

**Files:**
- Modify: `backend/ignite/agent/config.py`
- Create: `backend/ignite/services/config_service.py`
- Modify: `backend/ignite/services/runtime.py`
- Test: `tests/test_config_service.py`

**Interfaces:**
- Consumes: `Store.read_agent_config`, `Store.write_agent_config`, `EventBus.publish`.
- Produces:
  - `AgentConfig` fields: `enabled`, `operating_mode: Literal["observe","prepare","autonomous"]`, `execution_mode: Literal["shadow","demo","live"]`, `symbols`, `timeframe`, `cycle_interval_min`, `session_open_hour`, `session_end_hour`, `max_concurrent_analyses`, `position_check_interval_sec`, `max_concurrent_positions`, `max_positions_per_symbol`, `portfolio_risk_cap_pct`, `risk_pct`, `max_risk_pct`, `daily_loss_limit_pct`, `trail_sl_atr`, `scale_in_atr`, `scale_out_levels`, `max_correlation`.
  - `AgentConfig.to_risk_config(max_drift_atr: float) -> RiskConfig`
  - `CEILINGS: dict[str, float]`
  - `class AgentConfigPatch(BaseModel)` with `model_config = ConfigDict(extra="forbid")`
  - `class ConfigError(ValueError)`
  - `class ConfigService(store: Store, seed: AgentConfig, events: EventBus | None = None)` with `get() -> AgentConfig`, `version() -> int`, `update(patch: dict[str, Any]) -> AgentConfig`, `set_enabled(enabled: bool) -> AgentConfig`, `set_operating_mode(mode: str) -> AgentConfig`, `set_execution_mode(mode: str) -> AgentConfig`.
  - `Runtime.config() -> AgentConfig`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config_service.py
import pytest
from backend.ignite.agent.config import AgentConfig, ConfigError
from backend.ignite.services.config_service import ConfigService
from backend.ignite.store.db import Store


def test_seeds_from_env_once(tmp_path):
    store = Store(tmp_path / "t.db")
    svc = ConfigService(store, AgentConfig())
    assert svc.get().operating_mode == "prepare"
    # A second service must read the persisted row, not re-seed.
    svc2 = ConfigService(store, AgentConfig(operating_mode="observe"))
    assert svc2.get().operating_mode == "prepare"


def test_update_is_immutable_and_persisted(tmp_path):
    svc = ConfigService(Store(tmp_path / "t.db"), AgentConfig())
    before = svc.get()
    after = svc.update({"risk_pct": 0.025})
    assert before.risk_pct == 0.02
    assert after.risk_pct == 0.025
    assert svc.get().risk_pct == 0.025


def test_ceiling_rejects(tmp_path):
    svc = ConfigService(Store(tmp_path / "t.db"), AgentConfig())
    with pytest.raises(ConfigError, match="risk_pct"):
        svc.update({"risk_pct": 0.5})


def test_unknown_field_rejected(tmp_path):
    svc = ConfigService(Store(tmp_path / "t.db"), AgentConfig())
    with pytest.raises(ConfigError):
        svc.update({"not_a_field": 1})


def test_risk_config_carries_aggressive_envelope(tmp_path):
    svc = ConfigService(Store(tmp_path / "t.db"), AgentConfig())
    risk = svc.get().to_risk_config(max_drift_atr=0.3)
    assert risk.risk_pct == 0.02
    assert risk.max_risk_pct == 0.02
    assert risk.risk_pct <= risk.max_risk_pct


def test_version_bumps_and_toggle_persists(tmp_path):
    svc = ConfigService(Store(tmp_path / "t.db"), AgentConfig())
    v1 = svc.version()
    svc.set_enabled(True)
    assert svc.version() == v1 + 1
    assert svc.get().enabled is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config_service.py -q`
Expected: FAIL with `ModuleNotFoundError: backend.ignite.services.config_service`

- [ ] **Step 3: Implement**

Add the new fields and defaults to `AgentConfig` (frozen dataclass), keeping `from_env()` for seed values. Add `to_risk_config`, `CEILINGS`, `ConfigError`, and `AgentConfigPatch`.

`ConfigService` holds a `threading.Lock` and a cached `(version, AgentConfig)`. `get()` reads `store.read_agent_config()`; if the row is missing it writes the seed; if the row version differs from the cache it reloads. `update()` merges the patch, rejects unknown keys and ceiling violations with `ConfigError`, writes via `dataclasses.replace`, and publishes `config.changed` with `{"version": n}`.

In `Runtime.__init__`, replace `self.agent_config = AgentConfig.from_env()` with `self.config_service = ConfigService(self.store, AgentConfig.from_env(), self.events)`. Add `Runtime.config()` returning `self.config_service.get()`. Keep a read-only `agent_config` property for backwards compatibility that returns `self.config()`.

Because `max_risk_pct` rises from `0.010` to `0.020`, update the existing assertion in `tests/test_api.py:47` from `pytest.approx(0.01)` to `pytest.approx(0.02)`. The `/api/settings` rejection test still passes because `0.05 > 0.02`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config_service.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/ignite/agent/config.py backend/ignite/services/config_service.py backend/ignite/services/runtime.py tests/test_config_service.py
git commit -m "feat(config): single persisted config owner"
```

---

### Task 3: Real PnL, daily-loss guard, and real technical context

**Files:**
- Create: `backend/ignite/services/ledger.py`
- Modify: `backend/ignite/services/runtime.py`
- Modify: `backend/ignite/agent/engine.py:255-286`
- Modify: `backend/ignite/agent/position_manager.py:230-245`
- Modify: `backend/ignite/agent/synthesis.py:89-112`
- Test: `tests/test_guard_matrix.py`

**Interfaces:**
- Consumes: `Runtime.realised_today()`, `Runtime.account()`, `Runtime.positions()`, `Runtime.config()`, `Store.append_agent_event`.
- Produces:
  - `@dataclass(frozen=True) class DailyPnl` with `realised_usd`, `floating_usd`, `total_usd`, `day_start_equity`, `loss_limit_usd`, `remaining_usd`, `available: bool`, `blocked: bool`.
  - `class Ledger` with `daily() -> DailyPnl` and `open_risk_usd(positions: list[dict] | None = None) -> float`.
  - `Runtime.ledger: Ledger`
  - `AgentEngine._check_guards() -> GuardResult` using `Ledger.daily()`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_guard_matrix.py
from backend.ignite.services.ledger import DailyPnl, Ledger
from backend.ignite.store.db import Store


class FakeRt:
    def __init__(self, tmp_path, realised, equity=10000.0, floating=0.0, fail=False):
        self.store = Store(tmp_path / "guard.db")
        self._realised = realised
        self._equity = equity
        self._floating = floating
        self._fail = fail

    def realised_today(self):
        if self._fail:
            raise RuntimeError("broker down")
        return {"realised_usd": self._realised}

    def account(self):
        return {"equity": self._equity, "profit": self._floating}

    def positions(self):
        return []

    def config(self):
        from backend.ignite.agent.config import AgentConfig
        return AgentConfig(daily_loss_limit_pct=0.06)


def test_daily_loss_blocks_entries(tmp_path):
    pnl = Ledger(FakeRt(tmp_path, realised=-700.0)).daily()
    assert pnl.total_usd == -700.0
    assert pnl.blocked is True


def test_daily_loss_below_limit_allows(tmp_path):
    pnl = Ledger(FakeRt(tmp_path, realised=-200.0)).daily()
    assert pnl.blocked is False


def test_missing_pnl_source_fails_closed(tmp_path):
    rt = FakeRt(tmp_path, realised=0.0, fail=True)
    pnl = Ledger(rt).daily()
    assert pnl.available is False
    assert pnl.blocked is True
    assert rt.store.agent_events()[-1]["kind"] == "guard.daily_loss_unavailable"


def test_technical_context_reads_features_json(tmp_path):
    from backend.ignite.agent.synthesis import build_technical_context
    from backend.ignite.store.db import Store
    store = Store(tmp_path / "t.db")
    store._conn.execute(
        """INSERT INTO analyses (id, created_at, symbol, timeframe, last_bar_time,
        lookback, horizon, samples, model_id, infer_s, atr, p_up, edge, edge_atr,
        dispersion, signal, signal_version, risk_version, features_json, reasons_json)
        VALUES ('a','2026-01-01T00:00:00+00:00','XAUUSD','M15','t',1,1,1,'m',0.1,
        2.5,0.6,1.0,0.5,0.1,'LONG','v1','v1',
        '{"trend":"up","atr":2.5,"last_close":3930.0}','[]')"""
    )
    store._conn.commit()
    class Rt:
        def __init__(self): self.store = store
    ctx = build_technical_context(Rt(), "XAUUSD", "M15")
    assert ctx.trend == "up"
    assert ctx.atr == 2.5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_guard_matrix.py -q`
Expected: FAIL with `ModuleNotFoundError: backend.ignite.services.ledger`

- [ ] **Step 3: Implement**

`Ledger.daily()`:

- `realised = float(rt.realised_today()["realised_usd"])`
- `equity = float(rt.account().get("equity") or 0.0)`, `floating = float(account.get("profit") or 0.0)`
- `day_start_equity = equity - floating - realised` (clamped to `>0`; if not, `available=False`)
- `limit = day_start_equity * config().daily_loss_limit_pct`
- `total = realised + floating`
- `blocked = not available or total <= -limit`

Any exception from the broker sets `available=False` and `blocked=True`, and writes `guard.daily_loss_unavailable` via `store.append_agent_event`.

`Runtime.ledger = Ledger(self)` in `__init__`.

Replace the broken block in `engine.py` and `position_manager.py` with `pnl = self.rt.ledger.daily()`. If `not pnl.available`, write an event and reject the cycle with reason `daily_pnl_unavailable`. If `pnl.blocked`, reject with `daily_loss_limit`.

In `synthesis.py`, change `row.get("features", {})` to decode `json.loads(row["features_json"])` when the column exists, falling back to `row.get("features", {})`. Remove the `_assess_volatility_regime(0.0) == "compression"` confidence bump when ATR is unavailable: treat missing ATR as `normal` and write `technical.missing_atr` to the event log.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_guard_matrix.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/ignite/services/ledger.py backend/ignite/services/runtime.py backend/ignite/agent/engine.py backend/ignite/agent/position_manager.py backend/ignite/agent/synthesis.py tests/test_guard_matrix.py
git commit -m "fix(risk): real PnL ledger and fail-closed daily loss guard"
```

---

### Task 4: Execution gateway

**Files:**
- Create: `backend/ignite/services/gateway.py`
- Modify: `tests/fakes.py`
- Test: `tests/test_gateway.py`

**Interfaces:**
- Consumes: `Runtime.config()`, `Runtime.account()`, `Runtime.positions()`, `Runtime.spec()`, `Runtime.quote()`, `Runtime.spread()`, `Runtime.news.blackout_at()`, `Runtime.ledger`, `Runtime.kill_switch()`, `Runtime.store`, `broker.send_market_order`, `broker.close_position`, `broker.modify_position_sl_tp`, `broker.extract_order_ticket`.
- Produces:
  - `@dataclass(frozen=True) class OrderRequest` with `symbol: str`, `side: str`, `lots: float`, `sl: float`, `tp: float`, `decision_id: str`, `comment: str = "ignite agent"`, `order_type: str = "market"`.
  - `@dataclass(frozen=True) class OrderResult` with `ok: bool`, `code: str`, `detail: str`, `position_ticket: str | None = None`, `fill_price: float | None = None`, `unprotected: bool = False`.
  - `class AgentExecutionGateway` with `validate(req) -> OrderResult`, `place(req) -> OrderResult`, `close(ticket, reason) -> OrderResult`, `modify(ticket, sl, tp) -> OrderResult`.
  - `Store.begin_order(decision_id: str, symbol: str, side: str, lots: float) -> bool` — inserts an `orders` row with `id=decision_id`; returns `False` on `IntegrityError`.
  - `Runtime.gateway = AgentExecutionGateway(self)`.
  - Rejection codes: `KILL_SWITCH`, `MODE`, `NOT_WATCHED`, `SPEC`, `MARKET_CLOSED`, `SPREAD`, `NEWS_BLACKOUT`, `DAILY_LOSS`, `MAX_POSITIONS`, `MAX_PER_SYMBOL`, `PORTFOLIO_RISK`, `MARGIN`, `LOTS`, `STOPS`, `DUPLICATE`, `BROKER`, `PROTECTION_FAILED`, `UNRESOLVED`.
  - Kill switch blocks new entries and risk-increasing modifications only. `close()` is always allowed so an operator or the supervisor can reduce risk.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gateway.py
from backend.ignite.services.gateway import AgentExecutionGateway, OrderRequest


def make_gateway(rt):
    return AgentExecutionGateway(rt)


def test_duplicate_decision_is_rejected(rt):
    gw = make_gateway(rt)
    req = OrderRequest("XAUUSD", "buy", 0.01, 3920.0, 3950.0, "d1")
    first = gw.place(req)
    second = gw.place(req)
    assert first.ok is True
    assert second.ok is False and second.code == "DUPLICATE"
    assert len(rt.mcp.called("trade_send_market_order")) == 1


def test_lot_step_is_rejected_not_rounded(rt):
    result = make_gateway(rt).validate(
        OrderRequest("XAUUSD", "buy", 0.015, 3920.0, 3950.0, "d2")
    )
    assert result.ok is False and result.code == "LOTS"


def test_unprotected_fill_is_closed_and_marked(rt):
    rt.mcp.drop_sl_tp = True          # fake echoes a position with no SL/TP
    result = make_gateway(rt).place(
        OrderRequest("XAUUSD", "buy", 0.01, 3920.0, 3950.0, "d3")
    )
    assert result.ok is False
    assert result.code == "PROTECTION_FAILED"
    assert result.unprotected is True
    assert rt.mcp.called("trade_close_single_position")


def test_second_position_on_symbol_is_rejected(rt):
    rt.mcp.positions.append(
        {"position_id": "1", "symbol": "XAUUSD", "action": "buy", "volume": 0.01,
         "price_open": 3930.0, "price_last": 3930.0, "comment": "ignite agent",
         "create_time": "2026-01-01T00:00:00", "update_time": "2026-01-01T00:00:00"}
    )
    result = make_gateway(rt).validate(
        OrderRequest("XAUUSD", "buy", 0.01, 3920.0, 3950.0, "d4")
    )
    assert result.code == "MAX_PER_SYMBOL"


def test_daily_loss_blocks_entry(rt):
    rt.realised_override = -700.0
    result = make_gateway(rt).validate(
        OrderRequest("XAUUSD", "buy", 0.01, 3920.0, 3950.0, "d5")
    )
    assert result.code == "DAILY_LOSS"
```

The `rt` fixture lives in `tests/conftest.py`: build a real `Runtime` with `FakeMCP`, `FakeForecast`, a no-op LLM, and a temp DB. The fixture sets `rt.realised_override = None`; when it is not `None`, it monkeypatches `rt.realised_today` to return `{"realised_usd": rt.realised_override}`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_gateway.py -q`
Expected: FAIL with `ModuleNotFoundError: backend.ignite.services.gateway`

- [ ] **Step 3: Implement**

`validate` runs the guard chain in spec §12 order and returns the first rejection. `place` calls `validate`, then inserts an `orders` row with `state="sending"` and a unique `id` derived from `decision_id`, calls `send_market_order` inside `rt.execution_lock`, resolves the position with `extract_order_ticket`, then `_await_position_by_ticket`. If the position does not carry the requested SL/TP, call `modify_position_sl_tp` once; if still unprotected, call `close_position` and return `PROTECTION_FAILED`.

`_await_position_by_ticket(rt, ticket, timeout_s=5.0)` polls `rt.positions(symbol)` and returns the row whose `ticket` matches; it never returns "the first new position".

Update `FakeMCP` to echo `sl`/`tp` into the created position, honour `drop_sl_tp`, and record `trade_close_single_position` and `trade_modify_sl_tp`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_gateway.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/ignite/services/gateway.py tests/fakes.py tests/conftest.py tests/test_gateway.py
git commit -m "feat(execution): gateway with idempotency and protection assertion"
```

---

### Task 5: Route writes through the gateway; delete fabricated traces

**Files:**
- Modify: `backend/ignite/api/routes/agent.py`
- Modify: `backend/ignite/agent/chat.py`
- Test: `tests/test_agent_api.py`

**Interfaces:**
- Consumes: `ConfigService`, `AgentExecutionGateway`, `Store.append_agent_event`.
- Produces: `POST /api/agent/positions/{ticket}/close` → `{"ok": bool, "result": {...}}`; `PUT /api/agent/config` → the resolved config dict; `POST /api/agent/chat` returns `tool_calls` read from `agent_events` for the request's decision id.

- [ ] **Step 1: Write the failing tests**

```python
def test_manual_close_uses_symbol_and_ticket(client, rt):
    rt.mcp.positions.append(
        {"position_id": "900001", "symbol": "XAUUSD", "action": "buy",
         "volume": 0.01, "price_open": 3930.0, "price_last": 3930.0,
         "sl": 3920.0, "tp": 3950.0, "comment": "ignite agent",
         "create_time": "2026-01-01T00:00:00", "update_time": "2026-01-01T00:00:00"}
    )
    resp = client.post("/api/agent/positions/900001/close")
    assert resp.status_code == 200
    args = rt.mcp.called("trade_close_single_position")[0]
    assert args == {"symbol": "XAUUSD", "position_ticket": "900001"}


def test_config_put_round_trips_and_applies(client, rt):
    resp = client.put("/api/agent/config", json={"risk_pct": 0.025})
    assert resp.status_code == 200
    assert resp.json()["risk_pct"] == 0.025
    assert rt.config().risk_pct == 0.025


def test_question_does_not_place_an_order(client, rt):
    resp = client.post("/api/agent/chat", json={"text": "should I buy XAUUSD?"})
    assert resp.status_code == 200
    assert rt.mcp.called("trade_send_market_order") == []


def test_chat_tool_trace_is_real(client, rt):
    resp = client.post("/api/agent/chat", json={"text": "show my positions"})
    for row in resp.json()["tool_calls"]:
        assert rt.store.agent_events(decision_id=row["decision_id"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_agent_api.py -q`
Expected: FAIL on the close endpoint (`TypeError`) and the config PUT (`FrozenInstanceError`).

- [ ] **Step 3: Implement**

- `close_agent_position`: load the store row, call `rt.gateway.close(ticket, "MANUAL")`, persist `close_agent_position` only when `result.ok`.
- `agent_config_put`: `rt.config_service.update(body.model_dump(exclude_unset=True))`; return `config.__dict__`. Replace `ConfigRequest` with `AgentConfigPatch`.
- `agent_chat`: delete `_tool_plan` and the loop that saves `"<tool> completed"`. Execute the skill, write events for each real step, then return `tool_calls = rt.store.agent_events(decision_id=decision_id)`.
- `chat.py`: give trade-intent patterns a guard that rejects questions and negations. Add `_is_question_or_negative(text)` checking for a trailing `?`, leading `should|can|could|would|do|does|is|are|what|how`, or `don't|do not|not|never` within two tokens of the verb. Apply it to `place_trade` and `close_position` routes only.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_agent_api.py tests/test_chat_and_validation.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add backend/ignite/api/routes/agent.py backend/ignite/agent/chat.py tests/test_agent_api.py
git commit -m "fix(api): gateway-routed writes and real tool traces"
```

---

### Task 6: One trading process

**Files:**
- Modify: `backend/ignite/services/runtime.py`
- Modify: `backend/ignite/api/app.py`
- Delete: `backend/ignite/agent/worker.py`
- Create: `backend/ignite/__main__.py`
- Test: `tests/test_lifecycle.py`

**Interfaces:**
- Produces: `Runtime.start() -> None`, `Runtime.stop() -> None`; `create_app(runtime: Runtime | None = None) -> FastAPI`; `python -m backend.ignite` starts API + trading loop.

- [ ] **Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient


def test_lifespan_starts_one_scheduler_and_one_runtime(runtime):
    from backend.ignite.api.app import create_app
    app = create_app(runtime=runtime)
    with TestClient(app) as client:
        rt = app.state.runtime
        assert rt.scheduler.running is True
        assert len(rt.scheduler.get_jobs()) >= 3  # cycle + supervision + expiry
        assert client.get("/api/health").status_code == 200
    assert rt.scheduler.running is False


def test_no_worker_module():
    import importlib.util
    assert importlib.util.find_spec("backend.ignite.agent.worker") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_lifecycle.py -q`
Expected: FAIL — no `scheduler` attribute.

- [ ] **Step 3: Implement**

Move `AgentWorker`'s scheduler setup into `Runtime.start()`. `Runtime` creates one `BackgroundScheduler(timezone="UTC")`, registers the cycle job (`AgentEngine.run_cycle`), the supervision job (`PositionSupervisor.run`), and a 60 s `expire_stale_drafts` job. `Runtime.stop()` sets a shutdown event, calls `scheduler.shutdown(wait=False)`, then `shutdown()`.

`app.py`: lifespan calls `rt.start()` and `rt.stop()`. Delete `app = create_app()`; keep only the factory. `__main__.py` runs uvicorn with the factory.

Delete `agent/worker.py`; update `tests/test_agent_worker.py` to target `Runtime.start()`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_lifecycle.py tests/test_agent_worker.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add backend/ignite/services/runtime.py backend/ignite/api/app.py backend/ignite/__main__.py tests/test_lifecycle.py tests/test_agent_worker.py
git rm backend/ignite/agent/worker.py
git commit -m "refactor(runtime): single trading process and lifecycle"
```

---

### Task 7: Truthful overview contract

**Files:**
- Modify: `backend/ignite/api/routes/agent.py:793-851`
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/pages/AgentWorkbench.tsx:45-46`
- Test: `tests/test_contracts.py`

**Interfaces:**
- Produces: `GET /api/agent/overview` shape from spec §9. `agent_status.daily_pnl` reads `rt.ledger.daily().total_usd`.

- [ ] **Step 1: Write the failing test**

```python
def test_overview_contract(client):
    body = client.get("/api/agent/overview").json()
    assert set(body) >= {"status", "account", "risk", "positions", "drafts",
                         "decisions", "guardrails"}
    assert {"equity", "profit", "server", "currency", "margin_free",
            "mode"} <= set(body["account"])
    assert {"open_risk_usd", "open_risk_pct", "cap_pct", "daily_pnl",
            "daily_loss_limit_pct"} <= set(body["risk"])
    assert body["status"]["daily_pnl"] == body["risk"]["daily_pnl"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_contracts.py -q`
Expected: FAIL — `risk` key missing.

- [ ] **Step 3: Implement**

`agent_overview` builds `account` from `rt.account_payload()` plus `mode = "demo" if account["type"] == "demo" else "live"`, and `risk` from `rt.ledger.daily()` plus `rt.ledger.open_risk_usd()` and `rt.config().portfolio_risk_cap_pct`. `agent_status` stops summing open rows and uses the ledger.

Update `types.ts` to the new shape. `AgentWorkbench` reads `overview.data?.account` and `overview.data?.risk` directly.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_contracts.py -q` and `npm run typecheck` in `frontend/`
Expected: pass and pass

- [ ] **Step 5: Commit**

```bash
git add backend/ignite/api/routes/agent.py frontend/src/lib/types.ts frontend/src/pages/AgentWorkbench.tsx tests/test_contracts.py
git commit -m "fix(api): truthful overview and risk contract"
```

---

### Task 8: Pagination, draft expiry, health lock

**Files:**
- Modify: `backend/ignite/store/db.py:411-427`
- Modify: `backend/ignite/services/runtime.py`
- Modify: `backend/ignite/api/routes/system.py:51`
- Test: `tests/test_hygiene.py`

**Interfaces:**
- Produces: `Store.agent_messages(session_id, limit=200, before: str | None = None)`; `Runtime.jobs_snapshot() -> list[Job]`; `Runtime.expire_drafts()`.

- [ ] **Step 1: Write the failing tests**

```python
def test_messages_return_newest_window(tmp_path):
    store = Store(tmp_path / "t.db")
    store.create_agent_session("s", "chat")
    for i in range(250):
        store.add_agent_message({
            "id": f"m{i:03d}",
            "session_id": "s",
            "created_at": f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}+00:00",
            "role": "user",
            "content": f"m{i}",
            "status": "ok",
        })
    rows = store.agent_messages("s", limit=200)
    assert rows[-1]["content"] == "m249"
    assert rows[0]["content"] == "m50"


def test_expire_drafts_removes_stale(tmp_path):
    from backend.ignite.store.db import utc_now
    store = Store(tmp_path / "t.db")
    store._conn.execute(
        """INSERT INTO analyses (id, created_at, symbol, timeframe, last_bar_time,
        lookback, horizon, samples, model_id, infer_s, atr, p_up, edge, edge_atr,
        dispersion, signal, signal_version, risk_version, features_json, reasons_json)
        VALUES ('a','2026-01-01T00:00:00+00:00','XAUUSD','M15','t',1,1,1,'m',0.1,
        2.5,0.6,1.0,0.5,0.1,'LONG','v1','v1','{}','[]')"""
    )
    store.insert_draft({
        "id": "d1", "analysis_id": "a", "created_at": "2026-01-01T00:00:00+00:00",
        "expires_at": "2026-01-01T00:00:01+00:00", "state": "draft",
        "side": "long", "lots": 0.01, "reference_price": 3930.0,
        "sl": 3920.0, "tp": 3950.0, "risk_usd": 10.0, "risk_pct": 0.01,
        "rr": 2.0, "margin": None, "worst_case_usd": None,
        "blocked": 0, "block_reason": None, "idempotency_key": "k1",
    })
    store._conn.commit()
    assert store.expire_stale_drafts(utc_now()) == 1
    assert store.pending_drafts() == []


def test_health_uses_snapshot(client):
    assert client.get("/api/health").status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_hygiene.py -q`
Expected: FAIL — newest message is `m199`.

- [ ] **Step 3: Implement**

`agent_messages` selects `ORDER BY created_at DESC, id DESC LIMIT ?` with an optional `before` cursor (`"created_at|id"`), then reverses. `Runtime.jobs_snapshot()` copies under `_jobs_lock`; `system.health` uses it. `Runtime.expire_drafts()` calls `store.expire_stale_drafts(utc_now())` and is scheduled every 60 s.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_hygiene.py -q`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/ignite/store/db.py backend/ignite/services/runtime.py backend/ignite/api/routes/system.py tests/test_hygiene.py
git commit -m "fix(store): pagination, draft expiry, health snapshot"
```

---

### Task 9: Slice verification

- [ ] **Step 1: Run the full backend suite**

Run: `python -m pytest tests -q`
Expected: all pass, including the 72 pre-existing tests.

- [ ] **Step 2: Run the frontend checks**

Run: `npm run typecheck` and `npm run build` in `frontend/`
Expected: both pass.

- [ ] **Step 3: Update the spec status**

Change the design spec header from `Approved design, pending implementation plan` to `Implemented: slice 1 (foundation)`.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-11-13-agentic-trading-platform-design.md
git commit -m "docs: mark foundation slice implemented"
```
