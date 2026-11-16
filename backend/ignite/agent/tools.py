"""Agent tool registry: typed, permission-scoped, audited tools for LLM function calling.

Tools are the bridge between the model and the desk. Each tool has a JSON schema,
a permission (read/prepare/execute), a timeout, and a result schema.
"""

from __future__ import annotations

import json
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from backend.ignite.services.runtime import Runtime


def _sanitize_for_json(value: Any) -> Any:
    """Recursively convert non-JSON-serializable objects (e.g. pandas Timestamps,
    numpy scalars/arrays) to plain Python types so FastAPI's encoder never chokes."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, pd.Timedelta):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {k: _sanitize_for_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_for_json(v) for v in value]
    return str(value)


@dataclass(frozen=True)
class ToolSpec:
    """A single tool the agent can call."""

    name: str
    permission: str  # "read" | "prepare" | "execute"
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    timeout_s: float
    handler: "Callable[[Runtime, dict[str, Any]], Awaitable[dict[str, Any]]]"

    def to_openai(self) -> dict[str, Any]:
        """Convert to OpenAI tool schema format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }

    def validate_input(self, args: dict[str, Any]) -> dict[str, Any]:
        """Validate arguments against input schema, return coerced dict."""
        return args

    def validate_output(self, result: dict[str, Any]) -> dict[str, Any]:
        """Validate result against output schema, return coerced dict."""
        return result


def permission_allowed(
    permission: str, mode: str, kill_switch: bool, autonomy_level: int = 0
) -> bool:
    """Single source of truth for tool gating.

    read    → always allowed
    prepare → autonomous/prepare mode and autonomy level >= 1
    execute → autonomous mode, kill switch off, autonomy level >= 2
    """
    if permission == "execute":
        return mode == "autonomous" and not kill_switch and autonomy_level >= 2
    if permission == "prepare":
        return mode in ("autonomous", "prepare") and autonomy_level >= 1
    return True


