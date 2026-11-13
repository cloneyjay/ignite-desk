"""Process-wide runtime: one MCP session, one store, one event bus.

Sync by design. FastAPI runs handlers in a thread pool, and the analysis job
runs in its own thread, so everything here must be thread-safe but must not
touch the event loop directly (the bus handles the hop).
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from backend.ignite.agent.config import AgentConfig
from backend.ignite.analysis.features import Features
from backend.ignite.analysis.risk import RiskConfig, SymbolSpec
from backend.ignite.config import Settings
from backend.ignite.forecasting.client import ForecastClient
from backend.ignite.knowledge.loader import sync_cards
from backend.ignite.llm.client import LLMClient
from backend.ignite.market import bars as bar_mod
from backend.ignite.market.symbols import get_spec, quote, spread_points
from backend.ignite.market.time import Clock
from backend.ignite.mcp.client import MCPClient, MCPError
from backend.ignite.services.broker import BrokerError
from backend.ignite.services.config_service import ConfigService
from backend.ignite.services.events import EventBus
from backend.ignite.services.ledger import Ledger
from backend.ignite.services.news import NewsService
from backend.ignite.store.db import Store, utc_now

CLOCK_TTL_S = 900
SPEC_TTL_S = 3600


@dataclass
class Job:
    id: str
    symbol: str
    timeframe: str
    status: str = "queued"
    step: str = "queued"
    message: str = ""
    pct: int = 0
    analysis_id: str | None = None
    error: str | None = None
    cached: bool = False
    created_at: str = field(default_factory=utc_now)
    progress: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.id,
            "status": self.status,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "step": self.step,
            "message": self.message,
            "pct": self.pct,
            "analysis_id": self.analysis_id,
            "error": self.error,
            "cached": self.cached,
            "created_at": self.created_at,
            "progress": list(self.progress),
        }


class Runtime:
    def __init__(
        self,
        settings: Settings,
        mcp_client: MCPClient | Any | None = None,
        forecast_client: ForecastClient | Any | None = None,
        llm_client: LLMClient | Any | None = None,
    ) -> None:
        self.settings = settings
        self.store = Store(settings.db_path)
        self.events = EventBus()
        self.mcp = mcp_client or MCPClient(
            settings.mcp.url, settings.mcp.headers, settings.mcp.timeout_s
        )
        self.forecast = forecast_client or ForecastClient(settings.kronos_worker_url)
        self.llm = llm_client or LLMClient(settings.llm)

        self.knowledge = None
        try:
            self.knowledge = sync_cards(self.store, settings.knowledge_dir)
        except Exception as exc:  # noqa: BLE001 - health reports the failure
            self.knowledge = exc

        self.jobs: dict[str, Job] = {}
        self.execution_lock = threading.Lock()

        self._jobs_lock = threading.Lock()
        self._mcp_lock = threading.Lock()
        self._mcp_ready = False
        self._clock: Clock | None = None
        self._clock_ts = 0.0
        self._specs: dict[str, tuple[float, SymbolSpec]] = {}
        self._atr_cache: dict[tuple[str, str], tuple[float, float]] = {}
        self._realised_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._snapshot_ts = 0.0
        self._tokens: dict[str, tuple[str, float]] = {}
        self._tokens_lock = threading.Lock()

        self.news = NewsService(
            self.mcp,
            self.clock,
            pre_minutes=settings.news_pre_minutes,
            post_minutes=settings.news_post_minutes,
            currencies=tuple(
                code.strip().upper()
                for code in settings.news_currencies.split(",")
                if code.strip()
            ),
        )

        self._seed_config = AgentConfig.from_env()
        self.config_service = ConfigService(self.store, self._seed_config, self.events)
        self.ledger = Ledger(self)

    # ----------------------------------------------------------------- lifecycle

    @property
    def agent_config(self) -> AgentConfig:
        """Backwards-compatible view of the single persisted config."""
        return self.config_service.get()

    def config(self) -> AgentConfig:
        return self.config_service.get()

    def shutdown(self) -> None:
        try:
            self.mcp.close()
        finally:
            try:
                self.forecast.close()
            finally:
                try:
                    close = getattr(self.llm, "close", None)
                    if close is not None:
                        close()
                finally:
                    self.store.close()

    def seed_symbols(self) -> None:
        if self.store.list_symbols():
            return
        try:
            self._ensure_mcp()
            spec = get_spec(self.mcp, "XAUUSD")
            self.store.add_symbol(spec.__dict__)
        except Exception:  # noqa: BLE001 - health reports the real problem
            pass

    # ----------------------------------------------------------------------- MCP

    def _ensure_mcp(self) -> None:
        if self._mcp_ready:
            return
        with self._mcp_lock:
            if self._mcp_ready:
                return
            try:
                self.mcp.initialize()
            except httpx.HTTPError as exc:
                raise BrokerError(f"MT5 terminal unreachable: {exc}") from exc
            except MCPError as exc:
                raise BrokerError(f"MT5 MCP handshake failed: {exc}") from exc
            self._mcp_ready = True

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        self._ensure_mcp()
        try:
            return self.mcp.call_tool(name, arguments or {})
        except httpx.HTTPError as exc:
            self._mcp_ready = False
            raise BrokerError(f"MT5 terminal unreachable: {exc}") from exc
        except MCPError as exc:
            raise BrokerError(f"{name}: {exc}") from exc

    def clock(self, force: bool = False) -> Clock:
        now = time.monotonic()
        if not force and self._clock and now - self._clock_ts < CLOCK_TTL_S:
            return self._clock
        self._ensure_mcp()
        try:
            clock = Clock.from_mcp(self.mcp)
        except (MCPError, httpx.HTTPError) as exc:
            raise BrokerError(f"could not read broker clock: {exc}") from exc
        self._clock = clock
        self._clock_ts = now
        return clock

    def spec(self, symbol: str) -> SymbolSpec:
        cached = self._specs.get(symbol)
        if cached and time.monotonic() - cached[0] < SPEC_TTL_S:
            return cached[1]
        self._ensure_mcp()
        try:
            spec = get_spec(self.mcp, symbol)
        except Exception:  # noqa: BLE001 - fall back to the stored row
            row = next(
                (s for s in self.store.list_symbols() if s["symbol"] == symbol), None
            )
            if row is None:
                raise
            spec = SymbolSpec(
                symbol=row["symbol"],
                digits=int(row["digits"]),
                point=float(row["point"]),
                contract_size=float(row["contract_size"]),
                tick_value=float(row["tick_value"]),
                volume_min=float(row["volume_min"]),
                volume_max=float(row["volume_max"]),
                volume_step=float(row["volume_step"]),
                stops_level=int(row["stops_level"]),
            )
        self._specs[symbol] = (time.monotonic(), spec)
        return spec

    def quote(self, symbol: str) -> tuple[float, float]:
        self._ensure_mcp()
        try:
            return quote(self.mcp, symbol)
        except Exception as exc:  # noqa: BLE001
            raise BrokerError(f"no quote for {symbol}: {exc}") from exc

    def spread(self, symbol: str) -> float:
        bid, ask = self.quote(symbol)
        return spread_points(bid, ask, self.spec(symbol).point)

    def atr(self, symbol: str, timeframe: str = "M15") -> float:
        key = (symbol, timeframe)
        cached = self._atr_cache.get(key)
        if cached and time.monotonic() - cached[0] < 60:
            return cached[1]
        from backend.ignite.analysis import features as feat

        bars = bar_mod.fetch_bars(self.mcp, self.clock(), symbol, timeframe, 128)
        value = feat.compute(bars).atr
        self._atr_cache[key] = (time.monotonic(), value)
        return value

    # ------------------------------------------------------------------- account

    def account(self) -> dict[str, Any]:
        return self.call("get_trading_account_info").get("account", {})

    def account_payload(self) -> dict[str, Any]:
        from backend.ignite.services import broker

        payload = broker.account(self.mcp)
        self.snapshot_equity(payload)
        return payload

    def snapshot_equity(self, payload: dict[str, Any], force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._snapshot_ts < 60:
            return
        try:
            self.store.snapshot_equity(
                float(payload.get("balance") or 0.0),
                float(payload.get("equity") or 0.0),
                float(payload.get("margin") or 0.0),
                float(payload.get("margin_free") or 0.0),
            )
            self._snapshot_ts = now
        except Exception:  # noqa: BLE001 - a missing snapshot must not break the page
            pass

    def positions(self, symbol: str | None = None) -> list[dict[str, Any]]:
        from backend.ignite.services import broker

        return broker.positions(self.mcp, self.clock(), symbol)

    def realised_today(self) -> dict[str, Any]:
        """Closed P/L since local midnight, converted back to UTC for MT5."""
        start_local = datetime.now().astimezone().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        start_utc = start_local.astimezone(timezone.utc)
        key = start_utc.isoformat()
        now = time.monotonic()
        cached = self._realised_cache.get(key)
        if cached and now - cached[0] < 30:
            return cached[1]

        from backend.ignite.services import broker

        try:
            trades = broker.closed_trades(
                self.mcp, self.clock(), start_utc, self.now_utc()
            )
        except Exception:  # noqa: BLE001 - the account page must still render
            return {
                "local_day_start_utc": start_utc.isoformat(),
                "realised_usd": None,
                "trades": None,
                "wins": None,
            }
        payload = {
            "local_day_start_utc": start_utc.isoformat(),
            "realised_usd": round(sum(float(t["net"]) for t in trades), 2),
            "trades": len(trades),
            "wins": sum(1 for t in trades if float(t["net"]) > 0),
        }
        self._realised_cache[key] = (now, payload)
        return payload

    # ---------------------------------------------------------------------- risk

    def risk_config(self) -> RiskConfig:
        return self.config().to_risk_config(max_drift_atr=self.settings.max_drift_atr)

    def kill_switch(self) -> bool:
        return self.store.kill_switch()

    def set_kill_switch(self, enabled: bool) -> None:
        self.store.set_kill_switch(enabled)
        self.events.publish("kill_switch", {"enabled": enabled})

    # --------------------------------------------------------------------- jobs

    def job(self, job_id: str) -> Job | None:
        with self._jobs_lock:
            return self.jobs.get(job_id)

    def register_job(self, job: Job) -> None:
        with self._jobs_lock:
            self.jobs[job.id] = job
            if len(self.jobs) > 50:
                oldest = sorted(self.jobs.values(), key=lambda j: j.created_at)[:-50]
                for stale in oldest:
                    self.jobs.pop(stale.id, None)

    def job_progress(self, job: Job, step: str, message: str, pct: int) -> None:
        job.step = step
        job.message = message
        job.pct = pct
        job.progress.append({"step": step, "message": message, "pct": pct, "ts": utc_now()})
        self.events.publish(
            "analysis.progress",
            {
                "job_id": job.id,
                "symbol": job.symbol,
                "timeframe": job.timeframe,
                "step": step,
                "message": message,
                "pct": pct,
            },
        )

    # --------------------------------------------------------------- confirm token

    def issue_token(self, draft_id: str, expires_at: str) -> str:
        token = uuid.uuid4().hex + uuid.uuid4().hex
        expiry = datetime.fromisoformat(expires_at).timestamp()
        with self._tokens_lock:
            self._tokens[token] = (draft_id, expiry)
            self._sweep_tokens()
        return token

    def consume_token(self, token: str | None, draft_id: str) -> bool:
        if not token:
            return False
        with self._tokens_lock:
            entry = self._tokens.pop(token, None)
        if entry is None:
            return False
        bound_to, expiry = entry
        return bound_to == draft_id and time.time() <= expiry

    def _sweep_tokens(self) -> None:
        now = time.time()
        for token in [t for t, (_, exp) in self._tokens.items() if exp < now]:
            self._tokens.pop(token, None)

    # -------------------------------------------------------------------- timestamps

    def now_utc(self) -> datetime:
        return datetime.now(timezone.utc)

    def local_zone(self) -> str:
        if self.settings.timezone != "local":
            return self.settings.timezone
        return datetime.now().astimezone().tzname() or "local"

    # ------------------------------------------------------------------ knowledge

    def knowledge_stats(self) -> dict[str, Any]:
        cards = self.store.knowledge_cards()
        status = self.knowledge
        payload: dict[str, Any] = (
            status.as_dict()
            if hasattr(status, "as_dict")
            else {"ok": False, "error": str(status)}
        )
        payload["cards"] = len(cards)
        payload["reviewed"] = sum(1 for card in cards if card["status"] == "reviewed")
        payload["by_scope"] = {
            scope: sum(1 for card in cards if card["scope"] == scope)
            for scope in sorted({card["scope"] for card in cards})
        }
        payload["directory"] = str(self.settings.knowledge_dir)
        return payload
