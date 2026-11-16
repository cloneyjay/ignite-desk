"""Agent semantic memory: pattern/knowledge store with tag-based retrieval."""

from __future__ import annotations

from typing import Any

from backend.ignite.services.runtime import Runtime


class SemanticMemory:
    """Pattern/knowledge store with tag-based retrieval."""

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt

    def remember(self, key: str, value: dict[str, Any],
                 tags: list[str] | None = None, confidence: float = 1.0) -> None:
        """Store a pattern/knowledge entry with tags."""
        self.rt.store.semantic_remember(key, value, tags, confidence)

    def recall(self, query: str, tags: list[str] | None = None, limit: int = 10) -> list[dict[str, Any]]:
        """Recall patterns matching query and/or tags."""
        return self.rt.store.semantic_recall(query, tags, limit)

    def forget(self, key: str) -> bool:
        """Delete a semantic memory entry. Returns True if deleted."""
        cursor = self.rt.store._conn.execute(
            "DELETE FROM semantic_memory WHERE key=?", (key,)
        )
        self.rt.store._conn.commit()
        return cursor.rowcount > 0

    def list_by_tag(self, tag: str, limit: int = 50) -> list[dict[str, Any]]:
        """List all entries with a specific tag."""
        return self.recall("", tags=[tag], limit=limit)

    def get(self, key: str) -> dict[str, Any] | None:
        """Get a specific entry by key."""
        row = self.rt.store._conn.execute(
            "SELECT * FROM semantic_memory WHERE key=?", (key,)
        ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["value"] = json.loads(item.pop("value_json"))
        if item.get("tags_json"):
            item["tags"] = json.loads(item.pop("tags_json"))
        return item


import json