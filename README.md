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
pip install -r spikes\kronos_latency\requirements.txt

copy .env.example .env      # fill MT5_MCP_TOKEN and keys
```

Kronos lives in `vendor/kronos` (submodule). Clone with:

```powershell
git submodule update --init --recursive
```

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
- [ ] P1 backend core
- [ ] P2 dashboard MVP
- [ ] P3 news & calendar
- [ ] P4 hardening / walk-forward
- [ ] P5 multi-symbol
