"""Context packs: the only facts a skill is allowed to talk about.

The pack is built from stored rows, never from model output. It carries a
structured payload for the prompt and a flat set of numbers that the grounding
validator will accept. Anything else the model writes is a hallucination.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from backend.ignite.agent.validators import collect_numbers
from backend.ignite.knowledge.facts import desk_facts


class ContextError(ValueError):
    pass


@dataclass
class ContextPack:
    skill: str
    subject: str
    payload: dict[str, Any]
    facts: dict[str, str] = field(default_factory=dict)
    allowed_numbers: set[float] = field(default_factory=set)
    notes: str = ""

    def to_audit(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "subject": self.subject,
            "payload": self.payload,
            "facts": self.facts,
            "allowed_numbers": sorted(self.allowed_numbers),
            "notes": self.notes,
        }


def _draft_payload(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "side": row["side"],
        "lots": row["lots"],
        "reference_price": row["reference_price"],
        "sl": row["sl"],
        "tp": row["tp"],
        "risk_usd": row["risk_usd"],
        "risk_pct": row["risk_pct"],
        "rr": row["rr"],
        "margin": row.get("margin"),
        "worst_case_usd": row.get("worst_case_usd"),
        "blocked": bool(row["blocked"]),
        "block_reason": row["block_reason"],
        "state": row["state"],
    }


def build_analysis_context(rt: Any, analysis_id: str) -> ContextPack:
    row = rt.store.get_analysis(analysis_id)
    if row is None:
        raise ContextError(f"no analysis {analysis_id}")

    features = json.loads(row["features_json"])
    reasons = json.loads(row["reasons_json"])
    draft = rt.store.draft_for_analysis(analysis_id)
    spec_row = next(
        (s for s in rt.store.list_symbols() if s["symbol"] == row["symbol"]), None
    )

    try:
        blackout = rt.news.blackout_at(rt.now_utc())
        calendar: dict[str, Any] = {"status": "ok", "blackout": blackout}
    except Exception as exc:  # noqa: BLE001 - calendar may be offline
        calendar = {"status": "unavailable", "blackout": None, "error": str(exc)[:200]}

    payload: dict[str, Any] = {
        "analysis_id": row["id"],
        "created_at": row["created_at"],
        "symbol": row["symbol"],
        "timeframe": row["timeframe"],
        "last_bar_time": row["last_bar_time"],
        "instrument": {
            "digits": spec_row["digits"] if spec_row else None,
            "point": spec_row["point"] if spec_row else None,
            "contract_size": spec_row["contract_size"] if spec_row else None,
            "volume_min": spec_row["volume_min"] if spec_row else None,
        },
        "market": {
            "last_close": features.get("last_close"),
            "atr": row["atr"],
            "spread_points": features.get("spread_points"),
            "trend": features.get("trend"),
            "ema_fast": features.get("ema_fast"),
            "ema_slow": features.get("ema_slow"),
            "realized_vol_pct": features.get("realized_vol_pct"),
        },
        "forecast": {
            "model_id": row["model_id"],
            "samples": row["samples"],
            "horizon": row["horizon"],
            "lookback": row["lookback"],
            "infer_s": row["infer_s"],
            "p_up": row["p_up"],
            "expected_move": row["edge"],
            "edge_atr": row["edge_atr"],
            "dispersion": row["dispersion"],
        },
        "signal": {
            "side": row["signal"],
            "version": row["signal_version"],
            "reasons": reasons,
        },
        "draft": _draft_payload(draft),
        "calendar": calendar,
        "desk": {
            "risk_version": row["risk_version"],
            "risk_pct": rt.risk_config().risk_pct,
            "max_drift_atr": rt.settings.max_drift_atr,
            "sl_atr": rt.risk_config().sl_atr,
            "tp_atr": rt.risk_config().tp_atr,
            "min_rr": rt.risk_config().min_rr,
            "max_spread_points": rt.risk_config().max_spread_points,
            "draft_ttl_s": rt.settings.draft_ttl_s,
            "blackout_pre_min": rt.settings.news_pre_minutes,
            "blackout_post_min": rt.settings.news_post_minutes,
        },
    }

    facts = desk_facts(rt.settings, rt.risk_config())
    allowed = collect_numbers(payload) | collect_numbers(facts.values())
    return ContextPack(
        skill="analysis_narrative",
        subject=analysis_id,
        payload=payload,
        facts=facts,
        allowed_numbers=allowed,
        notes=(
            "The signal and draft are already decided. Explain them; do not "
            "re-decide, resize, or suggest overriding a block."
        ),
    )
