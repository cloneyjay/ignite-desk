"""JSON serialisation for stored analyses, drafts and bars.

Storage is UTC; every timestamp leaves this module as ISO-8601 with Z.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from backend.ignite.services.runtime import Runtime


def iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def draft_payload(
    row: dict[str, Any] | None, evaluation: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    if row is None:
        return None
    expires_at = datetime.fromisoformat(row["expires_at"])
    now = datetime.now(timezone.utc)
    state = row["state"]
    remaining = int((expires_at - now).total_seconds())
    if state == "draft" and remaining <= 0:
        state = "expired"
    payload: dict[str, Any] = {
        "id": row["id"],
        "analysis_id": row["analysis_id"],
        "created_at": iso(row["created_at"]),
        "expires_at": iso(row["expires_at"]),
        "expires_in_s": max(0, remaining),
        "state": state,
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
        "executable": state == "draft" and not row["blocked"],
    }
    if evaluation is not None:
        payload["executable"] = evaluation["executable"]
        payload["checks"] = evaluation["checks"]
        payload["live"] = evaluation["live"]
        payload["margin"] = evaluation["margin"]
        payload["worst_case_usd"] = evaluation["worst_case_usd"]
        payload["blackout"] = evaluation["blackout"]
    return payload


def analysis_payload(
    rt: Runtime, row: dict[str, Any], include_paths: bool = True
) -> dict[str, Any]:
    features = json.loads(row["features_json"])
    reasons = json.loads(row["reasons_json"])
    draft = rt.store.draft_for_analysis(row["id"])
    payload: dict[str, Any] = {
        "id": row["id"],
        "symbol": row["symbol"],
        "timeframe": row["timeframe"],
        "created_at": iso(row["created_at"]),
        "last_bar_time": iso(row["last_bar_time"]),
        "lookback": row["lookback"],
        "horizon": row["horizon"],
        "samples": row["samples"],
        "model_id": row["model_id"],
        "infer_s": row["infer_s"],
        "features": {
            **features,
            "atr": row["atr"],
            "last_time": iso(features.get("last_time")),
        },
        "signal": {
            "side": row["signal"],
            "p_up": row["p_up"],
            "edge": row["edge"],
            "edge_atr": row["edge_atr"],
            "dispersion": row["dispersion"],
            "reasons": reasons,
            "version": row["signal_version"],
        },
        "risk_version": row["risk_version"],
        "draft": draft_payload(draft),
    }
    if include_paths:
        payload["paths"] = rt.store.paths(row["id"])
    return payload


def bar_payload(frame: Any) -> list[dict[str, Any]]:
    out = []
    for row in frame.itertuples(index=False):
        out.append(
            {
                "time": iso(row.time),
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": float(row.volume),
                "spread": float(getattr(row, "spread", 0.0) or 0.0),
            }
        )
    return out
