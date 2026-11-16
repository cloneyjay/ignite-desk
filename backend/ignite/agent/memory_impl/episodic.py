"""Agent episodic memory: append-only episodes for trades, analyses, decisions."""

from __future__ import annotations

from typing import Any

from backend.ignite.services.runtime import Runtime


class EpisodicMemory:
    """Append-only episodic memory for trades, analyses, decisions."""

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt

    def record(self, type: str, payload: dict[str, Any],
               symbol: str | None = None, timeframe: str | None = None,
               outcome: str | None = None, tags: list[str] | None = None) -> int:
        """Record an episode. Returns the episode ID."""
        return self.rt.store.episodic_record(
            type=type,
            payload=payload,
            symbol=symbol,
            timeframe=timeframe,
            outcome=outcome,
            tags=tags,
        )

    def query(self, symbol: str | None = None, type: str | None = None,
              timeframe: str | None = None, limit: int = 100,
              since: str | None = None) -> list[dict[str, Any]]:
        """Query episodes with optional filters."""
        return self.rt.store.episodic_query(
            symbol=symbol, type=type, timeframe=timeframe, limit=limit, since=since
        )

    def get_trades(self, symbol: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Get trade episodes."""
        return self.query(type="trade", symbol=symbol, limit=limit)

    def get_analyses(self, symbol: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Get analysis episodes."""
        return self.query(type="analysis", symbol=symbol, limit=limit)

    def get_decisions(self, symbol: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Get decision episodes."""
        return self.query(type="decision", symbol=symbol, limit=limit)

    def get_reflections(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get reflection episodes."""
        return self.query(type="reflection", limit=limit)

    def get_recent(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get most recent episodes of any type."""
        return self.query(limit=limit)