"""Goal 5 evaluation: decision→outcome linkage, summary stats, compact feedback.

The PRD's ultimate objective is profitable trading, measured (Goal 5). This
module joins journaled entry decisions to their realised trade outcomes and
produces:

- ``summarize_outcomes`` — honest aggregate stats (win/loss, avg/sum R,
  expectancy). No edge is claimed from these numbers; they exist so the
  operator and the autonomy ladder have evidence.
- ``compact_feedback`` — a short string for the LLM's context pack
  (recent decisions with outcomes, per the PRD: "compact feedback, not
  raw history"), plus the cached daily baseline comparison.
- ``promotion_eligibility`` — measures the desk against the pre-committed
  promotion thresholds (``PROMOTION_THRESHOLDS_V1``). The numbers were fixed
  BEFORE any evaluation ran (PRD Goal 5: never tune thresholds after seeing
  results); promotion stays operator-confirmed, but the evidence gate is
  enforced in code.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from backend.ignite.services.runtime import Runtime

# Goal 5 "earned autonomy": the promotion evidence bar, committed in code
# before this desk had any measured results to tune against. Changing these
# numbers later is threshold-tuning and must be treated as a PRD violation —
# the harness fingerprint reset and the audit trail exist to expose it.
PROMOTION_THRESHOLDS_V1: dict[str, Any] = {
    "version": "promotion.v1",
    "min_closed_trades": 30,  # enough closed trades for the stats to mean anything
    "min_sum_r": 0.0,  # strictly positive — must beat the no-trade baseline
    "min_avg_r": 0.0,  # positive expectancy per trade
    "min_win_rate": 0.40,
    "max_drawdown_r": 8.0,  # peak-to-trough on cumulative R
}


def max_drawdown_r(rs_chronological: list[float]) -> float:
    """Peak-to-trough drawdown on the cumulative R curve (starts at 0)."""
    peak = 0.0
    cum = 0.0
    dd = 0.0
    for r in rs_chronological:
        cum += r
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return dd


def promotion_eligibility(
    rows: list[dict[str, Any]], current_mode: str
) -> dict[str, Any]:
    """Measure the desk against PROMOTION_THRESHOLDS_V1 (pure function).

    ``rows`` are ``agent_position_outcomes`` rows. The ladder step
    shadow→demo→live is computed from ``current_mode``; the report is shown
    to the operator and enforced by ``Runtime.promote_mode``.
    """
    closed = [
        r for r in rows if r.get("executed") and r.get("r_multiple") is not None
    ]
    closed_chrono = sorted(closed, key=lambda r: str(r.get("closed_at") or ""))
    rs = [float(r["r_multiple"]) for r in closed_chrono]
    stats = summarize_outcomes(rows)

    measured = {
        "closed_trades": len(closed),
        "sum_r": round(stats["sum_r"], 4),
        "avg_r": round(stats["avg_r"], 4) if stats["avg_r"] is not None else None,
        "win_rate": round(stats["win_rate"], 4) if stats["win_rate"] is not None else None,
        "max_drawdown_r": round(max_drawdown_r(rs), 4),
    }
    t = PROMOTION_THRESHOLDS_V1
    win_rate = measured["win_rate"]
    checks = [
        {
            "criterion": "min_closed_trades",
            "threshold": t["min_closed_trades"],
            "measured": measured["closed_trades"],
            "met": measured["closed_trades"] >= t["min_closed_trades"],
        },
        {
            "criterion": "min_sum_r",
            "threshold": f"> {t['min_sum_r']}",
            "measured": measured["sum_r"],
            "met": measured["sum_r"] > t["min_sum_r"],
        },
        {
            "criterion": "min_avg_r",
            "threshold": f"> {t['min_avg_r']}",
            "measured": measured["avg_r"],
            "met": measured["avg_r"] is not None and measured["avg_r"] > t["min_avg_r"],
        },
        {
            "criterion": "min_win_rate",
            "threshold": f">= {t['min_win_rate']}",
            "measured": win_rate,
            "met": win_rate is not None and win_rate >= t["min_win_rate"],
        },
        {
            "criterion": "max_drawdown_r",
            "threshold": f"<= {t['max_drawdown_r']}",
            "measured": measured["max_drawdown_r"],
            "met": measured["max_drawdown_r"] <= t["max_drawdown_r"],
        },
    ]
    ladder = ("shadow", "demo", "live")
    target = None
    if current_mode in ladder and ladder.index(current_mode) < len(ladder) - 1:
        target = ladder[ladder.index(current_mode) + 1]
    return {
        "thresholds_version": t["version"],
        "thresholds": t,
        "measured": measured,
        "checks": checks,
        "eligible": all(c["met"] for c in checks) and target is not None,
        "target_mode": target,
        "current_mode": current_mode,
    }


def summarize_outcomes(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate decision→outcome rows into honest summary stats.

    A decision is "closed" when its position has an r_multiple (the trade
    finished); "open" when executed but not yet resolved; "unexecuted" when
    the decision was made but nothing was sent (blocked, shadow, error).
    """
    closed = [r for r in rows if r.get("executed") and r.get("r_multiple") is not None]
    open_trades = [r for r in rows if r.get("executed") and r.get("r_multiple") is None]
    unexecuted = [r for r in rows if not r.get("executed")]

    rs = [float(r["r_multiple"]) for r in closed]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    sum_r = sum(rs)
    avg_r = sum_r / len(rs) if rs else None

    return {
        "entry_decisions": len(rows),
        "executed": len(rows) - len(unexecuted),
        "closed": len(closed),
        "open": len(open_trades),
        "unexecuted": len(unexecuted),
        "wins": len(wins),
        "losses": len(losses),
        "avg_win_r": (sum(wins) / len(wins)) if wins else None,
        "avg_loss_r": (sum(losses) / len(losses)) if losses else None,
        "sum_r": sum_r,
        "avg_r": avg_r,
        "win_rate": (len(wins) / len(closed)) if closed else None,
        "total_realised_usd": float(
            sum(float(r["realised_pnl"] or 0.0) for r in closed)
        ),
    }


