# Ignite Desk — PRD & Architecture

| | |
|---|---|
| **Status** | Draft for review |
| **Date** | 2026-11-12 |
| **Owner** | cloneyjay |
| **Scope** | XAUUSD, MetaQuotes demo account, single operator, localhost |
| **Repo** | `ignite-desk` |

---

## 1. Problem

Day trading XAUUSD on a 5–15 minute horizon requires three things that are currently
scattered: a fast read on the next few bars, a disciplined position size, and an execution
path that does not depend on remembering broker rules mid-session. Kronos gives a
probabilistic forecast of the next N candles; MetaTrader 5 holds the data, the economic
calendar and the order book. Nothing connects them, and nothing enforces risk.

Ignite Desk is a local web dashboard where an AI agent mediates between those three
parts. The operator picks a symbol and timeframe, asks for an analysis, reviews a fully
specified draft order, and confirms. Every number on screen is reproducible; every order
is auditable.

## 2. Goals

1. One screen answers "what is my exposure right now, and is it working?".
2. One click produces a forecast-backed trade plan for the selected symbol and timeframe.
3. No order can reach the broker without an explicit human confirmation.
4. Every trade is explainable after the fact from stored data — forecast, rule version,
   risk inputs, LLM narrative, and the raw MCP responses.
5. The system degrades safely: missing model, missing data or missing broker connection
   means *no trade*, never a guessed one.

## 3. Non-goals

- Multi-user, authentication, or remote access. Bind to `127.0.0.1` only.
- Unattended/automatic trading. There is no scheduler that places orders.
- Portfolio optimisation across many symbols, options, or hedging logic.
- Training or fine-tuning models inside the app (that stays a research activity).
- Mobile layout.

## 4. Users and jobs

Single user: a discretionary day trader working on a laptop, in local time, moving between
M5 and M15 during the London and New York sessions.

| Job | Trigger | Success |
|---|---|---|
| Check exposure | Open dashboard | Equity, open P/L, risk used visible in < 2 s |
| Find a setup | Pick symbol + TF, Analyse | Forecast + signal + draft in one view |
| Take the trade | Press Execute, confirm | Filled order with SL/TP, visible in positions |
| Review the day | History tab | Closed trades with R multiples and stats |
| Avoid news risk | News tab | Calendar, blackout windows, bias note |

## 5. Functional requirements

### 5.1 Portfolio (`/`)

- **P-1** Show balance, equity, free margin, margin level, today's realised P/L and open P/L.
- **P-2** Show an equity growth chart from `equity_snapshots`, hourly granularity minimum,
  backfilled for the current day from deal history.
- **P-3** List open positions with symbol, side, lots, entry, current price, SL/TP, P/L,
  and distance-to-stop in ATR.
- **P-4** Show risk used: sum of open risk at stop as a percentage of equity, with the
  configured cap.
- **P-5** Refresh account and positions every 5 s while the tab is visible (polling; the
  MCP server has no push channel).

### 5.2 Watchlist and chart (`/watchlist`)

- **W-1** List symbols from the database. Adding a symbol calls
  `add_marketwatch_symbol` on MT5, validates the symbol specification, then persists it.
  Removing a symbol removes it from the database and from MT5 Market Watch.
- **W-2** Timeframe tabs: **M5, M15, M30, H1**. M1 is excluded from the UI by default
  (latency and noise); it can be enabled in settings for research only.
- **W-3** Candlestick chart for the selected symbol/TF with the last closed bar marked and
  the news blackout windows shaded on the time axis.
- **W-4** The **Analyse** button starts an analysis for `(symbol, timeframe, horizon)` and
  streams progress (`fetching bars → features → forecast 12/25 → signal → risk`).
- **W-5** Analysis results are cached per `(symbol, timeframe, last_closed_bar_time)`.
  Re-clicking on the same closed bar returns the stored result instantly.

### 5.3 Analysis drawer

- **A-1** Forecast fan chart: median path plus p10/p90 band from sampled paths.
- **A-2** Numeric summary: `p_up`, expected move (and in ATR), dispersion, projected R:R,
  ATR, spread, and the rule version that produced the signal.
