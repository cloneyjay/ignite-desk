"""Desk facts a knowledge card may interpolate.

Cards never carry live numbers. They carry placeholders such as
``{{risk.risk_pct}}``; the renderer substitutes values read from code and
configuration at prompt-build time. A card that references an unknown fact is
rejected by ``knowledge lint`` before it can reach a model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.ignite.analysis.risk import RiskConfig
from backend.ignite.config import Settings


@dataclass(frozen=True)
class FactSpec:
    name: str
    description: str
    kind: str = "text"


FACT_SPECS: dict[str, FactSpec] = {
    spec.name: spec
    for spec in (
        FactSpec("risk.risk_pct", "Risk per trade as a share of equity", "pct"),
        FactSpec("risk.max_risk_pct", "Hard cap on risk per trade", "pct"),
        FactSpec("risk.sl_atr", "Stop-loss distance in ATR", "mult"),
        FactSpec("risk.tp_atr", "Take-profit distance in ATR", "mult"),
        FactSpec("risk.min_rr", "Minimum reward-to-risk ratio", "num2"),
        FactSpec("risk.max_spread_points", "Maximum spread accepted at entry", "points"),
        FactSpec("risk.max_drift_atr", "Maximum price drift from the closed bar", "mult"),
        FactSpec("risk.version", "Risk engine version", "text"),
        FactSpec("execution.draft_ttl_s", "Draft lifetime", "seconds"),
        FactSpec("news.blackout_pre_min", "Blackout lead time before an event", "minutes"),
        FactSpec("news.blackout_post_min", "Blackout lag after an event", "minutes"),
        FactSpec("instrument.contract_size", "XAUUSD contract size in ounces", "int"),
    )
}


def format_fact(spec: FactSpec, value: Any) -> str:
    if spec.kind == "pct":
        return f"{float(value) * 100:.2f}%"
    if spec.kind == "mult":
        return f"{float(value):g}×ATR"
    if spec.kind == "num2":
        return f"{float(value):.2f}"
    if spec.kind == "points":
        return f"{float(value):g} points"
    if spec.kind == "seconds":
        return f"{float(value):g} s"
    if spec.kind == "minutes":
        return f"{float(value):g} min"
    if spec.kind == "int":
        return f"{int(value)}"
    return str(value)


def desk_facts(settings: Settings, risk_config: RiskConfig) -> dict[str, str]:
    raw: dict[str, Any] = {
        "risk.risk_pct": risk_config.risk_pct,
        "risk.max_risk_pct": risk_config.max_risk_pct,
        "risk.sl_atr": risk_config.sl_atr,
        "risk.tp_atr": risk_config.tp_atr,
        "risk.min_rr": risk_config.min_rr,
        "risk.max_spread_points": risk_config.max_spread_points,
        "risk.max_drift_atr": risk_config.max_drift_atr,
        "risk.version": risk_config.version,
        "execution.draft_ttl_s": settings.draft_ttl_s,
        "news.blackout_pre_min": settings.news_pre_minutes,
        "news.blackout_post_min": settings.news_post_minutes,
        "instrument.contract_size": 100,
    }
    return {
        name: format_fact(FACT_SPECS[name], value)
        for name, value in raw.items()
    }
