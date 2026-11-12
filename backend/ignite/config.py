"""Runtime configuration. Everything comes from the environment / .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def _path(name: str, default: str) -> Path:
    raw = Path(os.getenv(name, default))
    return raw if raw.is_absolute() else (ROOT / raw).resolve()


@dataclass(frozen=True)
class MCPSettings:
    url: str
    token: str
    timeout_s: float = 60.0

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }


@dataclass(frozen=True)
class Settings:
    mcp: MCPSettings
    db_path: Path
    bind_host: str
    bind_port: int
    kronos_worker_url: str
    kronos_model: str
    timezone: str
    draft_ttl_s: int = 90
    max_drift_atr: float = 0.30
    news_pre_minutes: int = 30
    news_post_minutes: int = 15
    news_currencies: str = "USD,EUR,CNH,JPY"


def load_settings() -> Settings:
    token = os.getenv("MT5_MCP_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "MT5_MCP_TOKEN is not set. Copy .env.example to .env and fill it in."
        )
    return Settings(
        mcp=MCPSettings(
            url=os.getenv("MT5_MCP_URL", "http://127.0.0.1:22346/mcp").strip(),
            token=token,
            timeout_s=float(os.getenv("MT5_MCP_TIMEOUT_S", "60")),
        ),
        db_path=_path("IGNITE_DB_PATH", "./data/ignite.db"),
        bind_host=os.getenv("IGNITE_BIND_HOST", "127.0.0.1"),
        bind_port=int(os.getenv("IGNITE_BIND_PORT", "8000")),
        kronos_worker_url=os.getenv("KRONOS_WORKER_URL", "http://127.0.0.1:8765").rstrip("/"),
        kronos_model=os.getenv("KRONOS_MODEL", "NeoQuasar/Kronos-mini"),
        timezone=os.getenv("IGNITE_TZ", "local"),
        draft_ttl_s=int(os.getenv("IGNITE_DRAFT_TTL_S", "90")),
        max_drift_atr=float(os.getenv("IGNITE_MAX_DRIFT_ATR", "0.30")),
        news_pre_minutes=int(os.getenv("IGNITE_NEWS_PRE_MIN", "30")),
        news_post_minutes=int(os.getenv("IGNITE_NEWS_POST_MIN", "15")),
        news_currencies=os.getenv("IGNITE_NEWS_CURRENCIES", "USD,EUR,CNH,JPY"),
    )