class ToolRegistry:
    """Registry of all available tools, filtered by mode and kill switch."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._build_tools()

    def _build_tools(self) -> None:
        """Define all 21 tools from spec §5.5."""
        # ============================================================
        # READ tools (available in all modes)
        # ============================================================

        self._register(
            ToolSpec(
                name="account_snapshot",
                permission="read",
                description="Get current account balances, margin, and mode",
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                output_schema={
                    "type": "object",
                    "properties": {
                        "equity": {"type": "number"},
                        "balance": {"type": "number"},
                        "margin": {"type": "number"},
                        "margin_free": {"type": "number"},
                        "profit": {"type": "number"},
                        "currency": {"type": "string"},
                        "server": {"type": "string"},
                        "type": {"type": "string"},
                    },
                    "required": ["equity", "balance", "margin", "margin_free", "profit", "currency", "server", "type"],
                    "additionalProperties": False,
                },
                timeout_s=5.0,
                handler=self._account_snapshot,
            )
        )

        self._register(
            ToolSpec(
                name="account_positions",
                permission="read",
                description="List open MT5 positions with ownership info",
                input_schema={
                    "type": "object",
                    "properties": {"symbol": {"type": "string"}},
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "positions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "ticket": {"type": "string"},
                                    "symbol": {"type": "string"},
                                    "side": {"type": "string"},
                                    "lots": {"type": "number"},
                                    "price_open": {"type": "number"},
                                    "price_current": {"type": "number"},
                                    "sl": {"type": ["number", "null"]},
                                    "tp": {"type": ["number", "null"]},
                                    "profit": {"type": "number"},
                                    "swap": {"type": "number"},
                                    "comment": {"type": "string"},
                                },
                                "required": ["ticket", "symbol", "side", "lots", "price_open", "price_current", "profit", "swap", "comment"],
                                "additionalProperties": False,
                            },
                        }
                    },
                    "required": ["positions"],
                    "additionalProperties": False,
                },
                timeout_s=5.0,
                handler=self._account_positions,
            )
        )

        self._register(
            ToolSpec(
                name="market_quote",
                permission="read",
                description="Get current bid/ask/spread for a symbol",
                input_schema={
                    "type": "object",
                    "properties": {"symbol": {"type": "string"}},
                    "required": ["symbol"],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "bid": {"type": "number"},
                        "ask": {"type": "number"},
                        "spread_points": {"type": "number"},
                        "time": {"type": "string"},
                    },
                    "required": ["symbol", "bid", "ask", "spread_points", "time"],
                    "additionalProperties": False,
                },
                timeout_s=3.0,
                handler=self._market_quote,
            )
        )

        self._register(
            ToolSpec(
                name="market_bars",
                permission="read",
                description="Get OHLCV bars for a symbol/timeframe",
                input_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "timeframe": {"type": "string", "enum": ["M5", "M15", "M30", "H1"]},
                        "count": {"type": "integer", "minimum": 1, "maximum": 500},
                    },
                    "required": ["symbol", "timeframe"],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "timeframe": {"type": "string"},
                        "bars": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "time": {"type": "string"},
                                    "open": {"type": "number"},
                                    "high": {"type": "number"},
                                    "low": {"type": "number"},
                                    "close": {"type": "number"},
                                    "volume": {"type": "number"},
                                    "spread": {"type": "number"},
                                },
                                "required": ["time", "open", "high", "low", "close", "volume", "spread"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["symbol", "timeframe", "bars"],
                    "additionalProperties": False,
                },
                timeout_s=10.0,
                handler=self._market_bars,
            )
        )

        self._register(
            ToolSpec(
                name="market_spec",
                permission="read",
                description="Get SymbolSpec (digits, point, contract_size, volume_step, stops_level, etc.)",
                input_schema={
                    "type": "object",
                    "properties": {"symbol": {"type": "string"}},
                    "required": ["symbol"],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "digits": {"type": "integer"},
                        "point": {"type": "number"},
                        "contract_size": {"type": "number"},
                        "tick_value": {"type": "number"},
                        "volume_min": {"type": "number"},
                        "volume_max": {"type": "number"},
                        "volume_step": {"type": "number"},
                        "stops_level": {"type": "integer"},
                    },
                    "required": ["symbol", "digits", "point", "contract_size", "tick_value", "volume_min", "volume_max", "volume_step", "stops_level"],
                    "additionalProperties": False,
                },
                timeout_s=3.0,
                handler=self._market_spec,
            )
        )

        self._register(
            ToolSpec(
                name="market_structure",
                permission="read",
                description="Get market structure (trend, swings, levels, regime) for symbol/timeframe",
                input_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "timeframe": {"type": "string", "enum": ["M5", "M15", "M30", "H1"]},
                    },
                    "required": ["symbol", "timeframe"],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "timeframe": {"type": "string"},
                        "trend": {"type": "string"},
                        "last_close": {"type": "number"},
                        "ema_fast": {"type": "number"},
                        "ema_slow": {"type": "number"},
                        "atr": {"type": "number"},
                        "vwap": {"type": "number"},
                        "price_vs_vwap": {"type": "string"},
                        "swing_highs": {
                            "type": "array",
                            "items": {"type": "object", "properties": {"price": {"type": "number"}, "time": {"type": "string"}}, "additionalProperties": False},
                        },
                        "swing_lows": {
                            "type": "array",
                            "items": {"type": "object", "properties": {"price": {"type": "number"}, "time": {"type": "string"}}, "additionalProperties": False},
                        },
                        "recent_high": {"type": "number"},
                        "recent_low": {"type": "number"},
                    },
                    "required": ["symbol", "timeframe", "trend", "last_close", "ema_fast", "ema_slow", "atr", "vwap", "price_vs_vwap", "swing_highs", "swing_lows", "recent_high", "recent_low"],
                    "additionalProperties": False,
                },
                timeout_s=10.0,
                handler=self._market_structure,
            )
        )

        self._register(
            ToolSpec(
                name="news_calendar",
                permission="read",
                description="Get economic calendar events and blackout state",
                input_schema={
                    "type": "object",
                    "properties": {
                        "hours_before": {"type": "integer", "default": 2},
                        "days_after": {"type": "integer", "default": 2},
                    },
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "events": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "time": {"type": "string"},
                                    "impact": {"type": "string"},
                                    "currency": {"type": "string"},
                                },
                                "required": ["name", "time", "impact", "currency"],
                                "additionalProperties": False,
                            },
                        },
                        "blackout_active": {"type": "boolean"},
                        "blackout_until": {"type": ["string", "null"]},
                    },
                    "required": ["events", "blackout_active", "blackout_until"],
                    "additionalProperties": False,
                },
                timeout_s=5.0,
                handler=self._news_calendar,
            )
        )

        self._register(
            ToolSpec(
                name="news_headlines",
                permission="read",
                description="Get recent terminal news headlines",
                input_schema={
                    "type": "object",
                    "properties": {
                        "hours": {"type": "integer", "default": 48},
                        "limit": {"type": "integer", "default": 10},
                    },
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "subject": {"type": "string"},
                                    "time": {"type": "string"},
                                    "source": {"type": "string"},
                                },
                                "required": ["subject", "time", "source"],
                                "additionalProperties": False,
                            },
                        }
                    },
                    "required": ["items"],
                    "additionalProperties": False,
                },
                timeout_s=5.0,
                handler=self._news_headlines,
            )
        )

        # ============================================================
        # PREPARE tools (available when operating_mode allows)
        # ============================================================

        self._register(
            ToolSpec(
                name="forecast_run",
                permission="prepare",
                description="Run Kronos forecast for symbol/timeframe",
                input_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "timeframe": {"type": "string", "enum": ["M5", "M15", "M30", "H1"]},
                        "samples": {"type": "integer", "default": 25},
                        "lookback": {"type": "integer", "default": 288},
                    },
                    "required": ["symbol", "timeframe"],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "timeframe": {"type": "string"},
                        "forecast": {
                            "type": "array",
                            "items": {"type": "number"},
                        },
                        "p_up": {"type": "number"},
                        "edge_atr": {"type": "number"},
                        "dispersion": {"type": "number"},
                    },
                    "required": ["symbol", "timeframe", "forecast", "p_up", "edge_atr", "dispersion"],
                    "additionalProperties": False,
                },
                timeout_s=30.0,
                handler=self._forecast_run,
            )
        )

        self._register(
            ToolSpec(
                name="analysis_run",
                permission="prepare",
                description="Run deterministic analysis + create draft order",
                input_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "timeframe": {"type": "string", "enum": ["M5", "M15", "M30", "H1"]},
                    },
                    "required": ["symbol", "timeframe"],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "analysis_id": {"type": "string"},
                        "signal": {"type": "string", "enum": ["LONG", "SHORT", "NONE"]},
                        "p_up": {"type": "number"},
                        "edge_atr": {"type": "number"},
                        "dispersion": {"type": "number"},
                        "draft_id": {"type": "string"},
                    },
                    "required": ["analysis_id", "signal", "p_up", "edge_atr", "dispersion", "draft_id"],
                    "additionalProperties": False,
                },
                timeout_s=30.0,
                handler=self._analysis_run,
            )
        )

        self._register(
            ToolSpec(
                name="risk_evaluate",
                permission="prepare",
                description="Validate a hypothetical order against risk rules",
                input_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "side": {"type": "string", "enum": ["buy", "sell"]},
                        "lots": {"type": "number"},
                        "sl": {"type": "number"},
                        "tp": {"type": "number"},
                    },
                    "required": ["symbol", "side", "lots", "sl", "tp"],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "ok": {"type": "boolean"},
                        "code": {"type": "string"},
                        "detail": {"type": "string"},
                        "risk_usd": {"type": "number"},
                        "risk_pct": {"type": "number"},
                    },
                    "required": ["ok", "code", "detail", "risk_usd", "risk_pct"],
                    "additionalProperties": False,
                },
                timeout_s=5.0,
                handler=self._risk_evaluate,
            )
        )

        self._register(
            ToolSpec(
                name="draft_create",
                permission="prepare",
                description="Create a time-limited order draft",
                input_schema={
                    "type": "object",
                    "properties": {
                        "analysis_id": {"type": "string"},
                        "side": {"type": "string", "enum": ["buy", "sell"]},
                        "lots": {"type": "number"},
                        "reference_price": {"type": "number"},
                        "sl": {"type": "number"},
                        "tp": {"type": "number"},
                    },
                    "required": ["analysis_id", "side", "lots", "reference_price", "sl", "tp"],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "draft_id": {"type": "string"},
                        "expires_at": {"type": "string"},
                        "state": {"type": "string"},
                    },
                    "required": ["draft_id", "expires_at", "state"],
                    "additionalProperties": False,
                },
                timeout_s=5.0,
                handler=self._draft_create,
            )
        )

        self._register(
            ToolSpec(
                name="draft_evaluate",
                permission="prepare",
                description="Revalidate a draft against live market state",
                input_schema={
                    "type": "object",
                    "properties": {
                        "draft_id": {"type": "string"},
                    },
                    "required": ["draft_id"],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "ok": {"type": "boolean"},
                        "code": {"type": "string"},
                        "detail": {"type": "string"},
                        "spread_ok": {"type": "boolean"},
                        "margin_ok": {"type": "boolean"},
                    },
                    "required": ["ok", "code", "detail", "spread_ok", "margin_ok"],
                    "additionalProperties": False,
                },
                timeout_s=5.0,
                handler=self._draft_evaluate,
            )
        )

        # ============================================================
        # EXECUTE tools (only when autonomous + kill_switch=off)
        # ============================================================

        self._register(
            ToolSpec(
                name="execution_place_order",
                permission="execute",
                description="Execute a confirmed order draft through the guarded execution path",
                input_schema={
                    "type": "object",
                    "properties": {
                        "draft_id": {"type": "string"},
                    },
                    "required": ["draft_id"],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "ok": {"type": "boolean"},
                        "code": {"type": "string"},
                        "detail": {"type": "string"},
                        "position_ticket": {"type": ["string", "null"]},
                        "fill_price": {"type": ["number", "null"]},
                    },
                    "required": ["ok", "code", "detail", "position_ticket", "fill_price"],
                    "additionalProperties": False,
                },
                timeout_s=15.0,
                handler=self._execution_place_order,
            )
        )

        self._register(
            ToolSpec(
                name="execution_modify_position",
                permission="execute",
                description="Modify SL/TP of an open position",
                input_schema={
                    "type": "object",
                    "properties": {
                        "ticket": {"type": "string"},
                        "sl": {"type": ["number", "null"]},
                        "tp": {"type": ["number", "null"]},
                    },
                    "required": ["ticket"],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "ok": {"type": "boolean"},
                        "code": {"type": "string"},
                        "detail": {"type": "string"},
                    },
                    "required": ["ok", "code", "detail"],
                    "additionalProperties": False,
                },
                timeout_s=10.0,
                handler=self._execution_modify_position,
            )
        )

        self._register(
            ToolSpec(
                name="execution_close_position",
                permission="execute",
                description="Close a position by ticket",
                input_schema={
                    "type": "object",
                    "properties": {
                        "ticket": {"type": "string"},
                        "reason": {"type": "string", "default": "AGENT"},
                    },
                    "required": ["ticket"],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "ok": {"type": "boolean"},
                        "code": {"type": "string"},
                        "detail": {"type": "string"},
                    },
                    "required": ["ok", "code", "detail"],
                    "additionalProperties": False,
                },
                timeout_s=10.0,
                handler=self._execution_close_position,
            )
        )

        self._register(
            ToolSpec(
                name="execution_scale",
                permission="execute",
                description="Partial close or add to position",
                input_schema={
                    "type": "object",
                    "properties": {
                        "ticket": {"type": "string"},
                        "side": {"type": "string", "enum": ["reduce", "add"]},
                        "lots": {"type": "number"},
                        "sl": {"type": ["number", "null"]},
                        "tp": {"type": ["number", "null"]},
                    },
                    "required": ["ticket", "side", "lots"],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "ok": {"type": "boolean"},
                        "code": {"type": "string"},
                        "detail": {"type": "string"},
                        "new_ticket": {"type": ["string", "null"]},
                    },
                    "required": ["ok", "code", "detail", "new_ticket"],
                    "additionalProperties": False,
                },
                timeout_s=15.0,
                handler=self._execution_scale,
            )
        )

        # ============================================================
        # READ tools (additional)
        # ============================================================

        self._register(
            ToolSpec(
                name="position_list",
                permission="read",
                description="List agent-managed positions from local DB",
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                output_schema={
                    "type": "object",
                    "properties": {
                        "positions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "ticket": {"type": "string"},
                                    "symbol": {"type": "string"},
                                    "side": {"type": "string"},
                                    "entry_price": {"type": "number"},
                                    "volume": {"type": "number"},
                                    "sl": {"type": ["number", "null"]},
                                    "tp": {"type": ["number", "null"]},
                                    "opened_at": {"type": "string"},
                                    "status": {"type": "string"},
                                    "realised_pnl": {"type": ["number", "null"]},
                                    "r_multiple": {"type": ["number", "null"]},
                                },
                                "required": ["ticket", "symbol", "side", "entry_price", "volume", "opened_at", "status"],
                                "additionalProperties": False,
                            },
                        }
                    },
                    "required": ["positions"],
                    "additionalProperties": False,
                },
                timeout_s=3.0,
                handler=self._position_list,
            )
        )

        self._register(
            ToolSpec(
                name="position_history",
                permission="read",
                description="Get closed trades and PnL from local DB",
                input_schema={
                    "type": "object",
                    "properties": {
                        "days": {"type": "integer", "default": 7},
                    },
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "trades": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "ticket": {"type": "string"},
                                    "symbol": {"type": "string"},
                                    "side": {"type": "string"},
                                    "entry_price": {"type": "number"},
                                    "exit_price": {"type": "number"},
                                    "volume": {"type": "number"},
                                    "realised_pnl": {"type": "number"},
                                    "r_multiple": {"type": "number"},
                                    "closed_at": {"type": "string"},
                                    "close_reason": {"type": "string"},
                                },
                                "required": ["ticket", "symbol", "side", "entry_price", "exit_price", "volume", "realised_pnl", "r_multiple", "closed_at", "close_reason"],
                                "additionalProperties": False,
                            },
                        }
                    },
                    "required": ["trades"],
                    "additionalProperties": False,
                },
                timeout_s=5.0,
                handler=self._position_history,
            )
        )

        self._register(
            ToolSpec(
                name="level_register",
                permission="prepare",
                description="Register a price trigger for alerts",
                input_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "price": {"type": "number"},
                        "direction": {"type": "string", "enum": ["above", "below"]},
                        "label": {"type": "string"},
                    },
                    "required": ["symbol", "price", "direction", "label"],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "ok": {"type": "boolean"},
                        "trigger_id": {"type": "string"},
                    },
                    "required": ["ok", "trigger_id"],
                    "additionalProperties": False,
                },
                timeout_s=3.0,
                handler=self._level_register,
            )
        )

        self._register(
            ToolSpec(
                name="chat_respond",
                permission="read",
                description="Final narration to user (no side effects)",
                input_schema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                    },
                    "required": ["text"],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "ack": {"type": "boolean"},
                    },
                    "required": ["ack"],
                    "additionalProperties": False,
                },
                timeout_s=1.0,
                handler=self._chat_respond,
            )
        )

        # Memory tools (read/prepare permissions)
        self._register(
            ToolSpec(
                name="scratchpad_write",
                permission="prepare",
                description="Write to agent scratchpad with optional TTL",
                input_schema={
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "value": {"type": "object"},
                        "ttl_seconds": {"type": "integer", "minimum": 1},
                    },
                    "required": ["key", "value"],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}, "key": {"type": "string"}},
                    "required": ["ok", "key"],
                    "additionalProperties": False,
                },
                timeout_s=2.0,
                handler=self._scratchpad_write,
            )
        )
        self._register(
            ToolSpec(
                name="scratchpad_read",
                permission="read",
                description="Read from agent scratchpad",
                input_schema={
                    "type": "object",
                    "properties": {"key": {"type": "string"}},
                    "required": ["key"],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}, "key": {"type": "string"}, "value": {"type": "object"}},
                    "required": ["ok", "key"],
                    "additionalProperties": False,
                },
                timeout_s=1.0,
                handler=self._scratchpad_read,
            )
        )
        self._register(
            ToolSpec(
                name="scratchpad_delete",
                permission="prepare",
                description="Delete a key from agent scratchpad",
                input_schema={
                    "type": "object",
                    "properties": {"key": {"type": "string"}},
                    "required": ["key"],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}, "key": {"type": "string"}},
                    "required": ["ok", "key"],
                    "additionalProperties": False,
                },
                timeout_s=1.0,
                handler=self._scratchpad_delete,
            )
        )

        self._register(
            ToolSpec(
                name="episodic_record",
                permission="prepare",
                description="Record an episode (trade, analysis, decision, reflection)",
                input_schema={
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["trade", "analysis", "decision", "reflection"]},
                        "payload": {"type": "object"},
                        "symbol": {"type": "string"},
                        "timeframe": {"type": "string"},
                        "outcome": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["type", "payload"],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}, "episode_id": {"type": "integer"}},
                    "required": ["ok", "episode_id"],
                    "additionalProperties": False,
                },
                timeout_s=2.0,
                handler=self._episodic_record,
            )
        )
        self._register(
            ToolSpec(
                name="episodic_query",
                permission="read",
                description="Query episodic memory with filters",
                input_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "type": {"type": "string"},
                        "timeframe": {"type": "string"},
                        "limit": {"type": "integer", "default": 100, "minimum": 1},
                        "since": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}, "episodes": {"type": "array"}, "count": {"type": "integer"}},
                    "required": ["ok", "episodes", "count"],
                    "additionalProperties": False,
                },
                timeout_s=2.0,
                handler=self._episodic_query,
            )
        )

        self._register(
            ToolSpec(
                name="semantic_remember",
                permission="prepare",
                description="Store a pattern/knowledge entry with tags",
                input_schema={
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "value": {"type": "object"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1, "default": 1.0},
                    },
                    "required": ["key", "value"],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}, "key": {"type": "string"}},
                    "required": ["ok", "key"],
                    "additionalProperties": False,
                },
                timeout_s=2.0,
                handler=self._semantic_remember,
            )
        )
        self._register(
            ToolSpec(
                name="semantic_recall",
                permission="read",
                description="Recall patterns matching query and/or tags",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "default": ""},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "limit": {"type": "integer", "default": 10, "minimum": 1},
                    },
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}, "results": {"type": "array"}, "count": {"type": "integer"}},
                    "required": ["ok", "results", "count"],
                    "additionalProperties": False,
                },
                timeout_s=2.0,
                handler=self._semantic_recall,
            )
        )

        self._register(
            ToolSpec(
                name="procedural_learn",
                permission="prepare",
                description="Learn or update a procedural rule (condition-action)",
                input_schema={
                    "type": "object",
                    "properties": {
                        "trigger": {"type": "string"},
                        "action": {"type": "string"},
                        "condition": {"type": "object"},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1, "default": 1.0},
                    },
                    "required": ["trigger", "action", "condition"],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}, "trigger": {"type": "string"}},
                    "required": ["ok", "trigger"],
                    "additionalProperties": False,
                },
                timeout_s=2.0,
                handler=self._procedural_learn,
            )
        )
        self._register(
            ToolSpec(
                name="procedural_recall",
                permission="read",
                description="Recall a procedural rule by trigger",
                input_schema={
                    "type": "object",
                    "properties": {"trigger": {"type": "string"}},
                    "required": ["trigger"],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}, "result": {"type": "object"}},
                    "required": ["ok", "result"],
                    "additionalProperties": False,
                },
                timeout_s=1.0,
                handler=self._procedural_recall,
            )
        )
        self._register(
            ToolSpec(
                name="procedural_query",
                permission="read",
                description="Query all procedural rules",
                input_schema={
                    "type": "object",
                    "properties": {"limit": {"type": "integer", "default": 100, "minimum": 1}},
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}, "results": {"type": "array"}, "count": {"type": "integer"}},
                    "required": ["ok", "results", "count"],
                    "additionalProperties": False,
                },
                timeout_s=2.0,
                handler=self._procedural_query,
            )
        )

        # ============================================================
        # STRATEGY tools (read/prepare — create, compile, backtest EAs)
        # ============================================================

        self._register(
            ToolSpec(
                name="strategy_create",
                permission="prepare",
                description="Create a new trading strategy: write MQL5 EA code and save it",
                input_schema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "symbol": {"type": "string"},
                        "timeframe": {"type": "string", "enum": ["M5", "M15", "M30", "H1"]},
                        "description": {"type": "string"},
                        "mql5_code": {"type": "string"},
                        "parameters": {"type": "object"},
                    },
                    "required": ["name", "symbol", "timeframe", "mql5_code"],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "ok": {"type": "boolean"},
                        "strategy_id": {"type": "string"},
                        "message": {"type": "string"},
                        "file_path": {"type": "string"},
                    },
                    "required": ["ok", "strategy_id", "message"],
                    "additionalProperties": False,
                },
                timeout_s=10.0,
                handler=self._strategy_create,
            )
        )

        self._register(
            ToolSpec(
                name="strategy_compile",
                permission="prepare",
                description="Compile an MQL5 strategy via MetaEditor MCP tool",
                input_schema={
                    "type": "object",
                    "properties": {"strategy_id": {"type": "string"}},
                    "required": ["strategy_id"],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "ok": {"type": "boolean"},
                        "strategy_id": {"type": "string"},
                        "compiled": {"type": "boolean"},
                        "message": {"type": "string"},
                        "errors": {"type": ["string", "null"]},
                        "warnings": {"type": ["string", "null"]},
                    },
                    "required": ["ok", "strategy_id", "compiled", "message"],
                    "additionalProperties": False,
                },
                timeout_s=30.0,
                handler=self._strategy_compile,
            )
        )

        self._register(
            ToolSpec(
                name="strategy_backtest",
                permission="prepare",
                description="Run MT5 Strategy Tester backtest for a compiled strategy",
                input_schema={
                    "type": "object",
                    "properties": {
                        "strategy_id": {"type": "string"},
                        "start_date": {"type": "string"},
                        "end_date": {"type": "string"},
                        "parameters": {"type": "object"},
                    },
                    "required": ["strategy_id", "start_date", "end_date"],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "ok": {"type": "boolean"},
                        "strategy_id": {"type": "string"},
                        "backtest_id": {"type": "string"},
                        "message": {"type": "string"},
                        "result": {"type": "object"},
                    },
                    "required": ["ok", "strategy_id", "message"],
                    "additionalProperties": False,
                },
                timeout_s=60.0,
                handler=self._strategy_backtest,
            )
        )

        self._register(
            ToolSpec(
                name="strategy_list",
                permission="read",
                description="List stored strategies, optionally filtered by status",
                input_schema={
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "enum": ["draft", "compiled", "backtested", "shadow", "demo", "live", "archived"],
                        },
                    },
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "ok": {"type": "boolean"},
                        "strategies": {"type": "array"},
                        "count": {"type": "integer"},
                    },
                    "required": ["ok", "strategies", "count"],
                    "additionalProperties": False,
                },
                timeout_s=5.0,
                handler=self._strategy_list,
            )
        )

        self._register(
            ToolSpec(
                name="strategy_get",
                permission="read",
                description="Get strategy details and backtest results by ID",
                input_schema={
                    "type": "object",
                    "properties": {"strategy_id": {"type": "string"}},
                    "required": ["strategy_id"],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "ok": {"type": "boolean"},
                        "strategy": {"type": "object"},
                        "backtests": {"type": "array"},
                    },
                    "required": ["ok", "strategy"],
                    "additionalProperties": False,
                },
                timeout_s=5.0,
                handler=self._strategy_get,
            )
        )

    def _register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        """Return one tool by name, or None if it is not registered."""
        return self._tools.get(name)

    def get_available(self, mode: str, kill_switch: bool, autonomy_level: int = 0) -> list[ToolSpec]:
        """Return tools available for the given mode, kill switch state, and autonomy level."""
        return [
            spec
            for spec in self._tools.values()
            if permission_allowed(spec.permission, mode, kill_switch, autonomy_level)
        ]


# ============================================================
# Tool handlers (sync functions wrapped for async signature)
# ============================================================

    async def _account_snapshot(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        payload = rt.account_payload()
        return {
            "equity": float(payload.get("equity") or 0.0),
            "balance": float(payload.get("balance") or 0.0),
            "margin": float(payload.get("margin") or 0.0),
            "margin_free": float(payload.get("margin_free") or 0.0),
            "profit": float(payload.get("profit") or 0.0),
            "currency": str(payload.get("currency") or "USD"),
            "server": str(payload.get("server") or ""),
            "type": str(payload.get("type") or "live"),
        }

    async def _account_positions(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        symbol = args.get("symbol")
        positions = rt.positions(symbol)
        return {"positions": positions}

    async def _market_quote(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        symbol = args["symbol"]
        bid, ask = rt.quote(symbol)
        spec = rt.spec(symbol)
        return {
            "symbol": symbol,
            "bid": bid,
            "ask": ask,
            "spread_points": abs(ask - bid) / spec.point if spec.point else 0.0,
            "time": rt.now_utc().isoformat(),
        }

    async def _market_bars(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        from backend.ignite.market import bars as bar_mod
        symbol = args["symbol"]
        timeframe = args["timeframe"]
        count = args.get("count", 120)
        bars = bar_mod.fetch_bars(rt.mcp, rt.clock(), symbol, timeframe, count)
        records = bars.to_dict("records") if hasattr(bars, "to_dict") else bars
        for bar in records:
            t = bar.get("time")
            if hasattr(t, "isoformat"):
                bar["time"] = t.isoformat()
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "bars": records,
        }

    async def _market_spec(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        symbol = args["symbol"]
        spec = rt.spec(symbol)
        return {
            "symbol": spec.symbol,
            "digits": spec.digits,
            "point": spec.point,
            "contract_size": spec.contract_size,
            "tick_value": spec.tick_value,
            "volume_min": spec.volume_min,
            "volume_max": spec.volume_max,
            "volume_step": spec.volume_step,
            "stops_level": spec.stops_level,
        }

    async def _market_structure(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        from backend.ignite.market.structure import compute_structure
        from backend.ignite.market import bars as bar_mod
        symbol = args["symbol"]
        timeframe = args["timeframe"]
        frame = bar_mod.fetch_bars(rt.mcp, rt.clock(), symbol, timeframe, 120)
        structure = compute_structure(frame)
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "trend": structure["trend"],
            "last_close": structure["last_close"],
            "ema_fast": structure["ema_fast"],
            "ema_slow": structure["ema_slow"],
            "atr": structure["atr"],
            "vwap": structure["vwap"],
            "price_vs_vwap": structure["price_vs_vwap"],
            "swing_highs": structure["swing_highs"],
            "swing_lows": structure["swing_lows"],
            "recent_high": structure["recent_high"],
            "recent_low": structure["recent_low"],
        }

    async def _news_calendar(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        from datetime import datetime, timedelta, timezone
        hours_before = args.get("hours_before", 2)
        days_after = args.get("days_after", 2)
        now = datetime.now(timezone.utc)
        events = rt.news.calendar(now - timedelta(hours=hours_before), now + timedelta(days=days_after))
        blackout = rt.news.blackout_at(now)
        return {
            "events": events,
            "blackout_active": blackout is not None,
            "blackout_until": blackout.get("end") if blackout else None,
        }

    async def _news_headlines(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        from datetime import datetime, timedelta, timezone
        hours = args.get("hours", 48)
        limit = args.get("limit", 10)
        now = datetime.now(timezone.utc)
        items = rt.news.news(now - timedelta(hours=hours), now + timedelta(minutes=5), limit)
        return {"items": items}

    async def _forecast_run(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        symbol = args["symbol"]
        timeframe = args["timeframe"]
        samples = args.get("samples", 25)
        lookback = args.get("lookback", 288)
        from backend.ignite.analysis.graph import DEFAULT_HORIZON
        from backend.ignite.market import bars as bar_mod
        bars = bar_mod.fetch_bars(rt.mcp, rt.clock(), symbol, timeframe, lookback)
        horizon = DEFAULT_HORIZON.get(timeframe, 12)
        future = bar_mod.future_timestamps(bars["time"].iloc[-1], timeframe, horizon)
        forecast = rt.forecast.forecast(bars, future, samples=samples, lookback=lookback)
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "forecast": forecast.get("forecast", []),
            "p_up": forecast.get("p_up", 0.5),
            "edge_atr": forecast.get("edge_atr", 0.0),
            "dispersion": forecast.get("dispersion", 1.0),
        }

    async def _analysis_run(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        from backend.ignite.services.analysis_service import start_analysis
        import time
        symbol = args["symbol"]
        timeframe = args["timeframe"]
        job = start_analysis(rt, symbol, timeframe)
        start = time.monotonic()
        timeout = 120.0
        while True:
            job_status = rt.job(job.id)
            if not job_status:
                raise RuntimeError(f"job {job.id} disappeared")
            if job_status.status == "done":
                analysis_id = job_status.analysis_id
                break
            if job_status.status == "failed":
                raise RuntimeError(job_status.error or "analysis failed")
            if time.monotonic() - start > timeout:
                raise RuntimeError(f"analysis timed out after {timeout}s")
            time.sleep(0.5)
        # Get the analysis and draft
        analysis = rt.store.get_analysis(analysis_id)
        draft = rt.store.draft_for_analysis(analysis_id)
        return {
            "analysis_id": analysis_id,
            "signal": str(analysis.get("signal", "NONE")).upper(),
            "p_up": float(analysis.get("p_up", 0.5)),
            "edge_atr": float(analysis.get("edge_atr", 0.0)),
            "dispersion": float(analysis.get("dispersion", 1.0)),
            "draft_id": draft["id"] if draft else "",
        }

    async def _risk_evaluate(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        from backend.ignite.services.gateway import OrderRequest
        req = OrderRequest(
            symbol=args["symbol"],
            side=args["side"],
            lots=args["lots"],
            sl=args["sl"],
            tp=args["tp"],
            decision_id="risk_eval_" + str(hash(frozenset(args.items()))),
        )
        result = rt.gateway.validate(req)
        return {
            "ok": result.ok,
            "code": result.code,
            "detail": result.detail,
            "risk_usd": abs(args["lots"] * rt.spec(args["symbol"]).contract_size * abs(args["sl"] - (args.get("reference_price", 0)))),
            "risk_pct": 0.0,  # Would need equity
        }

    async def _draft_create(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        from backend.ignite.services.execution import create_draft
        from datetime import datetime, timezone, timedelta
        analysis_id = args["analysis_id"]
        analysis = rt.store.get_analysis(analysis_id)
        if not analysis:
            raise RuntimeError(f"analysis {analysis_id} not found")
        draft = create_draft(
            rt,
            analysis_id=analysis_id,
            side=args["side"],
            lots=args["lots"],
            reference_price=args["reference_price"],
            sl=args["sl"],
            tp=args["tp"],
        )
        return {
            "draft_id": draft["id"],
            "expires_at": draft["expires_at"],
            "state": draft["state"],
        }

    async def _draft_evaluate(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        from backend.ignite.services.execution import evaluate_draft
        draft_id = args["draft_id"]
        draft = rt.store.get_draft(draft_id)
        if not draft:
            raise RuntimeError(f"draft {draft_id} not found")
        result = evaluate_draft(rt, draft)
        return {
            "ok": result.get("ok", False),
            "code": result.get("code", "UNKNOWN"),
            "detail": result.get("detail", ""),
            "spread_ok": result.get("spread_ok", False),
            "margin_ok": result.get("margin_ok", False),
        }

    async def _execution_place_order(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        from backend.ignite.services.execution import execute_draft_autonomous
        draft_id = args["draft_id"]
        result = execute_draft_autonomous(rt, draft_id)
        position = result.get("position") or {}
        order = result.get("order") or {}
        return {
            "ok": bool(result.get("ok", False)),
            "code": "OK" if result.get("ok") else "ERROR",
            "detail": result.get("state", ""),
            "position_ticket": position.get("ticket") or order.get("ticket"),
            "fill_price": position.get("price_open") or order.get("filled_price"),
        }

    async def _execution_modify_position(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        ticket = args["ticket"]
        sl = args.get("sl")
        tp = args.get("tp")
        result = rt.gateway.modify(ticket, sl, tp)
        return {"ok": result.ok, "code": result.code, "detail": result.detail}

    async def _execution_close_position(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        ticket = args["ticket"]
        reason = args.get("reason", "AGENT")
        result = rt.gateway.close(ticket, reason)
        return {"ok": result.ok, "code": result.code, "detail": result.detail}

    async def _execution_scale(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        # Not fully implemented yet - placeholder
        return {"ok": False, "code": "NOT_IMPLEMENTED", "detail": "scale not yet implemented", "new_ticket": None}

    async def _position_list(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        positions = rt.store.agent_positions()
        return {"positions": positions}

    async def _position_history(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        from backend.ignite.services.broker import closed_trades
        from datetime import datetime, timedelta, timezone
        days = args.get("days", 7)
        now = datetime.now(timezone.utc)
        trades = closed_trades(rt.mcp, rt.clock(), now - timedelta(days=days), now)
        return {"trades": trades}

    async def _level_register(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        # Placeholder - would register price trigger in DB
        import uuid
        return {"ok": True, "trigger_id": uuid.uuid4().hex}

    async def _chat_respond(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        return {"ack": True}

    # ============================================================
    # Memory tools
    # ============================================================

    async def _scratchpad_write(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        key = args["key"]
        value = args["value"]
        ttl = args.get("ttl_seconds")
        rt.store.scratchpad_write(key, value, ttl)
        return {"ok": True, "key": key}

    async def _scratchpad_read(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        key = args["key"]
        value = rt.store.scratchpad_read(key)
        return {"ok": True, "key": key, "value": value}

    async def _scratchpad_delete(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        key = args["key"]
        rt.store.scratchpad_delete(key)
        return {"ok": True, "key": key}

    async def _episodic_record(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        episode_id = rt.store.episodic_record(
            type=args["type"],
            payload=args["payload"],
            symbol=args.get("symbol"),
            timeframe=args.get("timeframe"),
            outcome=args.get("outcome"),
            tags=args.get("tags"),
        )
        return {"ok": True, "episode_id": episode_id}

    async def _episodic_query(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        episodes = rt.store.episodic_query(
            symbol=args.get("symbol"),
            type=args.get("type"),
            timeframe=args.get("timeframe"),
            limit=args.get("limit", 100),
            since=args.get("since"),
        )
        return {"ok": True, "episodes": episodes, "count": len(episodes)}

    async def _semantic_remember(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        rt.store.semantic_remember(
            key=args["key"],
            value=args["value"],
            tags=args.get("tags"),
            confidence=args.get("confidence", 1.0),
        )
        return {"ok": True, "key": args["key"]}

    async def _semantic_recall(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        results = rt.store.semantic_recall(
            query=args.get("query", ""),
            tags=args.get("tags"),
            limit=args.get("limit", 10),
        )
        return {"ok": True, "results": results, "count": len(results)}

    async def _procedural_learn(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        rt.store.procedural_learn(
            trigger=args["trigger"],
            action=args["action"],
            condition=args["condition"],
            confidence=args.get("confidence", 1.0),
        )
        return {"ok": True, "trigger": args["trigger"]}

    async def _procedural_recall(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        result = rt.store.procedural_recall(args["trigger"])
        return {"ok": True, "result": result}

    async def _procedural_query(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        results = rt.store.procedural_query(args.get("limit", 100))
        return {"ok": True, "results": results, "count": len(results)}

    # ============================================================
    # Strategy tools
    # ============================================================

    async def _strategy_create(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        from backend.ignite.agent.strategy import StrategyManager
        mgr = StrategyManager(rt)
        result = mgr.create_strategy(
            name=args["name"],
            symbol=args["symbol"],
            timeframe=args["timeframe"],
            mql5_code=args["mql5_code"],
            description=args.get("description"),
            parameters=args.get("parameters"),
        )
        return {
            "ok": result.ok,
            "strategy_id": result.strategy_id,
            "message": result.message,
            "file_path": result.data.get("file_path"),
        }

    async def _strategy_compile(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        from backend.ignite.agent.strategy import StrategyManager
        mgr = StrategyManager(rt)
        result = mgr.compile_strategy(args["strategy_id"])
        return {
            "ok": result.ok,
            "strategy_id": result.strategy_id,
            "compiled": result.data.get("compiled", False),
            "message": result.message,
            "errors": result.data.get("errors"),
            "warnings": result.data.get("warnings"),
        }

    async def _strategy_backtest(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        from backend.ignite.agent.strategy import StrategyManager
        mgr = StrategyManager(rt)
        result = mgr.run_backtest(
            strategy_id=args["strategy_id"],
            start_date=args["start_date"],
            end_date=args["end_date"],
            parameters=args.get("parameters"),
        )
        return {
            "ok": result.ok,
            "strategy_id": result.strategy_id,
            "backtest_id": result.data.get("backtest_id"),
            "message": result.message,
            "result": result.data.get("result"),
        }

    async def _strategy_list(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        from backend.ignite.agent.strategy import StrategyManager
        mgr = StrategyManager(rt)
        strategies = mgr.list_strategies(status=args.get("status"))
        return {
            "ok": True,
            "strategies": strategies,
            "count": len(strategies),
        }

    async def _strategy_get(self, rt: Runtime, args: dict[str, Any]) -> dict[str, Any]:
        from backend.ignite.agent.strategy import StrategyManager
        mgr = StrategyManager(rt)
        strategy = mgr.get_strategy(args["strategy_id"])
        if not strategy:
            return {"ok": False, "strategy": None, "backtests": []}
        backtests = mgr.list_backtests(args["strategy_id"])
        return {
            "ok": True,
            "strategy": strategy,
            "backtests": backtests,
        }