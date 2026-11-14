"""Analyst: multi-source market read → deterministic analysis → draft.

Gathers live market data (quote, bars, structure), fundamentals (calendar,
news), Kronos forecast, and memory, then runs the deterministic analysis graph
to produce a signal and an optional draft order.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.ignite.market.bars import fetch_bars
from backend.ignite.market.structure import compute_structure
from backend.ignite.services.analysis_service import start_analysis
from backend.ignite.services.runtime import Runtime


@dataclass(frozen=True)
class AnalystResult:
    """Outcome of one symbol/timeframe assessment."""

    symbol: str
    timeframe: str
    signal: str  # "LONG" | "SHORT" | "NONE"
    p_up: float
    edge_atr: float
    dispersion: float
    draft_id: str | None
    rationale: str
    data: dict[str, Any]


class Analyst:
    """Reads the market from every available source and produces an analysis."""

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt

    def assess(self, symbol: str, timeframe: str) -> AnalystResult:
        """Run the full multi-source analysis for one symbol/timeframe."""
        now = datetime.now(timezone.utc)

        # --- live market data ---
        bid, ask = self.rt.quote(symbol)
        spec = self.rt.spec(symbol)
        spread = self.rt.spread(symbol)

        # --- bars & structure ---
        frame = fetch_bars(self.rt.mcp, self.rt.clock(), symbol, timeframe, 120)
        structure = compute_structure(frame)

        # --- fundamentals ---
        calendar_events = self.rt.news.calendar(
            now - timedelta(hours=2), now + timedelta(hours=2)
        )
        headlines = self.rt.news.news(
            now - timedelta(hours=48), now + timedelta(minutes=5), 10
        )

        # --- Kronos forecast ---
        lookback = 288
        bars = fetch_bars(self.rt.mcp, self.rt.clock(), symbol, timeframe, lookback)
        forecast_result = self.rt.forecast.forecast(
            bars, [], samples=25, lookback=lookback
        )

        # --- memory ---
        episodes = self.rt.store.episodic_query(
            symbol=symbol, type="analysis", limit=5
        )
        patterns = self.rt.store.semantic_recall(
            query=f"{symbol} {timeframe}", tags=[], limit=5
        )

        # --- deterministic analysis graph → draft ---
        job = start_analysis(self.rt, symbol, timeframe)
        analysis_id = self._wait_for_job(job)

        analysis = self.rt.store.get_analysis(analysis_id)
        draft = self.rt.store.draft_for_analysis(analysis_id)

        signal = str(analysis.get("signal", "NONE")).upper()
        p_up = float(analysis.get("p_up", 0.5))
        edge_atr = float(analysis.get("edge_atr", 0.0))
        dispersion = float(analysis.get("dispersion", 1.0))
        draft_id = draft["id"] if draft else None

        rationale = self._rationale(
            symbol, timeframe, signal, p_up, edge_atr, structure,
            forecast_result, calendar_events, draft,
        )

        return AnalystResult(
            symbol=symbol,
            timeframe=timeframe,
            signal=signal,
            p_up=p_up,
            edge_atr=edge_atr,
            dispersion=dispersion,
            draft_id=draft_id,
            rationale=rationale,
            data={
                "quote": {"bid": bid, "ask": ask, "spread": spread, "spec": {
                    "digits": spec.digits,
                    "point": spec.point,
                    "contract_size": spec.contract_size,
                }},
                "structure": structure,
                "calendar": calendar_events,
                "headlines": headlines,
                "forecast": forecast_result,
                "memory": {"episodes": episodes, "patterns": patterns},
            },
        )

    def _wait_for_job(self, job) -> str:
        """Poll the analysis job until it completes or fails."""
        start = time.monotonic()
        timeout = 120.0
        while True:
            job_status = self.rt.job(job.id)
            if not job_status:
                raise RuntimeError(f"job {job.id} disappeared")
            if job_status.status == "done":
                analysis_id = job_status.analysis_id
                if analysis_id is None:
                    raise RuntimeError("analysis job completed with no analysis id")
                return analysis_id
            if job_status.status == "failed":
                raise RuntimeError(job_status.error or "analysis failed")
            if time.monotonic() - start > timeout:
                raise RuntimeError(f"analysis timed out after {timeout}s")
            time.sleep(0.5)

    @staticmethod
    def _rationale(
        symbol: str,
        timeframe: str,
        signal: str,
        p_up: float,
        edge_atr: float,
        structure: dict[str, Any],
        forecast_result: dict[str, Any],
        calendar_events: list[dict[str, Any]],
        draft: dict[str, Any] | None,
    ) -> str:
        parts: list[str] = []
        if signal == "NONE":
            parts.append(
                f"No tradeable edge for {symbol} {timeframe}: "
                f"p_up {p_up:.2f}, edge {edge_atr:+.2f} ATR — staying flat."
            )
        else:
            parts.append(
                f"Kronos puts {signal} probability at {p_up:.0%} "
                f"with {edge_atr:+.2f} ATR edge on {timeframe}."
            )
            if draft:
                parts.append(
                    f"Draft: {draft['lots']:g} lots at "
                    f"{draft['reference_price']:.2f}, SL {draft['sl']:.2f}, "
                    f"TP {draft['tp']:.2f}, risk {draft.get('risk_pct', 0):.2%}."
                )
            else:
                parts.append("No draft produced — setup not executable.")

        high_impact = [
            e for e in calendar_events
            if str(e.get("importance", "")).lower() == "high"
        ]
        if high_impact:
            names = ", ".join(e.get("name", "event") for e in high_impact[:3])
            parts.append(f"High-impact news pending: {names}.")

        return " ".join(parts)
