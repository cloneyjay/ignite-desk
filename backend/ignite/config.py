"""Runtime configuration. Everything comes from the environment / .env."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
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
class LLMSettings:
    """OpenAI-compatible provider chain. Empty key means "not configured"."""

    provider_order: tuple[str, ...] = ("nim", "local")
    nim_base_url: str = "https://integrate.api.nvidia.com/v1"
    nim_api_key: str = ""
    nim_model: str = "meta/llama-3.3-70b-instruct"
    local_base_url: str = "http://127.0.0.1:11434/v1"
    local_api_key: str = "ollama"
    local_model: str = "bonsai-2:2b"
    extra_base_url: str = ""
    extra_api_key: str = ""
    extra_model: str = ""
    timeout_s: float = 20.0
    max_tokens: int = 320

    def key_for(self, provider: str) -> str:
        return {
            "nim": self.nim_api_key,
            "local": self.local_api_key,
            "extra": self.extra_api_key,
        }.get(provider, "")


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
    knowledge_dir: Path = ROOT / "docs" / "agent-knowledge"
    llm: LLMSettings = field(default_factory=LLMSettings)
    agent_timeout_s: float = 25.0


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
        knowledge_dir=_path("IGNITE_KNOWLEDGE_DIR", "./docs/agent-knowledge"),
        llm=LLMSettings(
            provider_order=tuple(
                name.strip().lower()
                for name in os.getenv("LLM_PROVIDER_ORDER", "nim,local").split(",")
                if name.strip()
            ),
            nim_base_url=os.getenv(
                "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"
            ).rstrip("/"),
            nim_api_key=os.getenv("NVIDIA_API_KEY", "").strip(),
            nim_model=os.getenv("NVIDIA_MODEL", "meta/llama-3.3-70b-instruct"),
            local_base_url=os.getenv(
                "OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"
            ).rstrip("/"),
            local_model=os.getenv("OLLAMA_MODEL", "bonsai-2:2b"),
            extra_base_url=os.getenv("EXTRA_BASE_URL", "").rstrip("/"),
            extra_api_key=os.getenv("EXTRA_API_KEY", "").strip(),
            extra_model=os.getenv("EXTRA_MODEL", ""),
            timeout_s=float(os.getenv("IGNITE_LLM_TIMEOUT_S", "20")),
            max_tokens=int(os.getenv("IGNITE_LLM_MAX_TOKENS", "320")),
        ),
        agent_timeout_s=float(os.getenv("IGNITE_AGENT_TIMEOUT_S", "25")),
    )
