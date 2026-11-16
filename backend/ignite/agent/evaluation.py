"""Goal 5 evaluation: decision→outcome linkage, summary stats, compact feedback.

The PRD's ultimate objective is profitable trading, measured (Goal 5). This
module joins journaled entry decisions to their realised trade outcomes and
produces:

- ``summarize_outcomes`` — honest aggregate stats (win/loss, avg/sum R,
  expectancy). No edge is claimed from these numbers; they exist so the
  operator and the autonomy ladder have evidence.
- ``compact_feedback`` — a short string for the LLM's context pack
  (recent decisions with outcomes, per the PRD: "compact feedback, not
  raw history").

Baselines (no-trade / follow-Kronos / random with the same risk rules) and
auto-promotion/demotion thresholds are later increments of Goal 5; this file
deliberately does not claim or gate on them yet.
"""

from __future__ import annotations

import hashlib
from typing import Any

from backend.ignite.services.runtime import Runtime


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
        return "Decision outcome stats: unavailable."
    if not rows:
        return "Decision outcome stats: no entry decisions journaled yet."

    stats = summarize_outcomes(rows)
    lines = [
        "Decision outcome stats (measured, last {closed} closed of {executed} executed):"
        .format(closed=stats["closed"], executed=stats["executed"]),
        (
            f"- win rate {stats['win_rate']:.0%}, "
            f"sum R {_fmt(stats['sum_r'])}, avg R {_fmt(stats['avg_r'])}"
            if stats["win_rate"] is not None
            else "- no closed trades yet"
        ),
        f"- realised P&L (reported): {stats['total_realised_usd']:+.2f} USD",
    ]

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
    return "\n".join(lines)
