"""Market data ingestion.

Two rules that everything downstream depends on:

1. Bars are requested and returned in *trade-server* time; they are converted to
   UTC here and never re-interpreted again.
2. The forming bar is dropped. A signal is only ever computed on closed bars.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from backend.ignite.market.time import Clock
from backend.ignite.mcp.client import MCPClient, MCPError

TIMEFRAME_MINUTES: dict[str, int] = {
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
}

COLUMNS = ["time", "open", "high", "low", "close", "volume", "amount", "spread"]


class MarketDataError(RuntimeError):
    pass


def fetch_bars(
    mcp: MCPClient,
    clock: Clock,
    symbol: str,
    timeframe: str,
    count: int,
) -> pd.DataFrame:
    """Return the last `count` *closed* bars, UTC-indexed, oldest first."""
    if timeframe not in TIMEFRAME_MINUTES:
        raise MarketDataError(f"unsupported timeframe {timeframe!r}")
    minutes = TIMEFRAME_MINUTES[timeframe]

    server_now = clock.server_now()
    # Ask for roughly twice the bars needed so weekends/maintenance breaks do not
    # leave us short. `limit` truncates from the start of the range, so it must
    # cover the whole window.
    window_bars = count * 2 + 50
    start = server_now - timedelta(minutes=minutes * window_bars)
    payload = mcp.call_tool(
        "get_chart_history",
        {
            "symbol": symbol,
            "period": timeframe,
            "datetime_from": start.strftime("%Y-%m-%dT%H:%M:%S"),
            "datetime_to": server_now.strftime("%Y-%m-%dT%H:%M:%S"),
            "limit": window_bars + 100,
        },
    )
    if not payload.get("ok"):
        raise MarketDataError(f"get_chart_history failed: {payload}")

    rows = payload.get("history") or []
    if not rows:
        raise MarketDataError(f"no bars returned for {symbol} {timeframe}")

    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"], utc=False)
    df = df.sort_values("time").drop_duplicates("time", keep="last")

    # Drop anything not yet closed in server time.
    cutoff = pd.Timestamp(server_now) - pd.Timedelta(minutes=minutes)
    df = df[df["time"] <= cutoff]
    if df.empty:
        raise MarketDataError("no closed bars after dropping the forming bar")

    df = df.rename(columns={"tick_volume": "volume"})
    df["volume"] = df["volume"].astype(float)
    df["amount"] = df["volume"] * df["close"].astype(float)
    df["spread"] = df["spread"].astype(float) if "spread" in df else 0.0

    # server time -> UTC, once.
    df["time"] = df["time"] - pd.Timedelta(clock.offset)

    df = df[COLUMNS].reset_index(drop=True).tail(count).reset_index(drop=True)
    if len(df) < count:
        raise MarketDataError(f"only {len(df)} closed bars available, need {count}")

    _validate(df, timeframe, minutes)
    return df


def _validate(df: pd.DataFrame, timeframe: str, minutes: int) -> None:
    if df[["open", "high", "low", "close"]].isna().values.any():
        raise MarketDataError("NaN in OHLC")
    if not df["time"].is_monotonic_increasing:
        raise MarketDataError("bar times are not monotonic")
    if (df["high"] < df["low"]).any():
        raise MarketDataError("high < low in input bars")
    if (df["high"] < df[["open", "close"]].max(axis=1) - 1e-9).any():
        raise MarketDataError("high below open/close")
    if (df["low"] > df[["open", "close"]].min(axis=1) + 1e-9).any():
        raise MarketDataError("low above open/close")

    # Intraday gaps: allow up to 4 hours (daily maintenance break on XAUUSD is
    # ~2h around 22:45 server). Flag longer intraday holes; weekends are >24h.
    if minutes <= 60:
        deltas = df["time"].diff().dropna()
        for idx, delta in deltas.items():
            if pd.Timedelta(hours=4) <= delta < pd.Timedelta(hours=20):
                raise MarketDataError(
                    f"suspicious gap of {delta} at {df.loc[idx - 1, 'time']} for {timeframe}"
                )


def future_timestamps(
    last_time: pd.Timestamp, timeframe: str, horizon: int
) -> list[pd.Timestamp]:
    """The next `horizon` bar opens, skipping weekends."""
    minutes = TIMEFRAME_MINUTES[timeframe]
    out: list[pd.Timestamp] = []
    current = pd.Timestamp(last_time)
    while len(out) < horizon:
        current = current + pd.Timedelta(minutes=minutes)
        if current.day_of_week < 5:
            out.append(current)
    return out
