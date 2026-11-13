"""Structured decision schema for the autonomous agent.

The final model turn must produce a decision matching this schema.
A decision that fails schema validation is recorded as INVALID and produces no order.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError


Action = Literal["LONG", "SHORT", "NO_TRADE", "WAIT", "MONITOR", "CLOSE", "MODIFY"]
EntryType = Literal["market", "limit"]


class Entry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: EntryType
    price: float  # 0.0 for market, limit price for limit


class Risk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lots: float
    sl: float
    tp: float


class Links(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_id: str | None = None
    draft_id: str | None = None
    decision_id: str


class Decision(BaseModel):
    """Structured trading decision from the agent."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    timeframe: str
    action: Action
    conviction: float
    thesis: str
    evidence: list[str]
    failed_conditions: list[str]
    entry: Entry
    risk: Risk
    expected_rr: float
    invalidate_if: list[str]
    links: Links


@dataclass(frozen=True)
class DecisionError(Exception):
    """Raised when decision parsing fails."""

    reason: str
    raw_json: str | None = None

    def __str__(self) -> str:
        return f"DecisionError: {self.reason}"


def parse_decision(json_str: str) -> Decision | DecisionError:
    """Parse a JSON string into a Decision, or return DecisionError on failure."""
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as exc:
        return DecisionError(reason=f"invalid json: {exc}", raw_json=json_str)

    try:
        return Decision(**data)
    except ValidationError as exc:
        return DecisionError(reason=f"validation failed: {exc}", raw_json=json_str)