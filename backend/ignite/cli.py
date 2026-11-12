"""Command line entry point.

  python -m backend.ignite.cli health
  python -m backend.ignite.cli analyse --symbol XAUUSD --tf M15
"""

from __future__ import annotations

import argparse
import json
import sys

import numpy as np

from backend.ignite.analysis.graph import run_analysis
from backend.ignite.analysis.risk import RiskConfig
from backend.ignite.config import load_settings
from backend.ignite.forecasting.client import ForecastClient, ForecastError
from backend.ignite.market.time import Clock
from backend.ignite.mcp.client import MCPClient, MCPError
from backend.ignite.store.db import Store


def _account_equity(mcp: MCPClient) -> float:
    payload = mcp.call_tool("get_trading_account_info")
    account = payload.get("account", {})
    equity = account.get("equity")
    if not equity:
        raise RuntimeError("account equity unavailable")
    return float(equity)


def cmd_health(args: argparse.Namespace) -> int:
    settings = load_settings()
    with MCPClient(settings.mcp.url, settings.mcp.headers, settings.mcp.timeout_s) as mcp:
        tools = mcp.list_tools()
        account = mcp.call_tool("get_trading_account_info").get("account", {})
        clock = Clock.from_mcp(mcp)
        print(f"mcp          ok   {len(tools)} tools   {settings.mcp.url}")
        print(f"server       {account.get('server')}  login {account.get('login')}  "
              f"{account.get('type')}  {account.get('currency')}")
        print(f"equity       {account.get('equity')}   balance {account.get('balance')}   "
              f"free margin {account.get('margin_free')}")
        print(f"server clock UTC{clock.offset.total_seconds() / 3600:+.0f}h  "
              f"now {clock.server_now()} server")

    client = ForecastClient(settings.kronos_worker_url)
    try:
        health = client.health()
        print(f"kronos       {health.get('model')}  ready={health.get('ready')}  "
              f"load {health.get('load_s')}s  threads {health.get('threads')}")
    except ForecastError as exc:
        print(f"kronos       DOWN  {exc}")
        print("             start it with: python -m backend.ignite.forecasting.worker")
    finally:
        client.close()
    return 0


def cmd_analyse(args: argparse.Namespace) -> int:
    settings = load_settings()
    client = ForecastClient(settings.kronos_worker_url)
    try:
        health = client.health()
        if not health.get("ready"):
            print("kronos worker is not ready", file=sys.stderr)
            return 2
    except ForecastError as exc:
        print(f"kronos worker unreachable: {exc}", file=sys.stderr)
        print("start it with: python -m backend.ignite.forecasting.worker", file=sys.stderr)
        return 2

    try:
        with MCPClient(settings.mcp.url, settings.mcp.headers, settings.mcp.timeout_s) as mcp:
            clock = Clock.from_mcp(mcp)
            equity = _account_equity(mcp)
            result = run_analysis(
                mcp,
                clock,
                client,
                args.symbol,
                args.tf,
                equity,
                horizon=args.horizon,
                samples=args.samples,
                risk_config=RiskConfig(max_drift_atr=settings.max_drift_atr),
            )

            if args.save:
                store = Store(settings.db_path)
                store.save_analysis(result, settings.draft_ttl_s)
                store.snapshot_equity(
                    float(mcp.call_tool("get_trading_account_info")["account"]["balance"]),
                    equity,
                    0.0,
                    0.0,
                )
                store.close()
    except (MCPError, RuntimeError, ValueError) as exc:
        print(f"analysis failed: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()

    if args.json:
        payload = {
            "analysis_id": result.analysis_id,
            "symbol": result.symbol,
            "timeframe": result.timeframe,
            "last_bar_time": str(result.last_bar_time),
            "model_id": result.model_id,
            "infer_s": result.infer_s,
            "samples": result.samples,
            "horizon": result.horizon,
            "features": {
                "last_close": result.features.last_close,
                "atr": result.features.atr,
                "trend": result.features.trend,
                "spread_points": result.features.spread_points,
            },
            "signal": {
                "side": result.signal.side,
                "p_up": result.signal.p_up,
                "edge": result.signal.edge,
                "edge_atr": result.signal.edge_atr,
                "reasons": list(result.signal.reasons),
            },
            "draft": None if result.draft is None else result.draft.__dict__,
        }
        print(json.dumps(payload, indent=2, default=str))
        return 0

    f = result.features
    s = result.signal
    median = np.median(result.paths[:, -1])
    p10, p90 = np.percentile(result.paths[:, -1], [10, 90])

    print(f"Ignite Desk  |  {result.symbol} {result.timeframe}  |  {result.created_at}")
    print(f"bars         {len(result.bars)} closed   "
          f"{result.bars['time'].iloc[0]} -> {result.last_bar_time} UTC")
    print(f"price        {f.last_close:.2f}   ATR {f.atr:.3f}   "
          f"spread {f.spread_points:.0f} pts   trend {f.trend}")
    print(f"forecast     {result.samples} paths x {result.horizon} bars   "
          f"{result.model_id.split('/')[-1]}   {result.infer_s:.1f}s")
    print(f"distribution p_up {s.p_up:.2f}   edge {s.edge:+.2f} ({s.edge_atr:+.2f} ATR)   "
          f"target {median:.2f}  p10 {p10:.2f}  p90 {p90:.2f}")
    print(f"signal       {s.side.upper()}")
    if s.side == "none":
        for reason in s.reasons:
            print(f"  why        {reason}")
    if result.draft is not None:
        d = result.draft
        print(f"draft        {d.lots:g} lots   entry ~{d.reference_price:.2f}   "
              f"SL {d.sl:.2f}   TP {d.tp:.2f}")
        print(f"risk         {d.risk_usd:.2f} USD ({d.risk_pct:.3%})   R:R {d.rr:.2f}")
        if d.blocked:
            print(f"blocked      {d.block_reason}")
    if args.save:
        print(f"saved        analysis {result.analysis_id[:12]}  draft {result.draft_id}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="ignite")
    sub = parser.add_subparsers(dest="command", required=True)

    p_health = sub.add_parser("health", help="check MCP and Kronos worker")
    p_health.set_defaults(func=cmd_health)

    p = sub.add_parser("analyse", help="run the analysis graph")
    p.add_argument("--symbol", default="XAUUSD")
    p.add_argument("--tf", default="M15", choices=["M5", "M15", "M30", "H1"])
    p.add_argument("--samples", type=int, default=25)
    p.add_argument("--horizon", type=int, default=None)
    p.add_argument("--json", action="store_true")
    p.add_argument("--save", action="store_true")
    p.set_defaults(func=cmd_analyse)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
