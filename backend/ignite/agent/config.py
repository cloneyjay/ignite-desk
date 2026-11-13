"""Agent configuration: the immutable value object and its validation rules.

The persisted row is the single source of truth (see ``ConfigService``); this
module only defines the shape, defaults, env seeding and ceilings.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from backend.ignite.analysis.risk import RiskConfig

OperatingMode = Literal["observe", "prepare", "autonomous"]
ExecutionMode = Literal["shadow", "demo", "live"]


class ConfigError(ValueError):
    """Raised when a config patch is unknown, malformed, or above its ceiling."""


# Absolute ceilings. The UI may not exceed these, whatever the operator types.
CEILINGS: dict[str, float] = {
    "risk_pct": 0.03,
    "max_risk_pct": 0.03,
    "daily_loss_limit_pct": 0.10,
    "max_concurrent_positions": 15,
    "max_positions_per_symbol": 3,
    "portfolio_risk_cap_pct": 0.20,
}


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
    """Immutable agent configuration. Persisted as JSON by ``ConfigService``."""

    enabled: bool = False
    operating_mode: OperatingMode = "prepare"
    execution_mode: ExecutionMode = "shadow"
    symbols: tuple[str, ...] = ()
    timeframe: str = "M15"
    cycle_interval_min: int = 30
    session_open_hour: int = 3
    session_end_hour: int = 21
    max_concurrent_analyses: int = 3
    position_check_interval_sec: int = 60
    max_concurrent_positions: int = 10
    max_positions_per_symbol: int = 2
    portfolio_risk_cap_pct: float = 0.15
    risk_pct: float = 0.02
    max_risk_pct: float = 0.02
    daily_loss_limit_pct: float = 0.06
    trail_sl_atr: float = 1.5
    scale_in_atr: float = 1.5
    scale_out_levels: tuple[float, ...] = (1.0, 2.0, 3.0)
    max_correlation: float = 0.7

    @classmethod
    def from_env(cls) -> "AgentConfig":
        """Seed values. Only used on first boot; the DB row wins afterwards."""
        return cls(
            enabled=os.getenv("IGNITE_AGENT_ENABLED", "false").lower() == "true",
            operating_mode=os.getenv("IGNITE_AGENT_MODE", "prepare").strip().lower(),  # type: ignore[arg-type]
            execution_mode=os.getenv("IGNITE_EXECUTION_MODE", "shadow").strip().lower(),  # type: ignore[arg-type]
            symbols=_parse_csv(os.getenv("IGNITE_AGENT_SYMBOLS")),
            timeframe=os.getenv("IGNITE_AGENT_TIMEFRAME", "M15"),
            cycle_interval_min=int(os.getenv("IGNITE_AGENT_CYCLE_INTERVAL_MIN", "30")),
            session_open_hour=int(os.getenv("IGNITE_AGENT_SESSION_OPEN_HOUR", "3")),
            session_end_hour=int(os.getenv("IGNITE_AGENT_SESSION_END_HOUR", "21")),
            max_concurrent_analyses=int(os.getenv("IGNITE_AGENT_MAX_CONCURRENT", "3")),
            position_check_interval_sec=int(os.getenv("IGNITE_AGENT_POSITION_CHECK_SEC", "60")),
            max_concurrent_positions=int(
                os.getenv("IGNITE_AGENT_MAX_CONCURRENT_POSITIONS", "10")
            ),
            max_positions_per_symbol=int(
                os.getenv("IGNITE_AGENT_MAX_POSITIONS_PER_SYMBOL", "2")
            ),
            portfolio_risk_cap_pct=float(os.getenv("IGNITE_AGENT_PORTFOLIO_RISK_PCT", "0.15")),
            risk_pct=float(os.getenv("IGNITE_AGENT_RISK_PCT", "0.02")),
            max_risk_pct=float(os.getenv("IGNITE_AGENT_MAX_RISK_PCT", "0.02")),
            daily_loss_limit_pct=float(os.getenv("IGNITE_AGENT_DAILY_LOSS_PCT", "0.06")),
            trail_sl_atr=float(os.getenv("IGNITE_AGENT_TRAIL_SL_ATR", "1.5")),
            scale_in_atr=float(os.getenv("IGNITE_AGENT_SCALE_IN_ATR", "1.5")),
            scale_out_levels=_parse_float_csv(os.getenv("IGNITE_AGENT_SCALE_OUT_LEVELS")),
            max_correlation=float(os.getenv("IGNITE_AGENT_MAX_CORRELATION", "0.7")),
        )

    def to_risk_config(self, max_drift_atr: float = 0.30) -> RiskConfig:
        return RiskConfig(
            risk_pct=self.risk_pct,
            max_risk_pct=self.max_risk_pct,
            max_drift_atr=max_drift_atr,
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AgentConfig":
        data = dict(raw)
        for key in ("symbols", "scale_out_levels"):
            if isinstance(data.get(key), list):
                data[key] = tuple(data[key])
        return cls(**data)


class AgentConfigPatch(BaseModel):
    """Validated partial update. Unknown fields are rejected, not ignored."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    operating_mode: OperatingMode | None = None
    execution_mode: ExecutionMode | None = None
    symbols: list[str] | None = None
    timeframe: str | None = None
    cycle_interval_min: int | None = None
    session_open_hour: int | None = None
    session_end_hour: int | None = None
    max_concurrent_analyses: int | None = None
    position_check_interval_sec: int | None = None
    max_concurrent_positions: int | None = None
    max_positions_per_symbol: int | None = None
    portfolio_risk_cap_pct: float | None = None
    risk_pct: float | None = None
    max_risk_pct: float | None = None
    daily_loss_limit_pct: float | None = None
    trail_sl_atr: float | None = None
    scale_in_atr: float | None = None
    scale_out_levels: list[float] | None = None
    max_correlation: float | None = None


def validate_patch(patch: dict[str, Any]) -> dict[str, Any]:
    try:
        model = AgentConfigPatch(**patch)
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc
    return model.model_dump(exclude_unset=True, exclude_none=True)


def check_ceilings(values: dict[str, Any]) -> None:
    for key, ceiling in CEILINGS.items():
        if key not in values:
            continue
        try:
            numeric = float(values[key])
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"{key} must be numeric") from exc
        if numeric > ceiling + 1e-12:
            raise ConfigError(f"{key}={numeric} exceeds ceiling {ceiling}")
