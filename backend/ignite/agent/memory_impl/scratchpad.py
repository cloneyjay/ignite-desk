"""Agent scratchpad: TTL-based key-value store for working memory."""

from __future__ import annotations

from typing import Any

from backend.ignite.services.runtime import Runtime
from backend.ignite.store.db import utc_now


class Scratchpad:
    """TTL-based key-value store for agent working memory."""

    def __init__(self, rt: Runtime, default_ttl: int = 3600) -> None:
        self.rt = rt
        self.default_ttl = default_ttl

    def write(self, key: str, value: dict[str, Any], ttl_seconds: int | None = None) -> None:
        """Write a value to the scratchpad with optional TTL."""
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        self.rt.store.scratchpad_write(key, value, ttl)

    def read(self, key: str) -> dict[str, Any] | None:
        """Read a value from the scratchpad. Returns None if expired or not found."""
        return self.rt.store.scratchpad_read(key)

    def delete(self, key: str) -> None:
        """Delete a key from the scratchpad."""
        self.rt.store.scratchpad_delete(key)

    def clear_expired(self) -> int:
        """Remove all expired entries. Returns count of deleted entries."""
        return self.rt.store.scratchpad_cleanup_expired()

    def exists(self, key: str) -> bool:
        """Check if a key exists and is not expired."""
        return self.read(key) is not None

    def keys(self) -> list[str]:
        """List all non-expired keys."""
        rows = self.rt.store._conn.execute(
            "SELECT key FROM scratchpad WHERE expires_at IS NULL OR expires_at > ?",
            (utc_now(),)
        ).fetchall()
        return [row["key"] for row in rows]

    def clear(self) -> int:
        """Clear all entries. Returns count of deleted entries."""
        cursor = self.rt.store._conn.execute("DELETE FROM scratchpad")
        self.rt.store._conn.commit()
        return cursor.rowcount