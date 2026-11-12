"""Decision synthesis — combines forecast, fundamental, technical, attribution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from backend.ignite.analysis.risk import RiskConfig
from backend.ignite.analysis.graph import AnalysisResult
from backend.ignite.services.runtime import Runtime


@dataclass
class FundamentalContext:
    high_impact_events: list[dict]
    news_bias: str  # "bullish", "bearish", "neutral"
    next_event_time: str | None


@dataclass
class TechnicalContext:
    trend: Literal["up", "down", "flat"]
    volatility_regime: Literal["compression", "expansion", "normal"]
    key_levels: dict[str, float]
    atr: float


@dataclass
class AttributionContext:
    last_forecast_p_up: float | None
    last_realised_move_atr: float | None
    hit_rate: float | None


@dataclass
class Decision:
    action: Literal["ENTER", "MANAGE", "SKIP", "ERROR"]
    side: Literal["LONG", "SHORT", "NONE"]
    confidence: float
    reasoning: str


def build_fundamental_context(rt: Runtime, symbol: str) -> FundamentalContext:
    """Build fundamental context from calendar and news."""
    try:
        now = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start.replace(hour=23, minute=59, second=59)

        events = rt.news.calendar(start, end)
        high_impact = [e for e in events if e.get("impact") == "high"]

        # Get news for bias
        news = rt.news.news(start, end, limit=20)
        bias = _assess_news_bias(news)

        next_event = None
        if high_impact:
            next_event = min(e.get("time") for e in high_impact if e.get("time"))

        return FundamentalContext(
            high_impact_events=high_impact[:5],
            news_bias=bias,
            next_event_time=next_event,
        )
    except Exception:  # noqa: BLE001
        return FundamentalContext(high_impact_events=[], news_bias="neutral", next_event_time=None)


def _assess_news_bias(news: list[dict]) -> str:
    """Simple keyword-based news bias assessment."""
    if not news:
        return "neutral"

    bullish_keywords = ["rally", "surge", "gain", "rise", "bullish", "optimism", "strong"]
    bearish_keywords = ["fall", "drop", "decline", "crash", "bearish", "pessimism", "weak"]

    bullish = sum(1 for n in news for k in bullish_keywords if k in (n.get("subject") or "").lower())
    bearish = sum(1 for n in news for k in bearish_keywords if k in (n.get("subject") or "").lower())

    if bullish > bearish:
        return "bullish"
    if bearish > bullish:
        return "bearish"
    return "neutral"


def build_technical_context(rt: Runtime, symbol: str, timeframe: str) -> TechnicalContext:
    """Build technical context from latest analysis."""
    try:
        row = rt.store.latest_analysis(symbol, timeframe)
        if not row:
            return TechnicalContext(trend="flat", volatility_regime="normal", key_levels={}, atr=0.0)

        features = row.get("features", {}) if isinstance(row, dict) else {}

        return TechnicalContext(
            trend=features.get("trend", "flat"),
            volatility_regime=_assess_volatility_regime(features.get("atr", 0.0)),
            key_levels=_get_key_levels(row),
            atr=features.get("atr", 0.0),
        )
    except Exception:  # noqa: BLE001
        return TechnicalContext(trend="flat", volatility_regime="normal", key_levels={}, atr=0.0)


def _assess_volatility_regime(atr: float) -> str:
    """Simple volatility regime assessment."""
    if atr < 5:
        return "compression"
    if atr > 20:
        return "expansion"
    return "normal"


def _get_key_levels(row: dict) -> dict[str, float]:
    """Extract key levels from analysis."""
    return {
        "prior_day_high": 0.0,
        "prior_day_low": 0.0,
        "session_high": 0.0,
        "session_low": 0.0,
    }


def build_attribution_context(rt: Runtime, analysis_id: str) -> "AttributionContext":
    """Compare last forecast vs realised."""
    try:
        row = rt.store.get_analysis(analysis_id)
        if not row:
            return AttributionContext(None, None, None)

        # Get last agent decision for this symbol/timeframe
        decisions = rt.store.agent_decisions(limit=10, symbol=row.get("symbol"))
        if not decisions:
            return AttributionContext(None, None, None)

        last = decisions[0]
        return AttributionContext(
            last_forecast_p_up=last.get("p_up"),
            last_realised_move_atr=last.get("edge_atr"),
            hit_rate=None,
        )
    except Exception:  # noqa: BLE001
        return AttributionContext(None, None, None)


def synthesise(
    forecast: "AnalysisResult",
    fundamental: FundamentalContext,
    technical: TechnicalContext,
    attribution: "AttributionContext",
    risk: "RiskConfig",
) -> "Decision":
    """Synthesize all contexts into a trading decision."""
    signal = forecast.signal
    p_up = signal.p_up
    edge_atr = signal.edge_atr

    # Base decision from signal
    if signal.side == "long" and p_up >= 0.62 and edge_atr >= 0.60:
        base_action = "ENTER"
        side = "LONG"
        base_confidence = min(0.9, 0.5 + p_up * 0.5)
    elif signal.side == "short" and p_up <= 0.38 and edge_atr <= -0.60:
        base_action = "ENTER"
        side = "SHORT"
        base_confidence = min(0.9, 0.5 + (1 - p_up) * 0.5)
    else:
        base_action = "SKIP"
        side = "NONE"
        base_confidence = 0.5

    # Apply fundamental bias
    bias_adjustment = 0.0
    if fundamental.news_bias == "bullish" and side == "LONG":
        bias_adjustment += 0.1
    elif fundamental.news_bias == "bearish" and side == "SHORT":
        bias_adjustment += 0.1
    elif fundamental.news_bias == "bullish" and side == "SHORT":
        bias_adjustment -= 0.1
    elif fundamental.news_bias == "bearish" and side == "LONG":
        bias_adjustment -= 0.1

    # Apply technical bias
    tech_adjustment = 0.0
    if technical.trend == "up" and side == "LONG":
        tech_adjustment += 0.1
    elif technical.trend == "down" and side == "SHORT":
        tech_adjustment += 0.1
    elif technical.trend == "up" and side == "SHORT":
        tech_adjustment -= 0.1
    elif technical.trend == "down" and side == "LONG":
        tech_adjustment -= 0.1

    # Volatility regime adjustment
    if technical.volatility_regime == "expansion":
        base_confidence *= 0.9  # Less confident in expanding vol
    elif technical.volatility_regime == "compression":
        base_confidence *= 1.05  # Slightly more confident

    # Attribution adjustment
    attr_adjustment = 0.0
    if attribution.last_forecast_p_up is not None:
        # If last forecast was wrong, reduce confidence
        pass

    final_confidence = max(0.0, min(0.95, base_confidence + bias_adjustment + tech_adjustment))

    if base_action == "ENTER":
        reasoning = f"Signal {side} with p_up {p_up:.2f}, edge {edge_atr:.2f} ATR. "
        if fundamental.news_bias != "neutral":
            reasoning += f"Fundamental bias: {fundamental.news_bias}. "
        reasoning += f"Technical: {technical.trend} trend, {technical.volatility_regime} vol."
        return Decision(
            action="ENTER",
            side=side,
            confidence=min(0.95, final_confidence),
            reasoning=reasoning,
        )

    reasoning = f"No trade signal. p_up {p_up:.2f}, edge {edge_atr:.2f} ATR. "
    if signal.side == "none":
        reasoning += "Signal in neutral band."
    else:
        reasoning += "Edge below threshold."

    return Decision(
        action="SKIP",
        side="NONE",
        confidence=0.5,
        reasoning=reasoning,
    )