- **A-3** Signal badge: `LONG`, `SHORT`, or `NO TRADE`, with the failed condition stated
  explicitly when there is no trade.
- **A-4** Draft order card: side, lots, entry reference, SL, TP, risk in USD and %, margin
  required, and the distance of each level in ATR.
- **A-5** Blackout banner when an analysis falls inside a news window; the draft is
  produced but not executable.
- **A-6** A short narrative written by the LLM (2–4 sentences) summarising the forecast and
  the news context. The narrative is clearly labelled as commentary and never contains
  numbers that differ from A-2/A-4.

### 5.4 Execution

- **E-1** Execute is disabled unless a valid, unexpired draft exists for the current bar.
- **E-2** Execute opens a confirmation dialog restating side, lots, SL, TP, risk in USD,
  and the worst-case loss including current spread and swap estimate.
- **E-3** On confirm, the backend re-validates and sends: positions → margin/profit
  calculation → `trade_check_market_order` → `trade_send_market_order`.
- **E-4** The system never sends a market order without both SL and TP.
- **E-5** A draft expires after 90 s or when price drifts more than 0.3×ATR from the
  reference price, whichever comes first. Stale drafts are rejected, not refreshed silently.
- **E-6** A draft can be executed at most once (idempotency key).
- **E-7** There is a global kill switch that rejects all executions while enabled.
- **E-8** Post-trade, poll for the resulting position ticket for up to 10 s and record the
  fill; if no position appears, record the failure with the raw broker response.

### 5.5 History (`/history`)

- **H-1** Table of closed trades: open/close time (local), symbol, TF at entry, side, lots,
  entry/exit, SL/TP, gross/net P/L, R multiple, duration, and the analysis that produced it.
- **H-2** Filters: date range, symbol, side, win/loss.
- **H-3** Summary stats for the selected range: trades, win rate, average R, expectancy in R,
  profit factor, max drawdown, average hold time.

### 5.6 News and fundamentals (`/news`)

- **N-1** Economic calendar for today and the next 7 days from the MT5 calendar, showing
  time (local), currency, event, impact, actual, forecast, previous.
- **N-2** Filter by impact and currency; XAUUSD-relevant currencies (USD, EUR, CNH, JPY)
  selected by default.
- **N-3** News feed from the terminal's news list with subject, time, category and body on
  demand.
- **N-4** A pre-session bias note generated from calendar + news + current forecast state,
  produced by the cloud LLM (NVIDIA NIM) and cached per session (Asia/London/New York).
- **N-5** Blackout windows are computed deterministically from the calendar and displayed on
  the chart and in the analysis drawer. The LLM does not decide blackouts.

### 5.7 Agent log (`/agent`)

- **A-7** Every agent run is listed with: request, provider used, model, latency, token
  usage, ordered tool calls with arguments and truncated results, and the final response.