def _fmt(value: float | None, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    return f"{value:+.2f}{suffix}"


def harness_fingerprint(
    provider: str | None, model: str | None, system_prompt: str, tool_names: list[str]
) -> str:
    """Stable fingerprint of the decision harness (PRD Goal 5).

    A change in model, system prompt, or the tool registry means the measured
    statistics no longer describe the current trader: the evaluation resets to
    shadow. Pure function; the engine supplies the pieces and compares.
    """
    digest = hashlib.sha256()
    digest.update((provider or "").encode())
    digest.update((model or "").encode())
    digest.update(system_prompt.encode())
    for name in sorted(tool_names):
        digest.update(name.encode())
    return digest.hexdigest()[:16]


def compact_feedback(rt: Runtime, limit: int = 30) -> str:
    """Compact outcome feedback for the LLM's context pack (Goal 5).

    Shows the desk's measured results and the last few closed trades with
    their R multiples — evidence the model can learn from, not raw history.
    """
    try:
        rows = rt.store.agent_position_outcomes(limit=limit)
    except Exception:  # noqa: BLE001 - feedback is best effort, never blocks
        rows = []
    stats = summarize_outcomes(rows) if rows else None
    lines: list[str] = []
    if not rows:
        lines.append("Decision outcome stats: no entry decisions journaled yet.")
    else:
        lines.extend([
            "Decision outcome stats (measured, last {closed} closed of {executed} executed):"
            .format(closed=stats["closed"], executed=stats["executed"]),
            (
                f"- win rate {stats['win_rate']:.0%}, "
                f"sum R {_fmt(stats['sum_r'])}, avg R {_fmt(stats['avg_r'])}"
                if stats["win_rate"] is not None
                else "- no closed trades yet"
            ),
            f"- realised P&L (reported): {stats['total_realised_usd']:+.2f} USD",
        ])

    closed_rows = [
        r for r in rows if r.get("executed") and r.get("r_multiple") is not None
    ][:5]
    if closed_rows:
        lines.append("Recent closed trades (newest first):")
        for r in closed_rows:
            thesis = str(r.get("reasoning") or "").replace("\n", " ")[:80]
            lines.append(
                f"- {str(r.get('closed_at') or '')[:16]} {r['signal_side']} "
                f"{r['symbol']} R={_fmt(float(r['r_multiple']))} "
                f"({r.get('close_reason') or 'closed'}) :: {thesis}"
            )

    # Daily baseline comparison (Goal 5), computed by the scheduled evaluation
    # job — read from cache so no simulation happens per cycle.
    try:
        cached = json.loads(rt.store.setting("agent_baseline_summary") or "{}")
    except Exception:  # noqa: BLE001
        cached = {}
    for symbol, s in cached.items():
        lines.append(
            f"- Baseline ({symbol}, {str(s.get('created_at'))[:10]}, mechanics only): "
            f"you {_fmt(_num(s.get('agent_sum_r')))}R vs "
            f"follow-Kronos {_fmt(_num(s.get('kronos_sum_r')))}R vs "
            f"random {_fmt(_num(s.get('random_sum_r')))}R"
        )
    return "\n".join(lines)


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
