"""Agent procedural memory: condition-action rules with confidence scoring."""

from __future__ import annotations

from typing import Any

from backend.ignite.services.runtime import Runtime


class ProceduralMemory:
    """Condition-action rules with confidence scoring and usage tracking."""

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt

    def learn(self, trigger: str, action: str, condition: dict[str, Any],
              confidence: float = 1.0) -> None:
        """Learn or update a procedural rule."""
        self.rt.store.procedural_learn(trigger, action, condition, confidence)

    def recall(self, trigger: str) -> dict[str, Any] | None:
        """Recall a specific procedural rule."""
        return self.rt.store.procedural_recall(trigger)

    def query(self, limit: int = 100) -> list[dict[str, Any]]:
        """Query all procedural rules sorted by confidence and usage."""
        return self.rt.store.procedural_query(limit)

    def reinforce(self, trigger: str, success: bool = True) -> bool:
        """Update confidence based on outcome."""
        rule = self.recall(trigger)
        if not rule:
            return False

        new_use_count = rule.get("use_count", 0) + 1
        new_success_count = rule.get("success_count", 0) + (1 if success else 0)
        new_confidence = new_success_count / new_use_count if new_use_count > 0 else 0.5

        self.rt.store._conn.execute(
            """
            UPDATE procedural_memory SET
                use_count=?, success_count=?, confidence=?, updated_at=?
            WHERE trigger=?
            """,
            (new_use_count, new_success_count, new_confidence, utc_now(), trigger),
        )
        self.rt.store._conn.commit()
        return True

    def get_high_confidence_rules(self, min_confidence: float = 0.7, limit: int = 20) -> list[dict[str, Any]]:
        """Get high-confidence procedural rules."""
        rows = self.rt.store._conn.execute(
            "SELECT * FROM procedural_memory WHERE confidence >= ? ORDER BY confidence DESC, use_count DESC LIMIT ?",
            (min_confidence, limit)
        ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["condition"] = json.loads(item.pop("condition_json"))
            results.append(item)
        return results


import json
from backend.ignite.store.db import utc_now