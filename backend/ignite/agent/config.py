"""Agent configuration. Loaded from environment variables with sensible defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


def _parse_csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(v.strip() for v in value.split(",") if v.strip())


def _parse_float_csv(value: str | None) -> tuple[float, ...]:
    if not value:
        return ()
    return tuple(float(v.strip()) for v in value.split(",") if v.strip())


@dataclass(frozen=True)
class AgentConfig:
    """Agent configuration loaded from environment variables."""

    enabled: bool = False
    symbols: tuple[str, ...] = ()
    timeframe: str = "M15"
    cycle_interval_min: int = 30
    session_open_hour: int = 3
    max_concurrent_analyses: int = 3
    position_check_interval_sec: int = 60
    max_concurrent_positions: int = 3
    daily_loss_limit_pct: float = 0.03
    trail_sl_atr: float = 1.5
    scale_in_atr: float = 1.5
    scale_out_levels: tuple[float, ...] = (1.0, 2.0, 3.0)
    max_correlation: float = 0.7
    session_end_hour: int = 21

    @classmethod
    def from_env(cls) -> "AgentConfig":
        """Load configuration from environment variables."""
        return cls(
            enabled=os.getenv("IGNITE_AGENT_ENABLED", "false").lower() == "true",
            symbols=_parse_csv(os.getenv("IGNITE_AGENT_SYMBOLS")),
            timeframe=os.getenv("IGNITE_AGENT_TIMEFRAME", "M15"),
            cycle_interval_min=int(os.getenv("IGNITE_AGENT_CYCLE_INTERVAL_MIN", "30")),
            session_open_hour=int(os.getenv("IGNITE_AGENT_SESSION_OPEN_HOUR", "3")),
            max_concurrent_analyses=int(os.getenv("IGNITE_AGENT_MAX_CONCURRENT", "3")),
            position_check_interval_sec=int(os.getenv("IGNITE_AGENT_POSITION_CHECK_SEC", "60")),
            max_concurrent_positions=int(os.getenv("IGNITE_AGENT_MAX_CONCURRENT_POSITIONS", "3")),
            daily_loss_limit_pct=float(os.getenv("IGNITE_AGENT_DAILY_LOSS_PCT", "0.03")),
            trail_sl_atr=float(os.getenv("IGNITE_AGENT_TRAIL_SL_ATR", "1.5")),
            scale_in_atr=float(os.getenv("IGNITE_AGENT_SCALE_IN_ATR", "1.5")),
            scale_out_levels=_parse_float_csv(os.getenv("IGNITE_AGENT_SCALE_OUT_LEVELS")),
            max_correlation=float(os.getenv("IGNITE_AGENT_MAX_CORRELATION", "0.7")),
            session_end_hour=int(os.getenv("IGNITE_AGENT_SESSION_END_HOUR", "21")),
        )