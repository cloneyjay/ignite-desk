"""Goal 6 auto-memory skeleton: capped index + two-step save.
This module acts as a package proxy for the existing memory implementations
stored in memory_impl/ for backward compatibility.
"""

from __future__ import annotations

import json
import uuid
import os
from typing import Any

# Make this module a package proxy so submodules like scratchpad etc. can be imported
# via backend.ignite.agent.memory.scratchpad
_path = os.path.join(os.path.dirname(__file__), "memory_impl")
if os.path.isdir(_path):
    # Python treats a module as a package if it has __path__
    import types
    __path__ = [_path]

from backend.ignite.store.db import Store, utc_now

# Re-export existing memory implementations for backward compatibility
import importlib

def _load(name):
    return importlib.import_module(f'backend.ignite.agent.memory.{name}')

_scratchpad = _load('scratchpad')
_Episodic = _load('episodic')
_Semantic = _load('semantic')
_Procedural = _load('procedural')

Scratchpad = _scratchpad.Scratchpad
EpisodicMemory = _Episodic.EpisodicMemory
SemanticMemory = _Semantic.SemanticMemory
ProceduralMemory = _Procedural.ProceduralMemory


class MemoryStore:
    """Capped auto-memory with propose/commit workflow."""

    def __init__(self, store: Store, max_entries: int = 200) -> None:
        self.store = store
        self.max_entries = max_entries
        self._proposals: dict[str, dict[str, Any]] = {}

    def propose_memory(self, key: str, content: Any) -> str:
        proposal_id = uuid.uuid4().hex
        self._proposals[proposal_id] = {
            "key": key,
            "content": content,
            "created_at": utc_now(),
        }
        return proposal_id

    def commit_memory(self, proposal_id: str) -> str | None:
        proposal = self._proposals.pop(proposal_id, None)
        if not proposal:
            return None
        key = proposal["key"]
        content = proposal["content"]
        content_json = json.dumps(content, default=str)
        created_at = proposal.get("created_at", utc_now())
        mem_id = uuid.uuid4().hex

        self.store.upsert_memory(mem_id, key, content_json, created_at)
        self._enforce_cap()
        return mem_id

    def reject_memory(self, proposal_id: str) -> bool:
        return self._proposals.pop(proposal_id, None) is not None

    def get_memory(self, key: str) -> Any | None:
        row = self.store.get_memory_by_key(key)
        if not row:
            return None
        self.store.increment_memory_access(key)
        return json.loads(row["content_json"])

    def list_memory(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.store.list_memory(limit)
        out = []
        for r in rows:
            out.append({
                "id": r["id"],
                "key": r["key"],
                "content": json.loads(r["content_json"]),
                "created_at": r["created_at"],
                "access_count": r["access_count"],
            })
        return out

    def _enforce_cap(self) -> None:
        cur = self.store._conn.execute("SELECT COUNT(*) as c FROM agent_memory")
        count = cur.fetchone()["c"]
        if count <= self.max_entries:
            return
        excess = count - self.max_entries
        self.store._conn.execute(
            """
            DELETE FROM agent_memory
            WHERE id IN (
                SELECT id FROM agent_memory
                ORDER BY access_count ASC, created_at ASC, id ASC
                LIMIT ?
            )
            """,
            (excess,),
        )
        self.store._conn.commit()
