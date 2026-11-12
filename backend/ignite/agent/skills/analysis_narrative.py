"""`analysis_narrative`: explain a stored analysis without re-deciding it.

The deterministic graph owns every number. This skill composes reviewed desk
notes across risk, market mechanics and fundamentals, asks a model for 2-4
sentences, validates the prose against the context pack, and falls back to a
template if the model is unavailable or ungrounded.
"""

from __future__ import annotations

from typing import Any

from backend.ignite.agent.context import ContextPack, build_analysis_context
from backend.ignite.agent.contracts import SkillSpec

SYSTEM = """You are the desk analyst on Ignite Desk, a one-person XAUUSD day-trading desk.

A deterministic engine has already produced the forecast, the signal and the draft in CONTEXT. Your job is to explain that decision in plain prose, not to make a new one.

Rules:
- The deterministic numbers are authoritative. Never invent, round away, or contradict a price, probability, size, stop, target, or risk figure.
- Use only numbers that appear in CONTEXT or the desk notes.
- If the signal is NO TRADE, explain what failed. Do not argue for a trade.
- If a draft is blocked, name the block. Do not suggest overriding it.
- If the calendar is unavailable, do not claim there is no news; say the check could not run.
- Write 2-4 sentences, plain prose. No headings, bullets, emojis, or promises.
- Never say you executed, will execute, or recommend that the reader buy or sell.
- Speak as the desk: "the rule", "the model", "the draft"."""

SPEC = SkillSpec(
    id="analysis_narrative",
    title="Analysis commentary",
    when="The operator opens a stored analysis and asks for a non-binding read.",
    scopes=("risk_manager", "market_analyst", "fundamentals_desk"),
    card_limits=(("risk_manager", 3), ("market_analyst", 3), ("fundamentals_desk", 2)),
    max_words=140,
    temperature=0.15,
    max_tokens=320,
    system=SYSTEM,
    user_suffix="Write the commentary now.",
)


def build_context(rt: Any, subject: str) -> ContextPack:
    return build_analysis_context(rt, subject)


def _fmt(value: Any, pattern: str) -> str:
    if isinstance(value, (int, float)):
        return pattern.format(value)
    return "n/a"


def template_narrative(pack: ContextPack) -> str:
    """A deterministic note that uses exactly the same facts as the model."""
    payload = pack.payload
    symbol = payload.get("symbol", "XAUUSD")
    timeframe = payload.get("timeframe", "")
    market = payload.get("market") or {}
    forecast = payload.get("forecast") or {}
    signal = payload.get("signal") or {}
    draft = payload.get("draft")
    desk = payload.get("desk") or {}
    calendar = payload.get("calendar") or {}

    side = str(signal.get("side") or "none")
    p_up = _fmt(forecast.get("p_up"), "{:.2f}")
    edge_atr = _fmt(forecast.get("edge_atr"), "{:+.2f}")
    atr = _fmt(market.get("atr"), "{:.2f}")
    spread = _fmt(market.get("spread_points"), "{:.0f}")
    sentences: list[str] = []

    if side == "none":
        sentences.append(
            f"Kronos puts the {symbol} {timeframe} chance of a higher close at {p_up}, "
            f"with an expected edge of {edge_atr} ATR, so the rule stays flat."
        )
        sentences.append(
            f"ATR is {atr} and the spread is {spread} points, and neither side clears "
            "the probability and edge thresholds at the same time."
        )
    else:
        sentences.append(
            f"Kronos puts the {symbol} {timeframe} chance of a higher close at {p_up}, "
            f"with an expected edge of {edge_atr} ATR, which is enough for the rule to go {side.upper()}."
        )
        if draft and not draft.get("blocked"):
            sentences.append(
                f"The draft is {_fmt(draft.get('lots'), '{:g}')} lots at "
                f"{_fmt(draft.get('reference_price'), '{:.2f}')}, stop "
                f"{_fmt(draft.get('sl'), '{:.2f}')}, target "
                f"{_fmt(draft.get('tp'), '{:.2f}')}, risking "
                f"{_fmt((draft.get('risk_pct') or 0) * 100, '{:.2f}')}% of equity "
                f"for {_fmt(draft.get('rr'), '{:.2f}')} reward-to-risk."
            )
            sentences.append(
                f"The entry is inside the {_fmt(desk.get('max_drift_atr'), '{:.2f}')} ATR "
                "drift limit, so the setup has not run away from the closed bar."
            )
        elif draft and draft.get("blocked"):
            sentences.append(
                f"The draft is blocked: {draft.get('block_reason')}. No order is "
                "executable until a fresh draft clears every guard."
            )
        else:
            sentences.append(
                "No draft was produced for this bar, so there is nothing to execute."
            )

    blackout = calendar.get("blackout")
    if blackout:
        sentences.append(
            f"The entry also sits inside the {blackout.get('name')} blackout window "
            f"({blackout.get('currency')}, high impact), which closes execution until "
            f"{blackout.get('end')}."
        )
    elif calendar.get("status") != "ok":
        sentences.append(
            "The economic-calendar check could not run, so the desk has no blackout "
            "clearance for this entry."
        )

    return " ".join(sentences[:4])