- **A-8** A chat box accepts natural-language requests ("analyse XAUUSD M15", "add EURUSD to
  the watchlist", "what's my risk right now"). The agent may call read tools and the
  draft tool; it has no execution tool.
- **A-9** Runs are immutable and retained for 90 days.

## 6. Core flows

### 6.1 Analyse

```
UI: Analyse(symbol=XAUUSD, tf=M15)
  → POST /api/analyses
  → analysis service: fetch 288 closed bars (MCP get_chart_history)
  → validate: continuity, staleness, spread, symbol spec
  → features: ATR14, EMA20/50, realised vol
  → Kronos worker: 25 sampled paths, horizon 12
  → signal rule v1 → LONG / SHORT / NO TRADE
  → risk engine → lots, SL, TP, risk USD, cap checks, blackout check
  → persist analysis + draft
  → SSE progress events → UI drawer
```

### 6.2 Execute

```
UI: Execute(draft_id) + confirm
  → POST /api/drafts/{id}/execute
  → guard: draft unexpired, price drift ok, kill switch off, no open position on symbol
  → MCP: get_trading_open_positions
  → MCP: trade_order_calc_profit, trade_order_calc_margin
  → MCP: trade_check_market_order
  → MCP: trade_send_market_order
  → poll positions, persist order + deal, emit event
```

### 6.3 Add symbol

```
UI: + symbol → "XAUUSD"
  → agent or direct API
  → MCP add_marketwatch_symbol
  → MCP get_marketwatch_symbols (validate digits, tick size, min/max/step, stops level)
  → persist symbol row → chart loads
```

## 7. Signal and risk specification (deterministic, versioned)

All thresholds live in versioned config (`signal.v1`, `risk.v1`). Changing one requires a
new version string stored on every analysis.

### 7.1 Inputs

| Input | Value |
|---|---|
| Lookback | 288 bars (M5, M15, M30) · 512 bars (H1) |
| Horizon | 12 bars (M5/M15/M30) · 8 bars (H1) |
| Samples | 25 independent paths |
| Sampling | `T=1.0`, `top_p=0.9` |

### 7.2 Signal

```
p_up        = share of sampled paths whose horizon-end close > last close
edge        = mean(horizon-end close) - last close
edge_atr    = edge / ATR14
LONG  if  p_up >= 0.62 and edge_atr >= 0.60
SHORT if  p_up <= 0.38 and edge_atr <= -0.60
else NO TRADE
```

Additional vetoes: blackout window, spread above cap, stale bar, insufficient history.

### 7.3 Stops, target, size

```
SL distance = 1.5 × ATR14        (reference price: current bid/ask)
TP distance = 3.0 × ATR14        (R:R = 2.0)
risk_usd    = equity × risk_pct
lots        = risk_usd / (SL_distance × contract_size)
lots        = floor(lots / volume_step) × volume_step, clamped to [min, max]
```

XAUUSD on this broker: `contract_size = 100`, so 1 lot loses **$100 per $1** of adverse move.
0.01 lot = $1 per $1. SL/TP are rounded to `digits` (2) and must respect
`trade_stops_level`.

### 7.4 Risk caps (`risk.v1`)

| Rule | Default |
|---|---|
| Risk per trade | 0.5% of equity (allowed 0.25–1.0%) |
| Max open positions per symbol | 1 |
| Max total open risk | 2.0% of equity |
| Daily realised loss limit | 3.0% → auto-disable execution for the day |
| Max spread at entry | 30 points ($0.30) |
| Blackout | 15 min before/after high-impact USD/XAU events; 30 min for NFP, CPI, FOMC |
| Draft TTL | 90 s |
| Max price drift | 0.3 × ATR |
| Kill switch | manual, blocks all execution |

## 8. Architecture

### 8.1 Context

```
Browser (React SPA, localhost)
   │  REST + SSE
   ▼
FastAPI backend ("ignite-desk-api")
   ├── Agent orchestrator      LLM provider chain, tool loop, guardrails
   ├── Analysis service        bars → features → forecast → signal → draft
   ├── Risk engine             sizing, caps, blackout, idempotency
   ├── Execution service       order lifecycle + reconciliation
   ├── Store                   SQLite (WAL), caches
   └── MCP client ────────────► MT5 MCP server  http://127.0.0.1:22346/mcp
                                     │
                                     ▼  MetaTrader 5 terminal
Kronos worker (separate process, torch CPU)
   ◄── internal HTTP 127.0.0.1:8765
```

Two processes are mandatory, not stylistic:

- **Kronos worker** isolates multi-second CPU inference from the request loop, loads weights
  once, and can restart without dropping the API. Queue concurrency 1 (one model instance).
- **API** stays responsive for the portfolio poll and SSE while an analysis runs.

### 8.2 MCP integration

The MT5 MCP server is a **Streamable HTTP** MCP endpoint with a bearer token. The backend is
a first-class MCP client (`initialize` → `tools/list` → `tools/call`), pinned to protocol
`2025-06-18`. Session id is kept per backend process and re-established on 404/410.

Tool allowlist (everything else is blocked at the client layer):

| Purpose | MCP tool |
|---|---|
| Account | `get_trading_account_info` |
| Bars | `get_chart_history` |
| Symbol specs / watchlist | `get_marketwatch_symbols`, `add_marketwatch_symbol`, `remove_marketwatch_symbol` |
| Positions / orders | `get_trading_open_positions`, `get_trading_history_positions`, `get_trading_history_orders` |
| Pre-trade checks | `trade_order_calc_margin`, `trade_order_calc_profit`, `trade_check_market_order` |
| Execution | `trade_send_market_order`, `trade_modify_sl_tp`, `trade_close_single_position` |
| Calendar / news | `economic_calendar_list_values`, `economic_calendar_list_countries`, `get_news_list`, `get_news_by_id` |
| Time / health | `get_time_information`, `terminal_get_info`, `get_workspace_info` |

Execution tools are **not exposed to the LLM**. They are called only by the execution
service, after the confirmation endpoint has been hit.

### 8.3 Agent runtime

The agent is a tool-calling loop with a strict budget: max 6 tool calls, 45 s wall clock,
one retry per provider. If it fails, the deterministic pipeline still returns an analysis
and the narrative is replaced by a template.

Providers are pluggable, all OpenAI-compatible:

| Provider | Base URL | Default model | Used for |
|---|---|---|---|
| `nim` | `https://integrate.api.nvidia.com/v1` | `meta/llama-3.3-70b-instruct` | Narrative, news bias note, chat (default) |
| `local` | `http://127.0.0.1:11434/v1` | `qwen3:8b` | Fallback, offline use, private mode |
| `extra` | configurable | — | Optional third endpoint |

Fallback order is `nim → local → template`. Keys come from `.env`, never from the database
or the UI, and are never included in prompts or logs.

**Tool surface exposed to the LLM (read + draft only):**

```
list_symbols()                          get_account_snapshot()
add_symbol_to_watchlist(symbol)         get_positions()
remove_symbol_from_watchlist(symbol)    get_trade_history(from, to)
get_bars(symbol, timeframe, count)      get_economic_calendar(from, to)
get_news(limit, filter)                 run_analysis(symbol, timeframe)
get_analysis(analysis_id)               draft_order(analysis_id)
explain(analysis_id)                    get_risk_state()
```

`draft_order` creates or returns the draft attached to an analysis. There is deliberately no
`execute` tool.

### 8.4 Time

Canonical storage is **UTC**. Ingestion converts MT5 trade-server time to UTC once, using
the offset from `get_time_information`; nothing downstream re-interprets it. All API
timestamps are ISO-8601 with `Z`. The UI renders in the operator's local timezone and
labelled with its abbreviation. Bar timestamps, calendar events, news and trade history all
follow this rule, so cross-source comparisons (e.g. blackout vs bar) are always valid.

Day boundaries used by the daily-loss rule are computed in local time.

### 8.5 Data model (SQLite)

| Table | Key columns |
|---|---|
| `symbols` | symbol, digits, point, contract_size, tick_value, volume_min/max/step, stops_level, added_at |
| `analyses` | id, symbol, timeframe, last_bar_time, lookback, horizon, samples, model_id, model_rev, signal_version, risk_version, p_up, edge, edge_atr, atr, spread, signal, reasons_json, created_at |
| `forecast_paths` | analysis_id, sample_idx, path_json (or compressed blob) |
| `drafts` | id, analysis_id, side, lots, ref_price, sl, tp, risk_usd, risk_pct, margin, expires_at, state, idempotency_key |
| `orders` | id, draft_id, ticket, symbol, side, lots, requested_price, filled_price, sl, tp, state, raw_json, created_at |
| `deals` | deal_id, order_id, position_id, entry, price, profit, commission, swap, time |
| `positions_cache` | ticket, symbol, side, lots, price_open, sl, tp, profit, updated_at |
| `equity_snapshots` | ts, balance, equity, margin, free_margin |
| `calendar_events` | event_id, time_utc, currency, name, impact, actual, forecast, previous |
| `news_items` | id, time_utc, subject, category, body, fetched_at |
| `agent_runs` | id, request, provider, model, latency_ms, tokens_in, tokens_out, tool_calls_json, response, created_at |
| `settings` | key, value (kill_switch, risk_pct, enabled_timeframes, …) |
| `audit_log` | ts, actor, action, payload_json, result |

### 8.6 API surface

```
GET    /api/health
GET    /api/account
GET    /api/portfolio/equity?range=1d|1w|1m|all
GET    /api/positions
GET    /api/symbols            POST /api/symbols            DELETE /api/symbols/{s}
GET    /api/bars?symbol&tf&count
POST   /api/analyses           GET  /api/analyses/{id}
GET    /api/analyses/latest?symbol&tf
POST   /api/drafts/{id}/execute        (requires confirm token from the UI dialog)
GET    /api/trades?from&to&symbol      GET /api/stats?from&to
GET    /api/calendar?from&to           GET /api/news?limit
POST   /api/agent/chat                 GET /api/agent/runs
GET    /api/settings                   PUT /api/settings
GET    /api/events                     (SSE: analysis progress, fills, equity ticks)
```

`POST /api/drafts/{id}/execute` requires `{"confirm": true, "token": "<issued by the
confirmation dialog>"}`; the token is bound to the draft id and expires with it.

### 8.7 Frontend

React 18 + Vite + TypeScript. TanStack Query for server state, `lightweight-charts` for
candles and the equity curve, Tailwind for layout. No client-side business logic: the UI
renders what the API returns and never computes a signal, size or stop.

## 9. Failure modes

| Failure | Behaviour |
|---|---|
| MCP server unreachable | Read-only mode; cached data labelled stale; Execute disabled; banner on every screen |
| MT5 terminal disconnected | Same as above; no retry storm (backoff 2→30 s) |
| Kronos worker down | Analyse returns 503 with a clear message; no fallback signal |
| Kronos inference timeout (> 60 s) | Analysis fails, draft not created |
| LLM provider down | Deterministic analysis proceeds; narrative replaced by a template |
| Insufficient history | Analysis refused with the actual bar count |
| Spread above cap | Draft produced but not executable, reason shown |
| Draft expired / price drifted | Execute returns 409 with the reason and a "Re-analyse" action |
| Order rejected by broker | Raw broker comment stored and shown; no automatic retry |
| Backend restart mid-trade | Reconciliation job recovers positions and deals from MT5 within 30 s |

Every failure path is **fail-closed**: it may block a trade, it may never invent one.

## 10. Security

- Bind `127.0.0.1`; no CORS origins beyond the local dev server.
- MCP bearer token and LLM keys only in `.env` (gitignored). `.env.example` documents names.
- The MCP token currently present in the opencode config should be rotated once the backend
  owns it, and never committed.
- Trade endpoints require the confirmation token; there is no unauthenticated order path.
- All tool calls are audit-logged with arguments and truncated results.
- Kill switch persists across restarts.

## 11. Observability

- Structured JSON logs to `logs/` with a request id per analysis and per execution.
- Agent runs persisted with provider, model, latency, tokens and tool trace.
- `/api/health` reports: MCP reachable, terminal connected, Kronos worker ready (model id,
  load time), queue depth, LLM providers configured.
- Every analysis stores model id + revision and config versions, so a result can be
  reproduced exactly.

## 12. Performance budgets (measured on the target machine)

Target machine: i5-5300U, 4 cores, 12 GB RAM, no CUDA. Kronos on CPU, `torch 2.15.0+cpu`.

| Operation | Budget | Notes |
|---|---|---|
| Portfolio load (cached) | < 2 s | account + positions + snapshots |
| Equity chart load | < 1 s | 1 440 snapshots |
| Bars fetch (288) | < 1 s | MCP round-trip |
| Analysis, M15, 25 samples | **14.3 s** measured | target < 60 s |
| Analysis, M5, 25 samples | **14.8 s** measured | must stay under ~120 s |
| Forecast cache hit | < 100 ms | keyed by closed bar |

**Selected model: `Kronos-mini` (4.1M).** It is 4.8× faster than `Kronos-small` at an
identical input shape (14.3 s vs 69.0 s for 25 paths) and leaves ~4.5 minutes of headroom on
a 5-minute bar. Forecast quality for XAUUSD is unproven for every checkpoint, so the extra
cost of a larger model is not justified until walk-forward testing demonstrates it.

## 13. Testing

| Layer | Approach |
|---|---|
| Signal rule | Unit tests with fixed forecast paths; boundary cases at p_up 0.61/0.62/0.38/0.39 |
| Risk engine | Unit tests: sizing across equity/lots/step, caps, daily loss, blackout windows, TTL, drift |
| MCP client | Contract tests against a fake MCP server replaying recorded responses |
| Analysis graph | Golden test on recorded bars → deterministic output (fixed seed) |
| Execution | Dry-run mode against demo account; assert order payloads never exceed caps |
| E2E | Playwright: add symbol → analyse → confirm dialog → execute (dry-run) → history row |
| Reconciliation | Kill backend mid-flow, assert recovery |

## 14. Phases and acceptance

| Phase | Deliverable | Done when |
|---|---|---|
| **P0** | Latency spike, model choice | Appendix A filled; chosen model inside the M5 budget |
| **P1** | Backend core | CLI analyse on live XAUUSD M15 produces a persisted analysis + draft; mock execution test passes |
| **P2** | Dashboard MVP | Portfolio, watchlist (add/remove), chart, analyse, confirm-execute, history all working on demo |
| **P3** | News | Calendar, news feed, blackout veto, NIM bias note |
| **P4** | Hardening | Reconciliation, kill switch, daily loss, walk-forward report on 12 months of M15 |
| **P5** | Multi-symbol | Add EURUSD via the UI without code changes |

## 15. Risks

| Risk | Mitigation |
|---|---|
| Kronos was not trained on XAUUSD/MT5 feeds — out-of-distribution | Walk-forward validation vs a naive baseline before P4 sign-off; fine-tuning is a separate research track |
| Small sample of trades → misleading win rate | Report R multiples and expectancy with sample size; no claims before 50 trades |
| CPU inference too slow for M5 | Measured in P0; else fall back to M15 or fewer samples |
| MT5 MCP server availability | Fail-closed; health banner; backoff reconnect |
| Broker spec differences between demo and live | Re-read symbol spec on add; block execution if `tick_value`/`stops_level` mismatch expectations |
| LLM hallucinating numbers | LLM never supplies numbers; narrative is generated from a fixed JSON payload and checked for numeric consistency |
| Overfitting the signal thresholds | Thresholds fixed before validation; any change requires a new version and a fresh out-of-sample test |

## Appendix A — P0 latency measurements

Target machine: i5-5300U (2C/4T), 12 GB RAM, no CUDA, `torch 2.15.0+cpu`.
Harness: `spikes/kronos_latency/bench.py`. Synthetic OHLCV; latency depends on tensor shape,
not price values. Lookback 288, horizon 12, `T=1.0`, `top_p=0.9`, torch default threads.

| Model | TF | Load (cached) | Per sample | 25-path analysis | RSS |
|---|---|---|---|---|---|
| **Kronos-mini** (4.1M) | M15 | 36.5 s cold / 1.7–3.0 s warm | **0.56 s** | **14.3 s** | 306 MB |
| **Kronos-mini** (4.1M) | M5 | 1.7 s | 0.61 s | 14.8 s | 292 MB |
| Kronos-small (24.7M) | M15 | 2.7 s | 2.81 s | 69.0 s | 371 MB |
| Kronos-base (102M) | M15 | not completed | — | — | — |

M5 and M15 cost the same because the tensors have the same shape. Sequential and batched
sampling also cost the same — the bottleneck is the autoregressive loop, not the batch
dimension. Base was cancelled and is not quoted.

**Decision: Kronos-mini.** Full write-up in `spikes/kronos_latency/results.md`.
