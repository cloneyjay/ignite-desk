# Ignite Desk

A local, single-operator trading desk for MetaTrader 5: a web dashboard where an AI agent
mediates between a Kronos price forecaster, the MT5 MCP server (market data, economic
calendar, order execution) and you.

Launch scope: **XAUUSD, demo account**. Architected for additional symbols and live accounts.

## Design invariants

- The LLM can **draft** a trade. It can never **execute** one. Execution is a separate
  endpoint that requires a draft id plus an explicit confirmation from the UI.
- All numbers come from a deterministic, versioned analysis graph. LLM output is narrative only.
- Every service fails **closed**: no data or no model means no trade, never a guessed one.
- 100% local. The only outbound calls are the optional cloud LLM provider you configure.

## Layout

```
ignite-desk/
├─ backend/            FastAPI app: MCP client, analysis graph, risk engine, execution
├─ frontend/           React + Vite dashboard
├─ spikes/             Throwaway measurements (kept for the record)
│  └─ kronos_latency/  P0: CPU inference latency per model / timeframe
├─ vendor/kronos/      Kronos upstream (git submodule)
├─ docs/               PRD, architecture, decision records
└─ data/               SQLite, caches (gitignored)
```

## Quick start (dev)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt

copy .env.example .env      # fill MT5_MCP_TOKEN and keys
```

Kronos lives in `vendor/kronos` (submodule). Clone with:

```powershell
git submodule update --init --recursive
```

### Run the backend

Two processes: the Kronos worker and the CLI/API.

```powershell
# terminal 1 - model worker on 127.0.0.1:8765
.\.venv\Scripts\python.exe -m backend.ignite.forecasting.worker

# terminal 2 - check both sides
.\.venv\Scripts\python.exe -m backend.ignite.cli health

# run one analysis (25 sampled paths)
.\.venv\Scripts\python.exe -m backend.ignite.cli analyse --symbol XAUUSD --tf M15 --save
```

Example output:

```
Ignite Desk  |  XAUUSD M15  |  2026-11-12T08:58:12+00:00
bars         288 closed   2026-11-09 02:45:00 -> 2026-11-12 08:30:00 UTC
price        3941.54   ATR 8.804   spread 13 pts   trend down
forecast     25 paths x 12 bars   Kronos-mini   14.2s
distribution p_up 0.76   edge +7.54 (+0.86 ATR)   target 3950.23  p10 3936.04  p90 3960.02
signal       LONG
draft        0.01 lots   entry ~3931.06   SL 3917.85   TP 3957.47
risk         13.21 USD (0.449%)   R:R 2.00
blocked      price drifted 1.19 ATR from the last closed bar (3941.54 -> 3931.06), max 0.30
```

The last line is the drift guard doing its job: the signal was valid at the last
closed bar, but price had already run by more than the allowed fraction of ATR, so
the draft is not executable.

Tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

## API (P1)

```powershell
# terminal 3 - API on 127.0.0.1:8000
.\.venv\Scripts\python.exe -m backend.ignite.api
```

Interactive docs: `http://127.0.0.1:8000/api/docs`

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | MCP, terminal, Kronos, kill switch, clock |
| GET | `/api/account` | balance/equity/positions, open risk, today's P/L |
| GET | `/api/portfolio/equity?range=1d\|1w\|1m\|all` | equity snapshots |
| GET | `/api/positions` | open positions |
| GET/POST | `/api/symbols`, `DELETE /api/symbols/{s}` | watchlist (mirrors MT5 Market Watch) |
| GET | `/api/bars?symbol&tf&count` | closed bars, UTC |
| POST | `/api/analyses` | start an analysis job (202 + `job_id`) |
| GET | `/api/jobs/{id}` | job progress / result |
| GET | `/api/analyses/{id}`, `/api/analyses/latest?symbol&tf` | stored analysis + fan paths + draft |
| POST | `/api/analyses/{id}/draft` | mint a fresh draft for an existing analysis |
| GET | `/api/drafts/{id}` | draft + live executability checks |
| POST | `/api/drafts/{id}/confirm` | opens the 90 s window, returns a single-use token |
| POST | `/api/drafts/{id}/execute` | `{confirm: true, token}` - re-validates, then sends |
| GET | `/api/trades`, `/api/stats`, `/api/orders` | history, stats, local order audit |
| GET | `/api/calendar`, `/api/blackouts`, `/api/news` | MT5 calendar/news, deterministic blackouts |
| GET/PUT | `/api/settings` | kill switch, risk %, limits |
| GET | `/api/events` | SSE: analysis progress, draft, fill, kill switch |

Execution is a three-step handshake by design:

```
GET  /api/drafts/{id}            -> checks[] and executable flag
POST /api/drafts/{id}/confirm    -> {token} (bound to the draft, expires with it)
POST /api/drafts/{id}/execute    -> {confirm: true, token}
```

The backend re-validates everything at execute time: state, expiry, kill switch,
price drift, spread, open position on the symbol, margin, economic blackout,
`trade_check_market_order`. The LLM has no path to this endpoint.

## P0 spike: Kronos CPU latency

Decides which Kronos checkpoint is viable for day trading on this machine
(i5-5300U, 4 cores, no CUDA).

```powershell
.\.venv\Scripts\python.exe spikes\kronos_latency\bench.py --model mini  --lookback 288 --horizon 12
.\.venv\Scripts\python.exe spikes\kronos_latency\bench.py --model small --lookback 288 --horizon 12
```

Results go to `spikes/kronos_latency/results.md`.

## Status

- [x] Repo scaffold
- [x] P0 latency spike (Kronos-mini selected)
- [x] PRD + architecture spec
- [x] P1 backend core (MCP client, bars, analysis graph, CLI)
- [x] P1 API: REST + SSE, confirmation-token execution, calendar/blackouts
- [ ] P2 dashboard MVP
- [ ] P3 news narrative / agent chat
- [ ] P4 hardening / walk-forward
- [ ] P5 multi-symbol
