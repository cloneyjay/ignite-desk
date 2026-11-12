"""Load the card directory into SQLite, or lint it without writing.

Fail closed: a directory with any lint issue is not written to the store. The
previously loaded catalogue stays in place, and ``/api/health`` reports the
problem so the operator knows the agent is running on stale knowledge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from backend.ignite.knowledge.card import LintIssue, load_cards
from backend.ignite.store.db import Store


@dataclass
class SyncResult:
    loaded: int = 0
    issues: list[LintIssue] = field(default_factory=list)
    written: bool = False
    by_scope: dict[str, int] = field(default_factory=dict)
    by_status: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.issues

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "loaded": self.loaded,
            "written": self.written,
            "by_scope": dict(self.by_scope),
            "by_status": dict(self.by_status),
            "issues": [issue.as_dict() for issue in self.issues],
        }


def lint_cards(directory: Path | str) -> list[LintIssue]:
    return load_cards(directory).issues


def sync_cards(store: Store, directory: Path | str) -> SyncResult:
    result = load_cards(directory)
    summary = SyncResult(issues=list(result.issues))
    for card in result.cards:
        summary.by_scope[card.scope] = summary.by_scope.get(card.scope, 0) + 1
        summary.by_status[card.status] = summary.by_status.get(card.status, 0) + 1
    if result.issues:
        return summary
    rows = [card.to_row() for card in result.cards]
    store.sync_knowledge_cards(rows)
    summary.loaded = len(rows)
    summary.written = True
    return summary
